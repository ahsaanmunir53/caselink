"""Everything else: health, logins, overview, reports, identifiers, alerts, questions, audit, quality, import/export."""

import hmac
import json
import time
from collections import Counter
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.ai import model_status
from app.ai.agents import translate
from app.ai.qa import ask
from app.api.common import case_json, limit, reader, report_json
from app.auth import (
    DEMO_USERS,
    Principal,
    make_token,
    require_analyst,
    require_supervisor,
    verify_password,
)
from app.core.embed import embed
from app.db.models import Alert, AuditEntry, Case, Entity, Mention, Report, Suggestion, User
from app.extract.rules import extract
from app.intel import audit, quality
from app.intel.stix import case_bundle, reports_from_bundle
from app.link import service

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- health

@router.get("/health")
async def health(request: Request) -> dict:
    s, deps = request.app.state.settings, request.app.state.deps
    return {"status": "ok", "app": "CaseLink", "llm": s.resolved_llm_provider if deps.models else False,
            "model": request.app.state.model_label, "models": [model_status.describe(m, detail=False) for m in deps.models],
            "storage": "postgres" if s.uses_postgres else "local", "demo_mode": s.demo_mode, "four_eyes": s.four_eyes,
            "hoshiyar_link": bool(s.hoshiyar_api_url and s.hoshiyar_integration_key), "version": "0.1.0"}


@router.get("/health/ai")
async def health_ai(request: Request) -> dict:
    limit(request, "ai", 10)
    from app.ai.agents import call_text

    results = []
    for model in request.app.state.deps.models:
        started = time.monotonic()
        text, used, errors = await call_text([model], "Reply with the single word OK.", "ping", 20)
        kind = None if text else model_status.describe(model)["status"]
        results.append({"model": model_status.model_key(model), "ok": bool(text), "ms": int((time.monotonic() - started) * 1000),
                        **({"error": errors[-1][:200], "kind": kind} if not text and errors else {})})
    return {"ok": any(r["ok"] for r in results), "models": results, "chain": request.app.state.model_label}


# --------------------------------------------------------------------------- logins

class Login(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


@router.post("/auth/login")
async def login(body: Login, request: Request) -> dict:
    limit(request, f"login:{body.email.lower()}", 10)
    s = request.app.state.settings
    async with request.app.state.deps.sessionmaker() as session:
        user = (await session.execute(select(User).where(User.email == body.email.lower().strip()))).scalar_one_or_none()
    if not user or not user.active or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password.")
    return {"token": make_token(s, user.email, user.role), "user": {"email": user.email, "name": user.name, "role": user.role}}


class DemoLogin(BaseModel):
    email: str


@router.get("/auth/demo-users")
async def demo_users(request: Request) -> dict:
    if not request.app.state.settings.demo_mode:
        return {"users": []}
    return {"users": [{"email": e, "name": n, "role": r} for e, n, r in DEMO_USERS]}


@router.post("/auth/demo")
async def demo_login(body: DemoLogin, request: Request) -> dict:
    s = request.app.state.settings
    limit(request, "login", 30)
    if not s.demo_mode:
        raise HTTPException(404, "Demo logins are switched off.")
    async with request.app.state.deps.sessionmaker() as session:
        user = (await session.execute(select(User).where(User.email == body.email, User.demo.is_(True)))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "No such demo account.")
    return {"token": make_token(s, user.email, user.role), "user": {"email": user.email, "name": user.name, "role": user.role}}


@router.get("/auth/me")
async def me(request: Request, who: Principal = Depends(require_analyst)) -> dict:
    return {"email": who.email, "name": who.name, "role": who.role, "demo": who.demo}


@router.get("/auth/whoami")
async def whoami(request: Request) -> dict:
    from app.auth import principal_from_request

    try:
        who = await principal_from_request(request, "viewer")
    except HTTPException:
        return {"user": None}
    return {"user": {"email": who.email, "name": who.name, "role": who.role, "demo": who.demo}}


# --------------------------------------------------------------------------- overview

@router.get("/overview")
async def overview(request: Request, _=Depends(reader)) -> dict:
    deps = request.app.state.deps
    async with deps.sessionmaker() as session:
        reports = (await session.execute(select(Report))).scalars().all()
        cases = (await session.execute(select(Case).where(Case.status.notin_(("merged",))))).scalars().all()
        pending = (await session.execute(select(func.count()).select_from(Suggestion).where(Suggestion.status == "pending"))).scalar()
        alerts = (await session.execute(select(Alert).order_by(Alert.created_at.desc()).limit(8))).scalars().all()
        emerging = await service.emerging(session)
        top_money = await _top_money(session, 8)
    by_status = Counter(c.status for c in cases)
    in_case = sum(1 for r in reports if r.case_id)
    months = Counter(r.received_at.strftime("%Y-%m") for r in reports)
    titles = {c.id: c.title for c in cases}
    return {
        "reports": len(reports), "reports_in_cases": in_case, "cases": len(cases), "cases_by_status": dict(by_status),
        "pending_suggestions": pending, "total_loss": sum(r.amount_lost or 0 for r in reports),
        "synthetic": all(r.synthetic for r in reports) if reports else False,
        "by_kind": Counter(r.kind for r in reports).most_common(), "by_source": Counter(r.source for r in reports).most_common(),
        "by_language": Counter(r.language for r in reports).most_common(),
        "by_city": Counter(r.reporter_city for r in reports if r.reporter_city).most_common(10),
        "by_country": Counter(r.destination_country for r in reports if r.destination_country).most_common(10),
        "by_month": sorted(months.items()),
        "top_cases": [case_json(c) for c in sorted(cases, key=lambda c: -c.priority)[:6]],
        "emerging": [{**e, "title": titles.get(e["case_id"])} for e in emerging],
        "alerts": [_alert_json(a) for a in alerts],
        "top_money": top_money,
    }


async def _top_money(session, n: int) -> list[dict]:
    rows = (await session.execute(
        select(Entity.id, Entity.kind, Entity.display, Mention.report_id, Report.amount_lost, Report.case_id)
        .join(Mention, Mention.entity_id == Entity.id).join(Report, Report.id == Mention.report_id)
        .where(Entity.official.is_(False), Entity.kind.in_(("phone", "iban")), Mention.role.in_(("wallet", "payee"))))).all()
    agg: dict[int, dict] = {}
    for eid, kind, display, _rid, amount, cid in rows:
        a = agg.setdefault(eid, {"entity_id": eid, "kind": kind, "display": display, "reports": 0, "total": 0, "cases": set()})
        a["reports"] += 1
        a["total"] += amount or 0
        if cid:
            a["cases"].add(cid)
    out = sorted(agg.values(), key=lambda a: (-a["total"], -a["reports"]))[:n]
    return [{**a, "cases": sorted(a["cases"])} for a in out]


def _alert_json(a: Alert) -> dict:
    return {"id": a.id, "kind": a.kind, "message": a.message, "case_id": a.case_id, "report_id": a.report_id,
            "seen": a.seen, "created_at": a.created_at.isoformat()}


@router.get("/alerts")
async def alerts(request: Request, _=Depends(reader)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        rows = (await session.execute(select(Alert).order_by(Alert.created_at.desc()).limit(100))).scalars().all()
        emerging = await service.emerging(session)
    return {"alerts": [_alert_json(a) for a in rows], "emerging": emerging}


@router.post("/alerts/{aid}/seen")
async def alert_seen(aid: int, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        a = await session.get(Alert, aid)
        if a:
            a.seen = True
            await session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- reports

@router.get("/reports")
async def list_reports(request: Request, q: str | None = None, kind: str | None = None, source: str | None = None,
                       case: str | None = None, unassigned: bool = False, language: str | None = None,
                       page: int = 1, size: int = 50, _=Depends(reader)) -> dict:
    size = max(1, min(size, 200))
    async with request.app.state.deps.sessionmaker() as session:
        if q:
            from app.intel.search import search_reports

            hits = await search_reports(session, q, 100)
            ids = [h["id"] for h in hits]
            rows = (await session.execute(select(Report).where(Report.id.in_(ids)))).scalars().all()
            order = {rid: i for i, rid in enumerate(ids)}
            rows = sorted(rows, key=lambda r: order[r.id])
        else:
            query = select(Report)
            if kind:
                query = query.where(Report.kind == kind)
            if source:
                query = query.where(Report.source == source)
            if case:
                query = query.where(Report.case_id == case.upper())
            if unassigned:
                query = query.where(Report.case_id.is_(None))
            if language:
                query = query.where(Report.language == language)
            rows = (await session.execute(query.order_by(Report.received_at.desc()))).scalars().all()
    total = len(rows)
    rows = rows[(page - 1) * size: page * size]
    return {"total": total, "page": page, "reports": [report_json(r, full=False) for r in rows]}


@router.get("/reports/{rid}")
async def get_report(rid: str, request: Request, _=Depends(reader)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        r = await session.get(Report, rid.upper())
        if not r:
            raise HTTPException(404, "No such report.")
        ents = (await session.execute(
            select(Entity, Mention.role, Mention.source, Mention.raw).join(Mention, Mention.entity_id == Entity.id)
            .where(Mention.report_id == r.id))).all()
        others = (await session.execute(select(Report).where(Report.id != r.id))).scalars().all()
    vec = embed(r.text)
    similar = sorted(((float(vec @ embed(o.text)), o) for o in others), key=lambda x: -x[0])[:5]
    return {"report": report_json(r), "entities": [
        {"id": e.id, "kind": e.kind, "value": e.value, "display": e.display, "official": e.official, "watched": e.watched,
         "valid": e.valid, "role": role, "found_by": src, "raw": raw} for e, role, src, raw in ents],
        "similar": [{"id": o.id, "score": round(s, 3), "case_id": o.case_id, "kind": o.kind, "text": o.text[:160]} for s, o in similar]}


class ReportIn(BaseModel):
    text: str = Field(min_length=10, max_length=6000)
    source: str = Field(default="police_desk", max_length=24)
    channel: str = Field(default="walk_in", max_length=24)
    received_at: str | None = None
    reporter_city: str | None = Field(default=None, max_length=64)
    destination_country: str | None = Field(default=None, max_length=64)
    amount_lost: int | None = Field(default=None, ge=0, le=10**12)
    kind: str | None = Field(default=None, max_length=24)


class ReportsIn(BaseModel):
    reports: list[ReportIn] = Field(min_length=1, max_length=200)
    use_ai: bool = True


@router.post("/reports")
async def add_reports(body: ReportsIn, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    deps = request.app.state.deps
    limit(request, "ingest", 20)
    items = [r.model_dump() for r in body.reports]
    result = await deps.ingest_graph.ainvoke({"items": items, "actor": f"analyst:{who.email}", "use_ai": body.use_ai},
                                             {"configurable": {"thread_id": f"ingest-{datetime.now(UTC):%Y%m%d%H%M%S%f}"}})
    return {"new_ids": result.get("new_ids", []), "outcomes": result.get("outcomes", []), "linker": result.get("rebuild", {}),
            "ai_extracted": sorted((result.get("ai_found") or {}).keys())}


@router.post("/reports/upload")
async def upload_reports(request: Request, file: UploadFile = File(...), who: Principal = Depends(require_analyst)) -> dict:
    """A JSON list of reports, JSON lines, or a CSV with a 'text' column."""
    import csv
    import io

    data = (await file.read())[:3_000_000].decode("utf-8", errors="replace")
    items: list[dict] = []
    try:
        parsed = json.loads(data)
        items = parsed if isinstance(parsed, list) else parsed.get("reports", []) if isinstance(parsed, dict) else []
        if isinstance(parsed, dict) and parsed.get("type") == "bundle":
            items = reports_from_bundle(parsed)
    except json.JSONDecodeError:
        lines = [ln for ln in data.splitlines() if ln.strip()]
        if lines and lines[0].lstrip().startswith("{"):
            items = [json.loads(ln) for ln in lines]
        else:
            items = list(csv.DictReader(io.StringIO(data)))
    clean = []
    for it in items[:200]:
        if isinstance(it, dict) and str(it.get("text") or "").strip():
            try:
                clean.append(ReportIn(**{k: v for k, v in it.items() if k in ReportIn.model_fields}).model_dump())
            except Exception:
                continue
    if not clean:
        raise HTTPException(422, "No reports with a 'text' field were found in the file.")
    return await add_reports(ReportsIn(reports=[ReportIn(**c) for c in clean], use_ai=False), request, who)


@router.post("/reports/{rid}/translate")
async def translate_report(rid: str, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    deps = request.app.state.deps
    limit(request, "ai", 20)
    async with deps.sessionmaker() as session:
        r = await session.get(Report, rid.upper())
        if not r:
            raise HTTPException(404, "No such report.")
        if r.translation:
            return {"translation": r.translation, "model": r.translation_model, "cached": True}
        text, model = await translate(deps.models, deps.settings.llm_timeout_seconds, r.text)
        if not text:
            raise HTTPException(503, "Translation needs an AI model, and none answered right now.")
        r.translation, r.translation_model = text, model
        await audit.record(session, "agent:translator", "report.translated", "report", r.id, {"model": model, "requested_by": who.email})
        await session.commit()
    return {"translation": text, "model": model, "cached": False}


# --------------------------------------------------------------------------- identifiers

@router.get("/entities")
async def entities(request: Request, q: str | None = None, kind: str | None = None, watched: bool = False,
                   _=Depends(reader)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        query = select(Entity, func.count(Mention.id)).join(Mention, Mention.entity_id == Entity.id).group_by(Entity.id)
        if kind:
            query = query.where(Entity.kind == kind)
        if watched:
            query = query.where(Entity.watched.is_(True))
        if q:
            found = extract(q).entities
            values = {f.value for f in found} | {q.strip().lower()}
            query = query.where(Entity.value.in_(values) | Entity.display.ilike(f"%{q.strip()[:60]}%"))
        rows = (await session.execute(query.order_by(func.count(Mention.id).desc()).limit(200))).all()
    return {"entities": [{"id": e.id, "kind": e.kind, "value": e.value, "display": e.display, "official": e.official,
                          "watched": e.watched, "watch_note": e.watch_note, "valid": e.valid, "reports": n} for e, n in rows]}


@router.get("/entities/{eid}")
async def entity(eid: int, request: Request, _=Depends(reader)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        e = await session.get(Entity, eid)
        if not e:
            raise HTTPException(404, "No such identifier.")
        rows = (await session.execute(select(Report, Mention.role).join(Mention, Mention.report_id == Report.id)
                                      .where(Mention.entity_id == eid).order_by(Report.received_at))).all()
    return {"entity": {"id": e.id, "kind": e.kind, "value": e.value, "display": e.display, "official": e.official,
                       "watched": e.watched, "watch_note": e.watch_note, "valid": e.valid},
            "reports": [{**report_json(r, full=False), "role": role} for r, role in rows],
            "cases": sorted({r.case_id for r, _ in rows if r.case_id}),
            "total": sum(r.amount_lost or 0 for r, _ in rows)}


class WatchIn(BaseModel):
    watched: bool
    note: str = Field(default="", max_length=255)


@router.post("/entities/{eid}/watch")
async def watch(eid: int, body: WatchIn, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        e = await session.get(Entity, eid)
        if not e:
            raise HTTPException(404, "No such identifier.")
        e.watched, e.watch_note = body.watched, (body.note or None)
        await audit.record(session, f"analyst:{who.email}", "entity.watch" if body.watched else "entity.unwatch", "entity",
                           str(e.id), {"display": e.display, "note": body.note})
        await session.commit()
    return {"watched": body.watched}


# --------------------------------------------------------------------------- questions

class Question(BaseModel):
    question: str = Field(min_length=3, max_length=600)


@router.post("/ask")
async def ask_cases(body: Question, request: Request, _=Depends(reader)) -> dict:
    limit(request, "ai", 15)
    result = await ask(request.app.state.deps, body.question)
    async with request.app.state.deps.sessionmaker() as session:
        await audit.record(session, "agent:assistant", "question.answered", "question", "-", {
            "question": body.question[:300], "citations": result.get("citations"), "removed": result.get("removed_citations"),
            "model": result.get("model"), "tools": [t["tool"] for t in result.get("tools", [])]})
        await session.commit()
    return result


# --------------------------------------------------------------------------- audit and quality

@router.get("/audit")
async def audit_log(request: Request, page: int = 1, size: int = 50, actor: str | None = None, object_id: str | None = None,
                    _=Depends(reader)) -> dict:
    size = max(1, min(size, 200))
    async with request.app.state.deps.sessionmaker() as session:
        q = select(AuditEntry)
        if actor:
            q = q.where(AuditEntry.actor.ilike(f"%{actor[:60]}%"))
        if object_id:
            q = q.where(AuditEntry.object_id == object_id)
        total = (await session.execute(select(func.count()).select_from(q.subquery()))).scalar()
        rows = (await session.execute(q.order_by(AuditEntry.id.desc()).offset((page - 1) * size).limit(size))).scalars().all()
    return {"total": total, "entries": [{"id": a.id, "ts": a.ts.isoformat(), "actor": a.actor, "action": a.action,
                                         "object_type": a.object_type, "object_id": a.object_id, "details": a.details,
                                         "hash": a.hash, "prev_hash": a.prev_hash} for a in rows]}


@router.get("/audit/verify")
async def audit_verify(request: Request, _=Depends(reader)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        return await audit.verify(session)


_quality_cache: dict = {}


@router.get("/quality")
async def quality_report(request: Request, _=Depends(reader)) -> dict:
    deps = request.app.state.deps
    async with deps.sessionmaker() as session:
        reps = list((await service.load_reps(session)).values())
        synthetic = (await session.execute(select(func.count()).select_from(Report).where(Report.synthetic.is_(True)))).scalar()
        cases = (await session.execute(select(Report.id, Report.case_id))).all()
        decided = Counter((await session.execute(select(Suggestion.status))).scalars().all())
    if not synthetic:
        return {"available": False, "reason": "Quality is measured on the synthetic dataset, which is not loaded."}
    key = (len(reps), synthetic)
    if key not in _quality_cache:
        _quality_cache.clear()
        _quality_cache[key] = quality.offline_report(reps, deps.settings)
    out = dict(_quality_cache[key])
    from app.data.synthetic import generate

    _, truth = generate()
    groups: dict[str, set] = {}
    for rid, cid in cases:
        if cid:
            groups.setdefault(cid, set()).add(rid)
    out["current_cases"] = quality.pairwise(list(groups.values()), {k: v for k, v in truth.items() if k in {r for r, _ in cases}})
    out["decisions"] = dict(decided)
    out["available"] = True
    return out


# --------------------------------------------------------------------------- import and export

@router.post("/import/hoshiyar")
async def import_hoshiyar(request: Request, who: Principal = Depends(require_analyst)) -> dict:
    """Pull Hoshiyar's confirmed scam websites (STIX 2.1) and add them as intelligence reports."""
    s = request.app.state.settings
    if not (s.hoshiyar_api_url and s.hoshiyar_integration_key):
        raise HTTPException(503, "Set HOSHIYAR_API_URL and HOSHIYAR_INTEGRATION_KEY to pull from Hoshiyar.")
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.get(f"{s.hoshiyar_api_url.rstrip('/')}/api/stix", headers={"X-Integration-Key": s.hoshiyar_integration_key})
            r.raise_for_status()
            bundle = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Could not read Hoshiyar's export: {type(exc).__name__}") from exc
    items = reports_from_bundle(bundle)
    if not items:
        return {"new_ids": [], "outcomes": [], "note": "Hoshiyar has no confirmed websites to share yet."}
    return await add_reports(ReportsIn(reports=[ReportIn(**{k: v for k, v in it.items() if k in ReportIn.model_fields})
                                                for it in items[:200]], use_ai=False), request, who)


@router.get("/export/stix")
async def export_all(request: Request, who: Principal = Depends(require_supervisor)) -> dict:
    s = request.app.state.settings
    async with request.app.state.deps.sessionmaker() as session:
        q = select(Case).where(Case.status.in_(("open", "investigating", "referred", "closed")))
        if s.four_eyes:
            q = q.where(Case.confirmed_by.is_not(None))
        cases = (await session.execute(q)).scalars().all()
        pairs = [(c, await service.case_facts(session, c.id)) for c in cases]
        await audit.record(session, f"user:{who.email}", "cases.exported", "system", "stix", {"cases": [c.id for c in cases]})
        await session.commit()
    return case_bundle(pairs)


# --------------------------------------------------------------------------- scheduled jobs

def _cron_ok(request: Request, secret: str | None) -> None:
    s = request.app.state.settings
    if not s.cron_secret:
        raise HTTPException(404, "Scheduled jobs are not set up.")
    if not secret or not secret.isascii() or not hmac.compare_digest(secret, s.cron_secret):
        raise HTTPException(401, "Wrong cron secret.")


@router.post("/cron/reset-demo")
async def reset_demo(request: Request, x_cron_secret: str | None = Header(default=None)) -> dict:
    """Nightly: put the public demo back to its starting state."""
    _cron_ok(request, x_cron_secret)
    if not request.app.state.settings.demo_mode:
        raise HTTPException(409, "Only demo deployments are reset.")
    from app.seed import reset_and_seed

    return await reset_and_seed(request.app.state.deps)


@router.post("/cron/rebuild")
async def cron_rebuild(request: Request, x_cron_secret: str | None = Header(default=None)) -> dict:
    _cron_ok(request, x_cron_secret)
    async with request.app.state.deps.sessionmaker() as session:
        out = await service.rebuild(session, request.app.state.settings, "system:cron")
        await session.commit()
    return out


@router.post("/cron/digest")
async def cron_digest(request: Request, x_cron_secret: str | None = Header(default=None)) -> dict:
    """Daily note to the supervisors' Telegram channel: new proposed cases, waiting suggestions, emerging patterns."""
    _cron_ok(request, x_cron_secret)
    s = request.app.state.settings
    async with request.app.state.deps.sessionmaker() as session:
        proposed = (await session.execute(select(Case).where(Case.status == "proposed").order_by(Case.priority.desc()))).scalars().all()
        pending = (await session.execute(select(func.count()).select_from(Suggestion).where(Suggestion.status == "pending"))).scalar()
        emerging = await service.emerging(session)
    lines = ["CaseLink daily digest", f"Proposed cases waiting for review: {len(proposed)}", f"Suggestions waiting: {pending}"]
    lines += [f"- {c.id} (priority {c.priority}): {c.title}" for c in proposed[:5]]
    if emerging:
        lines.append("Growing fast in the last two weeks: " + ", ".join(f"{e['case_id']} (+{e['recent']})" for e in emerging[:5]))
    if s.public_app_url:
        lines.append(s.public_app_url)
    text = "\n".join(lines)
    sent = False
    if s.telegram_bot_token and s.telegram_alert_chat_id:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                                  json={"chat_id": s.telegram_alert_chat_id, "text": text, "disable_web_page_preview": True})
            sent = r.status_code == 200
    return {"sent": sent, "text": text}


@router.get("/privacy")
async def privacy() -> dict:
    return {"points": [
        "The public demo holds only synthetic reports; every person, number, account and website in it is invented.",
        "Phone numbers, IBANs and emails are replaced by tokens before any text is sent to a language model.",
        "Language models only read, draft and suggest. Links between reports are decided by rules and by people.",
        "Every action by an agent or a person is written to a hash-chained audit log.",
        "Exports are marked TLP:AMBER and, with the four-eyes rule on, need a second person's confirmation.",
    ]}
