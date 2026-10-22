"""Search reports: by identifier when the query contains one, otherwise by wording.

Wording search uses the local embedder plus plain keyword hits, so it works without any API key.
"""

import re

import numpy as np
from sqlalchemy import select

from app.core.embed import embed
from app.db.models import Case, Entity, Mention, Report
from app.extract.rules import extract

_STOP = {"the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "which", "what", "who", "how", "many", "is", "are",
         "was", "were", "with", "by", "from", "cases", "case", "reports", "report", "any", "all", "show", "me", "list"}


async def search_reports(session, query: str, limit: int = 8) -> list[dict]:
    query = (query or "").strip()[:500]
    if not query:
        return []
    hits: dict[str, float] = {}
    found = [e for e in extract(query).entities if e.kind != "agency"]
    if found:
        rows = (await session.execute(
            select(Mention.report_id).join(Entity, Entity.id == Mention.entity_id)
            .where(Entity.kind.in_({f.kind for f in found}), Entity.value.in_({f.value for f in found})))).scalars().all()
        for rid in rows:
            hits[rid] = hits.get(rid, 0) + 2.0
    reports = (await session.execute(select(Report))).scalars().all()
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _STOP and len(w) > 2]
    qv = embed(query)
    for r in reports:
        hay = f"{r.text} {r.translation or ''} {r.destination_country or ''} {r.reporter_city or ''} {r.kind}".lower()
        keyword = sum(1 for w in words if w in hay)
        score = float(np.dot(qv, embed(r.text))) + 0.15 * keyword
        if keyword or r.id in hits:
            hits[r.id] = hits.get(r.id, 0) + score
    best = sorted(hits.items(), key=lambda kv: -kv[1])[:limit]
    by_id = {r.id: r for r in reports}
    return [summary_row(by_id[rid], score) for rid, score in best if rid in by_id]


def summary_row(r: Report, score: float | None = None) -> dict:
    row = {"id": r.id, "case_id": r.case_id, "kind": r.kind, "date": f"{r.received_at:%Y-%m-%d}", "source": r.source,
           "city": r.reporter_city, "destination": r.destination_country, "amount": r.amount_lost, "language": r.language,
           "text": r.text[:400]}
    if score is not None:
        row["score"] = round(score, 3)
    return row


async def list_cases(session, kind: str | None = None, country: str | None = None, status: str | None = None,
                     limit: int = 10) -> list[dict]:
    q = select(Case).where(Case.status.notin_(("merged",)))
    if status:
        q = q.where(Case.status == status)
    if kind:
        q = q.where(Case.kind == kind)
    cases = (await session.execute(q.order_by(Case.priority.desc()))).scalars().all()
    out = []
    for c in cases:
        members = (await session.execute(select(Report).where(Report.case_id == c.id))).scalars().all()
        if country and not any((r.destination_country or "").lower() == country.lower() for r in members):
            continue
        out.append({"id": c.id, "title": c.title, "status": c.status, "kind": c.kind, "priority": c.priority,
                    "reports": len(members), "loss": sum(r.amount_lost or 0 for r in members)})
        if len(out) >= limit:
            break
    return out
