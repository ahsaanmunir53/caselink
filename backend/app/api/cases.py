"""Cases and suggestions: reading them, reviewing them, and the case workflow."""

import csv
import io
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.agent.graphs import resume_review, review_status, start_review
from app.ai.agents import adjudicate, write_summary
from app.api.common import case_json, limit, reader, report_json
from app.auth import Principal, require_analyst, require_viewer
from app.db.models import Case, Link, Note, Report, Suggestion
from app.intel import audit
from app.intel.stix import case_bundle
from app.link import service
from app.link.service import KIND_TITLES

router = APIRouter(prefix="/api")

WORKFLOW = {"open": {"investigating"}, "investigating": {"referred", "closed", "open"},
            "referred": {"closed", "investigating"}, "closed": {"investigating"}}


async def _counts(session, case_ids: list[str]) -> dict[str, dict]:
    rows = (await session.execute(
        select(Report.case_id, func.count(Report.id), func.sum(Report.amount_lost), func.max(Report.received_at))
        .where(Report.case_id.in_(case_ids)).group_by(Report.case_id))).all()
    return {cid: {"reports": n, "loss": int(total or 0), "last_report": last.isoformat() if last else None}
            for cid, n, total, last in rows}


@router.get("/cases")
async def list_cases(request: Request, status: str | None = None, kind: str | None = None, q: str | None = None,
                     _=Depends(reader)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        query = select(Case)
        if status:
            query = query.where(Case.status.in_(status.split(",")))
        else:
            query = query.where(Case.status.notin_(("merged",)))
        if kind:
            query = query.where(Case.kind == kind)
        cases = (await session.execute(query.order_by(Case.priority.desc()))).scalars().all()
        if q:
            cases = [c for c in cases if q.lower() in c.title.lower() or q.lower() == c.id.lower()]
        counts = await _counts(session, [c.id for c in cases])
        pending = Counter()
        for s in (await session.execute(select(Suggestion).where(Suggestion.status == "pending"))).scalars().all():
            for cid in (s.case_id, s.other_case_id):
                if cid:
                    pending[cid] += 1
    return {"cases": [case_json(c, {**counts.get(c.id, {"reports": 0, "loss": 0, "last_report": None}),
                                    "pending_suggestions": pending[c.id]}) for c in cases]}


@router.get("/cases/{case_id}")
async def get_case(case_id: str, request: Request, _=Depends(reader)) -> dict:
    deps = request.app.state.deps
    async with deps.sessionmaker() as session:
        case = await session.get(Case, case_id.upper())
        if not case:
            raise HTTPException(404, "No such case.")
        facts = await service.case_facts(session, case.id)
        notes = (await session.execute(select(Note).where(Note.case_id == case.id).order_by(Note.created_at))).scalars().all()
        sugs = (await session.execute(select(Suggestion).where(
            (Suggestion.case_id == case.id) | (Suggestion.other_case_id == case.id)).order_by(Suggestion.score.desc()))).scalars().all()
        related = await _related_cases(session, case.id, facts)
    review = await review_status(deps.review_graph, case.id) if deps.review_graph else {"waiting": False}
    return {
        "case": case_json(case, {"reports": len(facts["reports"]), "loss": facts["total_loss"]}),
        "summary": case.summary,
        "review": review,
        "reports": [report_json(r, full=True) for r in facts["reports"]],
        "mentions": facts["mentions"],
        "entities": facts["entities"],
        "money": facts["money"],
        "key_identifiers": [{**k, "display": next((e["display"] for e in facts["entities"] if e["value"] == k["value"]), k["value"])}
                            for k in facts["key_identifiers"]],
        "links": [{"a": lk.report_a, "b": lk.report_b, "kind": lk.kind, "strength": lk.strength, "detail": lk.detail, "score": lk.score}
                  for lk in facts["links"]][:600],
        "timeline": [{"id": r.id, "date": r.received_at.isoformat(), "amount": r.amount_lost, "city": r.reporter_city}
                     for r in facts["reports"]],
        "cities": facts["cities"], "countries": facts["countries"], "sources": facts["sources"], "languages": facts["languages"],
        "first_seen": facts["first_seen"].isoformat() if facts["first_seen"] else None,
        "last_seen": facts["last_seen"].isoformat() if facts["last_seen"] else None,
        "notes": [{"id": n.id, "author": n.author, "text": n.text, "created_at": n.created_at.isoformat()} for n in notes],
        "suggestions": [_suggestion_json(s) for s in sugs],
        "related": related,
        "four_eyes": request.app.state.settings.four_eyes,
    }


async def _related_cases(session, case_id: str, facts: dict) -> list[dict]:
    """Other cases sharing a weak link (same agency name, abbreviation) with this one."""
    ids = [r.id for r in facts["reports"]]
    if not ids:
        return []
    rows = (await session.execute(select(Link).where(Link.strength == "weak", (Link.report_a.in_(ids)) | (Link.report_b.in_(ids))))).scalars().all()
    others = {lk.report_b if lk.report_a in ids else lk.report_a: lk.detail for lk in rows}
    reps = (await session.execute(select(Report.id, Report.case_id).where(Report.id.in_(list(others))))).all()
    found: dict[str, set] = {}
    for rid, cid in reps:
        if cid and cid != case_id:
            found.setdefault(cid, set()).add(others[rid])
    out = []
    for cid, details in found.items():
        c = await session.get(Case, cid)
        if c and c.status != "merged":
            out.append({"id": cid, "title": c.title, "status": c.status, "why": sorted(details)[:3]})
    return out


@router.get("/cases/{case_id}/graph")
async def case_graph(case_id: str, request: Request, _=Depends(reader)) -> dict:
    """Reports and the identifiers that connect them, for the network view."""
    async with request.app.state.deps.sessionmaker() as session:
        facts = await service.case_facts(session, case_id.upper())
    if not facts["reports"]:
        raise HTTPException(404, "No such case.")
    keys = {k["value"]: k for k in facts["key_identifiers"]}
    money = {m["value"] for m in facts["money"]}
    nodes = [{"id": r.id, "type": "report", "label": r.id, "kind": r.kind, "date": r.received_at.isoformat(),
              "amount": r.amount_lost, "city": r.reporter_city, "pinned": r.pinned} for r in facts["reports"]]
    edges = []
    for e in facts["entities"]:
        if e["official"] or (len(e["reports"]) < 2 and e["kind"] != "agency"):
            continue
        nid = f"E{e['id']}"
        nodes.append({"id": nid, "type": "entity", "kind": e["kind"], "label": e["display"], "reports": len(e["reports"]),
                      "bridge": bool(keys.get(e["value"], {}).get("bridge")), "money": e["value"] in money,
                      "watched": e["watched"], "sources": e["sources"]})
        edges += [{"source": rid, "target": nid} for rid in e["reports"]]
    return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------- review (human in the loop)

class Decision(BaseModel):
    decision: str = Field(pattern="^(approve|reject|redraft)$")
    note: str = Field(default="", max_length=1000)


@router.post("/cases/{case_id}/review")
async def review_start(case_id: str, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    deps = request.app.state.deps
    limit(request, "ai", 20)
    async with deps.sessionmaker() as session:
        case = await session.get(Case, case_id.upper())
        if not case:
            raise HTTPException(404, "No such case.")
        if case.status != "proposed":
            raise HTTPException(409, f"The case is {case.status}; only proposed cases are reviewed.")
    status = await review_status(deps.review_graph, case.id)
    if status["waiting"]:
        return status
    return await start_review(deps.review_graph, case.id)


@router.post("/cases/{case_id}/review/decision")
async def review_decide(case_id: str, body: Decision, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    deps = request.app.state.deps
    status = await review_status(deps.review_graph, case_id.upper())
    if not status["waiting"]:
        raise HTTPException(409, "There is no draft waiting for a decision. Start a review first.")
    limit(request, "ai", 20)
    return await resume_review(deps.review_graph, case_id.upper(), {"decision": body.decision, "note": body.note, "by": who.email})


class StatusChange(BaseModel):
    status: str
    note: str = Field(default="", max_length=1000)


@router.post("/cases/{case_id}/status")
async def change_status(case_id: str, body: StatusChange, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    settings = request.app.state.settings
    async with request.app.state.deps.sessionmaker() as session:
        case = await session.get(Case, case_id.upper())
        if not case:
            raise HTTPException(404, "No such case.")
        if body.status not in WORKFLOW.get(case.status, set()):
            raise HTTPException(409, f"A {case.status} case cannot move to {body.status}.")
        if body.status == "referred" and settings.four_eyes and not case.confirmed_by:
            raise HTTPException(409, "Four-eyes rule: a second person must confirm the case before it is referred.")
        old = case.status
        case.status, case.updated_at = body.status, datetime.now(UTC)
        if body.note:
            session.add(Note(case_id=case.id, author=who.email, text=f"[{old} → {body.status}] {body.note}"))
        await audit.record(session, f"analyst:{who.email}", "case.status", "case", case.id, {"from": old, "to": body.status, "note": body.note})
        await session.commit()
    return {"status": body.status}


@router.post("/cases/{case_id}/confirm")
async def confirm_case(case_id: str, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    """The second pair of eyes: someone other than the approver confirms the case."""
    async with request.app.state.deps.sessionmaker() as session:
        case = await session.get(Case, case_id.upper())
        if not case or case.status not in ("open", "investigating"):
            raise HTTPException(409, "Only an approved (open or investigating) case can be confirmed.")
        if case.approved_by == who.email:
            raise HTTPException(409, "Four-eyes rule: the person who approved the case cannot also confirm it.")
        case.confirmed_by, case.confirmed_at = who.email, datetime.now(UTC)
        await audit.record(session, f"analyst:{who.email}", "case.confirmed", "case", case.id, {"approved_by": case.approved_by})
        await session.commit()
    return {"confirmed_by": who.email}


class Assign(BaseModel):
    assignee: str | None = Field(default=None, max_length=255)


@router.post("/cases/{case_id}/assign")
async def assign(case_id: str, body: Assign, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        case = await session.get(Case, case_id.upper())
        if not case:
            raise HTTPException(404, "No such case.")
        case.assignee = body.assignee or None
        await audit.record(session, f"analyst:{who.email}", "case.assigned", "case", case.id, {"assignee": case.assignee})
        await session.commit()
    return {"assignee": case.assignee}


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/cases/{case_id}/notes")
async def add_note(case_id: str, body: NoteIn, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        if not await session.get(Case, case_id.upper()):
            raise HTTPException(404, "No such case.")
        note = Note(case_id=case_id.upper(), author=who.email, text=body.text)
        session.add(note)
        await audit.record(session, f"analyst:{who.email}", "case.note", "case", case_id.upper(), {"chars": len(body.text)})
        await session.commit()
    return {"id": note.id}


class RemoveReport(BaseModel):
    report_id: str


@router.post("/cases/{case_id}/remove-report")
async def remove_report(case_id: str, body: RemoveReport, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        case = await session.get(Case, case_id.upper())
        report = await session.get(Report, body.report_id.upper())
        if not case or not report or report.case_id != case.id:
            raise HTTPException(404, "That report is not in this case.")
        left = (await session.execute(select(func.count()).select_from(Report).where(Report.case_id == case.id))).scalar()
        if left <= 1:
            raise HTTPException(409, "This is the case's last report. Reject or close the case instead.")
        await service.remove_report(session, case, report, who.email)
        await session.commit()
    return {"removed": report.id}


@router.post("/cases/{case_id}/summary")
async def regenerate_summary(case_id: str, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    """New cited summary for an approved case (proposed cases get theirs through the review)."""
    deps = request.app.state.deps
    limit(request, "ai", 20)
    async with deps.sessionmaker() as session:
        case = await session.get(Case, case_id.upper())
        if not case:
            raise HTTPException(404, "No such case.")
        facts = await service.case_facts(session, case.id)
        summary = await write_summary(deps.models, deps.settings.llm_timeout_seconds, facts, KIND_TITLES.get(case.kind, "Fraud"))
        case.summary = {**summary, "requested_by": who.email}
        await audit.record(session, "agent:writer", "summary.written", "case", case.id, {
            "model": summary.get("model"), "sentences": len(summary["sentences"]), "dropped": len(summary.get("dropped", [])),
            "requested_by": who.email})
        await session.commit()
    return summary


# --------------------------------------------------------------------------- exports

async def _export_ready(session, settings, case_id: str) -> tuple[Case, dict]:
    case = await session.get(Case, case_id.upper())
    if not case or case.status in ("proposed", "rejected", "merged"):
        raise HTTPException(409, "Only approved cases can be exported.")
    if settings.four_eyes and not case.confirmed_by:
        raise HTTPException(409, "Four-eyes rule: a second person must confirm the case before it is exported.")
    facts = await service.case_facts(session, case.id)
    if not facts["reports"]:
        raise HTTPException(409, "The case has no reports left to export.")
    return case, facts


@router.get("/cases/{case_id}/export/stix")
async def export_stix(case_id: str, request: Request, who: Principal = Depends(require_viewer)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        case, facts = await _export_ready(session, request.app.state.settings, case_id)
        await audit.record(session, f"user:{who.email}", "case.exported", "case", case.id, {"format": "stix"})
        await session.commit()
    return case_bundle([(case, facts)])


@router.get("/cases/{case_id}/export/csv")
async def export_csv(case_id: str, request: Request, who: Principal = Depends(require_viewer)) -> Response:
    async with request.app.state.deps.sessionmaker() as session:
        case, facts = await _export_ready(session, request.app.state.settings, case_id)
        await audit.record(session, f"user:{who.email}", "case.exported", "case", case.id, {"format": "csv"})
        await session.commit()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["kind", "value", "reports", "roles", "found_by", "report_ids"])
    for e in facts["entities"]:
        if not e["official"]:
            w.writerow([e["kind"], e["value"], len(e["reports"]), ";".join(e["roles"]), ";".join(e["sources"]), ";".join(e["reports"])])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{case.id}-identifiers.csv"'})


@router.get("/cases/{case_id}/referral")
async def referral(case_id: str, request: Request, who: Principal = Depends(require_viewer)) -> dict:
    """Everything a referral letter needs: to FIA, the Bureau of Emigration, and each bank or wallet."""
    async with request.app.state.deps.sessionmaker() as session:
        case, facts = await _export_ready(session, request.app.state.settings, case_id)
        await audit.record(session, f"user:{who.email}", "case.referral_prepared", "case", case.id, {})
        await session.commit()
    freeze = [{"kind": m["kind"], "value": next((e["value"] for e in facts["entities"] if e["id"] == m["entity_id"]), m["display"]),
               "victims": m["reports"], "amount": m["total"], "reports": m["report_ids"]} for m in facts["money"]]
    recipients = ["FIA Cybercrime Wing"]
    if case.kind == "overseas_job":
        recipients.append("Bureau of Emigration and Overseas Employment (Protector of Emigrants)")
    if freeze:
        recipients.append("Banks and wallets holding the accounts listed below (freeze request)")
    return {"case": case_json(case), "summary": case.summary, "recipients": recipients, "freeze_requests": freeze,
            "identifiers": [e for e in facts["entities"] if not e["official"]],
            "reports": [report_json(r, full=False) for r in facts["reports"]], "total_loss": facts["total_loss"],
            "first_seen": facts["first_seen"].isoformat(), "last_seen": facts["last_seen"].isoformat(),
            "prepared_by": who.email, "prepared_at": datetime.now(UTC).isoformat(), "tlp": case.tlp}


# --------------------------------------------------------------------------- suggestions

def _suggestion_json(s: Suggestion) -> dict:
    return {"id": s.id, "kind": s.kind, "case_id": s.case_id, "other_case_id": s.other_case_id, "report_ids": s.report_ids,
            "reasons": s.reasons, "score": s.score, "ai_verdict": s.ai_verdict, "ai_reason": s.ai_reason, "ai_model": s.ai_model,
            "status": s.status, "decided_by": s.decided_by, "decided_at": s.decided_at.isoformat() if s.decided_at else None}


@router.get("/suggestions")
async def list_suggestions(request: Request, status: str = "pending", _=Depends(reader)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        rows = (await session.execute(select(Suggestion).where(Suggestion.status == status)
                                      .order_by(Suggestion.score.desc(), Suggestion.id))).scalars().all()
        titles = {c.id: c.title for c in (await session.execute(select(Case))).scalars().all()}
    return {"suggestions": [{**_suggestion_json(s), "case_title": titles.get(s.case_id), "other_case_title": titles.get(s.other_case_id)}
                            for s in rows]}


async def _sides(session, s: Suggestion) -> tuple[list[Report], list[Report]]:
    a = await service.case_members(session, s.case_id) if s.case_id else []
    b = await service.case_members(session, s.other_case_id) if s.other_case_id else []
    loose = list((await session.execute(select(Report).where(Report.id.in_(s.report_ids or [])))).scalars().all())
    if s.kind == "new_case":
        half = max(1, len(loose) // 2)
        return loose[:half], loose[half:]
    return a, (b or loose)


@router.get("/suggestions/{sid}")
async def get_suggestion(sid: int, request: Request, _=Depends(reader)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        s = await session.get(Suggestion, sid)
        if not s:
            raise HTTPException(404, "No such suggestion.")
        a, b = await _sides(session, s)
    return {**_suggestion_json(s), "side_a": [report_json(r, full=False) for r in a], "side_b": [report_json(r, full=False) for r in b]}


@router.post("/suggestions/{sid}/second-opinion")
async def second_opinion(sid: int, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    deps = request.app.state.deps
    limit(request, "ai", 20)
    async with deps.sessionmaker() as session:
        s = await session.get(Suggestion, sid)
        if not s:
            raise HTTPException(404, "No such suggestion.")
        a, b = await _sides(session, s)
        result = await adjudicate(deps.models, deps.settings.llm_timeout_seconds, a, b, s.reasons)
        if result.get("verdict"):
            s.ai_verdict, s.ai_reason, s.ai_model = result["verdict"], result["reason"], result["model"]
            await audit.record(session, "agent:adjudicator", "suggestion.second_opinion", "suggestion", str(s.id),
                               {"verdict": result["verdict"], "model": result["model"], "requested_by": who.email})
            await session.commit()
    return result


class SuggestionDecision(BaseModel):
    accept: bool


@router.post("/suggestions/{sid}/decision")
async def decide(sid: int, body: SuggestionDecision, request: Request, who: Principal = Depends(require_analyst)) -> dict:
    async with request.app.state.deps.sessionmaker() as session:
        s = await session.get(Suggestion, sid)
        if not s or s.status != "pending":
            raise HTTPException(409, "This suggestion was already decided.")
        result = await service.decide_suggestion(session, s, body.accept, who.email)
        await session.commit()
    return {"status": "accepted" if body.accept else "rejected", "case_id": result}
