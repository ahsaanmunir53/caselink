"""Reports in, cases out: storing reports, running the linker, and keeping cases in step with people's decisions.

Rules for keeping people in charge:

* A case only becomes *open* when an analyst approves it. Until then it is *proposed*.
* Once a case is open (or later), the linker never removes a report from it. New reports that share
  a strong identifier with it are attached, and an alert says so.
* Reports a person placed somewhere (by accepting a suggestion or approving a case) are *pinned*;
  the linker does not move them.
* When a person rejects a case, a suggestion or a report's place in a case, those report pairs are
  remembered and never linked again.
"""

import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import detect_language
from app.db.models import Alert, Case, Entity, Link, Mention, RejectedPair, Report, Suggestion
from app.extract.rules import extract, mask
from app.intel import audit
from app.link.linker import KIND_LABEL, STRONG_KINDS, Rep, key_identifiers, link_all, pair

ACTIVE = ("open", "investigating", "referred", "closed")
KIND_TITLES = {
    "overseas_job": "Overseas job fraud", "bisp": "Fake BISP payment", "parcel": "Fake parcel fee",
    "bank_otp": "Bank impersonation and OTP theft", "task": "Online task and investment scam",
    "family": "Fake family emergency", "prize": "Fake prize or lucky draw", "other": "Fraud",
}


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- ingest

async def _next_report_id(session: AsyncSession) -> int:
    ids = (await session.execute(select(Report.id))).scalars().all()
    nums = [int(i[2:]) for i in ids if re.fullmatch(r"R-\d+", i)]
    return (max(nums) if nums else 0) + 1


async def _entity(session: AsyncSession, cache: dict, kind: str, value: str, official: bool, valid: bool) -> Entity:
    key = (kind, value)
    if key in cache:
        return cache[key]
    ent = (await session.execute(select(Entity).where(Entity.kind == kind, Entity.value == value))).scalar_one_or_none()
    if ent is None:
        ent = Entity(kind=kind, value=value, display=mask(kind, value), official=official, valid=valid)
        session.add(ent)
        await session.flush()
    cache[key] = ent
    return ent


async def store_reports(session: AsyncSession, items: list[dict], actor: str) -> list[str]:
    """Save reports, extract their identifiers with rules, and return the new ids."""
    next_num = await _next_report_id(session)
    cache: dict = {}
    new_ids = []
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        rid = item.get("id") if re.fullmatch(r"R-\d{4,}", str(item.get("id") or "")) else None
        if rid is None or await session.get(Report, rid) is not None:
            rid = f"R-{next_num:04d}"
            next_num += 1
        received = item.get("received_at")
        when = _utc(datetime.fromisoformat(received)) if isinstance(received, str) and received else datetime.now(UTC)
        report = Report(
            id=rid, source=str(item.get("source") or "upload")[:24], channel=str(item.get("channel") or "web_form")[:24],
            received_at=when, language=item.get("language") or detect_language(text),
            reporter_city=item.get("reporter_city"), destination_country=item.get("destination_country"),
            amount_lost=item.get("amount_lost"), currency=item.get("currency") or "PKR",
            kind=item.get("kind") or guess_kind(text), text=text[:6000], synthetic=bool(item.get("synthetic")),
        )
        ex = extract(text)
        if report.amount_lost is None and ex.amount:
            report.amount_lost = ex.amount
        session.add(report)
        await session.flush()
        for found in ex.entities:
            ent = await _entity(session, cache, found.kind, found.value, found.official, found.valid)
            session.add(Mention(report_id=rid, entity_id=ent.id, raw=found.raw[:255], role=found.role, source="rules"))
        new_ids.append(rid)
    if new_ids:
        await audit.record(session, actor, "reports.stored", "report", new_ids[0] if len(new_ids) == 1 else f"{len(new_ids)} reports",
                           {"ids": new_ids[:50], "count": len(new_ids)})
    return new_ids


_KIND_WORDS = [
    ("overseas_job", r"visa|naukri|job in|work permit|overseas|manpower|protector|ویزا|نوکری"),
    ("bisp", r"bisp|benazir|8171|بی آئی ایس پی"),
    ("parcel", r"parcel|courier|pakistan post|tcs|leopards|پارسل"),
    ("bank_otp", r"otp|account (?:will be )?blocked|head office|bank se|بینک"),
    ("task", r"task|telegram|daily profit|earning|investment|usdt|crypto"),
    ("family", r"naya number|new number|ammi|abbu|beta|mushkil|in trouble"),
    ("prize", r"lucky draw|inaam|prize|jeeto|انعام"),
]


def guess_kind(text: str) -> str:
    low = text.lower()
    for kind, pattern in _KIND_WORDS:
        if re.search(pattern, low):
            return kind
    return "other"


# --------------------------------------------------------------------------- loading

async def load_reps(session: AsyncSession) -> dict[str, Rep]:
    reports = (await session.execute(select(Report))).scalars().all()
    reps = {r.id: Rep(r.id, r.kind, _utc(r.received_at), r.text, r.destination_country, r.amount_lost) for r in reports}
    rows = (await session.execute(
        select(Mention.report_id, Mention.raw, Mention.source, Entity.kind, Entity.value, Entity.official)
        .join(Entity, Entity.id == Mention.entity_id))).all()
    for rid, raw, source, kind, value, official in rows:
        if official or rid not in reps:
            continue
        reps[rid].entities.setdefault(kind, set()).add(value)
        if kind == "agency" and source != "name_list":
            reps[rid].agency_raw.setdefault(value, raw)
    return reps


async def rejected_pairs(session: AsyncSession) -> set[tuple[str, str]]:
    return {pair(a, b) for a, b in (await session.execute(select(RejectedPair.report_a, RejectedPair.report_b))).all()}


# --------------------------------------------------------------------------- titles and priority

def case_title(members: list[Rep]) -> tuple[str, str]:
    kinds = Counter(r.kind for r in members)
    kind = kinds.most_common(1)[0][0]
    names = Counter(raw for r in members for raw in r.agency_raw.values())
    dest = Counter(r.destination for r in members if r.destination)
    label = KIND_TITLES.get(kind, "Fraud")
    if names and kind in ("overseas_job", "task", "prize"):
        head = names.most_common(1)[0][0]
        title = f"{head}: {label.lower()}" + (f", {dest.most_common(1)[0][0]}" if dest else "")
    else:
        top = Counter((k, v) for r in members for k in ("domain", "iban", "phone") for v in r.entities.get(k, set()))
        ident = top.most_common(1)[0][0] if top else None
        title = label + (f" via {mask(ident[0], ident[1])}" if ident else "")
    return title[:200], kind


def priority(members: list[Rep], newest: datetime) -> int:
    n = len(members)
    loss = sum(r.amount or 0 for r in members)
    last = max(r.received_at for r in members)
    days = (newest - last).days
    victims = min(45.0, 9 * math.log2(1 + n))
    money = min(30.0, 15 * math.log10(1 + loss / 50_000))
    recency = 25 if days <= 14 else 12 if days <= 45 else 4
    return int(round(victims + money + recency))


# --------------------------------------------------------------------------- rebuild

async def _next_case_id(session: AsyncSession) -> int:
    ids = (await session.execute(select(Case.id))).scalars().all()
    nums = [int(i[2:]) for i in ids if re.fullmatch(r"C-\d+", i)]
    return (max(nums) if nums else 0) + 1


async def rebuild(session: AsyncSession, settings, actor: str = "agent:linker") -> dict:
    """Run the linker over every report and bring cases and suggestions up to date."""
    reps = await load_reps(session)
    if not reps:
        return {"reports": 0}
    rejected = await rejected_pairs(session)
    res = link_all(list(reps.values()), settings.hub_share, settings.hub_min_reports, settings.name_min_length, rejected)
    now = datetime.now(UTC)
    newest = max(r.received_at for r in reps.values())

    # Names found by the name list become mentions too, so the case page can show them.
    if res.name_list:
        cache: dict = {}
        for rid, cores in res.name_list.items():
            for core in cores:
                ent = await _entity(session, cache, "agency", core, False, True)
                exists = (await session.execute(select(Mention.id).where(Mention.report_id == rid, Mention.entity_id == ent.id))).first()
                if not exists:
                    session.add(Mention(report_id=rid, entity_id=ent.id, raw=core, role="agency", source="name_list"))

    await session.execute(delete(Link))
    for e in res.edges:
        session.add(Link(report_a=e.a, report_b=e.b, kind=e.kind, strength=e.strength, detail=e.detail[:255], score=e.score))

    reports = {r.id: r for r in (await session.execute(select(Report))).scalars().all()}
    cases = {c.id: c for c in (await session.execute(select(Case))).scalars().all()}
    members: dict[str, set[str]] = defaultdict(set)
    for r in reports.values():
        if r.case_id:
            members[r.case_id].add(r.id)
    active = {cid for cid, c in cases.items() if c.status in ACTIVE}
    stats = Counter()
    next_case = await _next_case_id(session)
    touched: set[str] = set()

    for comp in res.components:
        if len(comp) < 2:
            continue
        in_active = Counter(reports[r].case_id for r in comp if reports[r].case_id in active)
        free = [r for r in comp if reports[r].case_id not in active and not reports[r].pinned]
        if in_active:
            target = in_active.most_common(1)[0][0]
            for rid in free:
                old = reports[rid].case_id
                reports[rid].case_id = target
                members[target].add(rid)
                if old:
                    members[old].discard(rid)
                session.add(Alert(kind="joined_case", case_id=target, report_id=rid,
                                  message=f"{rid} shares an identifier with {target} and was added to it."))
                await audit.record(session, actor, "case.report_attached", "case", target, {"report": rid, "rule": "shared identifier"})
                stats["attached_to_open_cases"] += 1
            touched.add(target)
            continue
        # Proposed case: keep the id of the proposed case it overlaps most, so ids stay stable.
        overlap = Counter(reports[r].case_id for r in comp if reports[r].case_id and cases[reports[r].case_id].status == "proposed")
        best = None
        for cid, n in overlap.most_common():
            if cid not in touched and n / len(members[cid] | set(comp)) >= 0.34:
                best = cid
                break
        if best is None:
            best = f"C-{next_case:03d}"
            next_case += 1
            cases[best] = Case(id=best, title="", status="proposed", created_at=now, updated_at=now)
            session.add(cases[best])
            await session.flush()
            await audit.record(session, actor, "case.proposed", "case", best, {"reports": sorted(comp)})
            stats["new_proposed_cases"] += 1
        for rid in comp:
            if reports[rid].case_id in active or (reports[rid].pinned and reports[rid].case_id != best):
                continue
            old = reports[rid].case_id
            if old != best:
                reports[rid].case_id = best
                members[best].add(rid)
                if old:
                    members[old].discard(rid)
        touched.add(best)

    # Proposed cases the linker no longer supports lose their unpinned reports; empty ones go.
    for cid, case in cases.items():
        if case.status != "proposed" or cid in touched:
            continue
        for rid in list(members[cid]):
            if not reports[rid].pinned:
                reports[rid].case_id = None
                members[cid].discard(rid)
        if len(members[cid]) < 2:
            for rid in members[cid]:
                reports[rid].case_id = None
                reports[rid].pinned = False
            await session.delete(case)
            stats["proposed_cases_dropped"] += 1
        else:
            touched.add(cid)

    # Titles, kinds and priorities
    for cid in touched:
        case = cases[cid]
        group = [reps[r] for r in members[cid] if r in reps]
        if not group:
            continue
        case.title, case.kind = case_title(group)
        case.priority = priority(group, newest)
        case.updated_at = now

    await session.flush()
    await _sync_suggestions(session, res, reports)
    await audit.record(session, actor, "linker.rebuild", "system", "linker", {
        "reports": len(reps), "strong_links": sum(e.strength == "strong" for e in res.edges),
        "weak_links": sum(e.strength == "weak" for e in res.edges), "common_identifiers": len(res.common),
        **{k: v for k, v in stats.items()}})
    return {"reports": len(reps), "groups": sum(len(c) > 1 for c in res.components), **stats}


async def _sync_suggestions(session: AsyncSession, res, reports: dict[str, Report]) -> None:
    decided = (await session.execute(select(Suggestion).where(Suggestion.status != "pending"))).scalars().all()
    decided_keys = {_key(s.kind, s.case_id, s.other_case_id, s.report_ids) for s in decided}
    old_pending = {_key(s.kind, s.case_id, s.other_case_id, s.report_ids): s for s in
                   (await session.execute(select(Suggestion).where(Suggestion.status == "pending"))).scalars().all()}
    keep: set = set()
    for sug in res.suggestions:
        groups = [sorted(g) for g in sug.groups if g]
        case_ids = sorted({reports[r].case_id for g in groups for r in g if reports[r].case_id})
        loose = sorted(r for g in groups for r in g if not reports[r].case_id)
        if sug.kind == "new_case" or not case_ids:
            kind, case_id, other, rids = "new_case", None, None, sorted(r for g in groups for r in g)
            if len(rids) < 2:
                continue
        elif len(case_ids) >= 2:
            kind, case_id, other, rids = "merge", case_ids[0], case_ids[1], []
        else:
            kind, case_id, other, rids = "attach", case_ids[0], None, loose
            if not rids:
                continue
        key = _key(kind, case_id, other, rids)
        if key in decided_keys or key in keep:
            continue
        keep.add(key)
        if key in old_pending:
            old_pending[key].reasons, old_pending[key].score = sug.reasons, sug.score
            continue
        session.add(Suggestion(kind=kind, case_id=case_id, other_case_id=other, report_ids=rids,
                               reasons=sug.reasons, score=sug.score))
    for key, s in old_pending.items():
        if key not in keep:
            await session.delete(s)


def _key(kind, case_id, other, rids) -> tuple:
    return (kind, case_id or "", other or "", tuple(sorted(rids or [])))


# --------------------------------------------------------------------------- decisions by people

async def _remember_rejected(session: AsyncSession, pairs: set[tuple[str, str]], who: str) -> None:
    existing = await rejected_pairs(session)
    for a, b in pairs - existing:
        session.add(RejectedPair(report_a=a, report_b=b, decided_by=who))


async def case_members(session: AsyncSession, case_id: str) -> list[Report]:
    return list((await session.execute(select(Report).where(Report.case_id == case_id).order_by(Report.received_at))).scalars().all())


async def approve_case(session: AsyncSession, case: Case, who: str) -> None:
    case.status, case.approved_by, case.approved_at, case.updated_at = "open", who, datetime.now(UTC), datetime.now(UTC)
    for r in await case_members(session, case.id):
        r.pinned = True
    await audit.record(session, f"analyst:{who}", "case.approved", "case", case.id, {})


async def reject_case(session: AsyncSession, case: Case, who: str, reason: str = "") -> None:
    rows = await case_members(session, case.id)
    ids = {r.id for r in rows}
    links = (await session.execute(select(Link.report_a, Link.report_b).where(Link.report_a.in_(ids), Link.report_b.in_(ids)))).all()
    await _remember_rejected(session, {pair(a, b) for a, b in links}, who)
    for r in rows:
        r.case_id, r.pinned = None, False
    case.status, case.updated_at = "rejected", datetime.now(UTC)
    await audit.record(session, f"analyst:{who}", "case.rejected", "case", case.id, {"reason": reason[:300], "reports": sorted(ids)})


async def remove_report(session: AsyncSession, case: Case, report: Report, who: str) -> None:
    others = {r.id for r in await case_members(session, case.id)} - {report.id}
    await _remember_rejected(session, {pair(report.id, o) for o in others}, who)
    report.case_id, report.pinned = None, False
    await audit.record(session, f"analyst:{who}", "case.report_removed", "case", case.id, {"report": report.id})


async def decide_suggestion(session: AsyncSession, sug: Suggestion, accept: bool, who: str) -> str | None:
    """Apply or reject a suggestion. Returns the case the reports ended up in, if any."""
    now = datetime.now(UTC)
    sug.status, sug.decided_by, sug.decided_at = ("accepted" if accept else "rejected"), who, now
    result = None
    if not accept:
        groups: list[set[str]] = []
        if sug.case_id:
            groups.append({r.id for r in await case_members(session, sug.case_id)})
        if sug.other_case_id:
            groups.append({r.id for r in await case_members(session, sug.other_case_id)})
        loose = set(sug.report_ids or [])
        pairs = set()
        if sug.kind == "new_case":
            ids = sorted(loose)
            pairs = {pair(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]}
        else:
            if loose:
                groups.append(loose)
            if len(groups) == 2:
                pairs = {pair(a, b) for a in groups[0] for b in groups[1]}
        await _remember_rejected(session, pairs, who)
    elif sug.kind == "attach":
        for rid in sug.report_ids:
            r = await session.get(Report, rid)
            if r:
                r.case_id, r.pinned = sug.case_id, True
        result = sug.case_id
    elif sug.kind == "merge":
        target, other = sug.case_id, await session.get(Case, sug.other_case_id)
        for r in await case_members(session, sug.other_case_id):
            r.case_id, r.pinned = target, True
        if other:
            other.status, other.merged_into = "merged", target
        result = target
    else:  # new_case
        cid = f"C-{await _next_case_id(session):03d}"
        session.add(Case(id=cid, title="", status="proposed", created_at=now, updated_at=now))
        await session.flush()
        for rid in sug.report_ids:
            r = await session.get(Report, rid)
            if r:
                r.case_id, r.pinned = cid, True
        result = cid
    await audit.record(session, f"analyst:{who}", f"suggestion.{sug.status}", "suggestion", str(sug.id),
                       {"kind": sug.kind, "case": sug.case_id, "other_case": sug.other_case_id, "reports": sug.report_ids,
                        "result": result})
    if result:
        reps = await load_reps(session)
        group = [reps[r.id] for r in await case_members(session, result) if r.id in reps]
        case = await session.get(Case, result)
        if case and group:
            case.title, case.kind = case_title(group)
            case.priority = priority(group, max(r.received_at for r in reps.values()))
            case.updated_at = now
    return result


# --------------------------------------------------------------------------- case facts

async def case_facts(session: AsyncSession, case_id: str) -> dict:
    """Everything the case page and the writer need: members, identifiers, money, timeline, network."""
    rows = await case_members(session, case_id)
    ids = {r.id for r in rows}
    reps = await load_reps(session)
    res_common = set()
    mentions = (await session.execute(
        select(Mention.report_id, Mention.role, Mention.source, Mention.raw, Entity.id, Entity.kind, Entity.value,
               Entity.display, Entity.official, Entity.watched, Entity.valid)
        .join(Entity, Entity.id == Mention.entity_id).where(Mention.report_id.in_(ids)))).all()
    entities: dict[int, dict] = {}
    spans: dict[str, list[dict]] = {}
    for rid, role, source, raw, eid, kind, value, display, official, watched, valid in mentions:
        if raw:
            spans.setdefault(rid, []).append({"raw": raw, "kind": kind, "entity_id": eid, "role": role, "official": official})
        e = entities.setdefault(eid, {"id": eid, "kind": kind, "value": value, "display": display, "official": official,
                                      "watched": watched, "valid": valid, "reports": set(), "roles": set(), "sources": set()})
        e["reports"].add(rid)
        e["roles"].add(role)
        e["sources"].add(source)
    by_id = {r.id: r for r in rows}
    money = []
    for e in entities.values():
        if e["kind"] in ("phone", "iban") and ({"wallet", "payee"} & e["roles"]) and not e["official"]:
            victims = sorted(e["reports"])
            money.append({"entity_id": e["id"], "kind": e["kind"], "display": e["display"], "value": e["value"],
                          "reports": len(victims), "total": sum(by_id[r].amount_lost or 0 for r in victims), "report_ids": victims})
    money.sort(key=lambda m: (-m["total"], -m["reports"]))
    links = (await session.execute(select(Link).where(Link.report_a.in_(ids), Link.report_b.in_(ids)))).scalars().all()
    keys = key_identifiers(ids, reps, res_common) if ids else []
    total = sum(r.amount_lost or 0 for r in rows)
    return {
        "reports": rows,
        "entities": sorted(({**e, "reports": sorted(e["reports"]), "roles": sorted(e["roles"]), "sources": sorted(e["sources"])}
                            for e in entities.values()), key=lambda e: (e["official"], -len(e["reports"]), e["kind"])),
        "money": money,
        "links": links,
        "mentions": spans,
        "key_identifiers": keys,
        "total_loss": total,
        "first_seen": rows[0].received_at if rows else None,
        "last_seen": rows[-1].received_at if rows else None,
        "cities": Counter(r.reporter_city for r in rows if r.reporter_city).most_common(),
        "countries": Counter(r.destination_country for r in rows if r.destination_country).most_common(),
        "sources": Counter(r.source for r in rows).most_common(),
        "languages": Counter(r.language for r in rows).most_common(),
    }


async def emerging(session: AsyncSession, days: int = 14) -> list[dict]:
    """Cases with several reports in the last two weeks of data, growing faster than before."""
    newest = (await session.execute(select(func.max(Report.received_at)))).scalar_one_or_none()
    if not newest:
        return []
    newest = _utc(newest)
    cut = newest - timedelta(days=days)
    rows = (await session.execute(select(Report.case_id, Report.received_at).where(Report.case_id.is_not(None)))).all()
    recent, before = Counter(), Counter()
    for cid, when in rows:
        (recent if _utc(when) >= cut else before)[cid] += 1
    out = []
    for cid, n in recent.items():
        rate_before = before[cid] / max(1, 90 / days)
        if n >= 3 and n > 1.5 * rate_before:
            out.append({"case_id": cid, "recent": n, "earlier": before[cid], "days": days})
    return sorted(out, key=lambda x: -x["recent"])


def label(kind: str) -> str:
    return KIND_LABEL.get(kind, kind)


__all__ = ["store_reports", "rebuild", "approve_case", "reject_case", "remove_report", "decide_suggestion",
           "case_facts", "emerging", "case_members", "STRONG_KINDS", "label"]
