"""LangGraph workflows.

Review (human in the loop): draft -> wait for a person (interrupt) -> apply the decision.
The graph pauses at `review` and its state is saved by the checkpointer (Postgres in production),
so a draft can wait for hours, survive a restart, and be resumed by whoever opens the case next.
An analyst can approve, reject, or ask for a new draft with a note.

Ingest: store and extract -> AI extraction (optional) -> link -> tell the analyst what happened
(joined a case, new proposed case, waiting suggestion, watchlist hit, possible duplicate).
"""

import logging
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select

from app.ai.agents import extract_with_ai, write_summary
from app.core.embed import embed
from app.db.models import Alert, Case, Entity, Mention, Report
from app.extract.rules import agency_core
from app.intel import audit
from app.link import service
from app.link.service import KIND_TITLES

log = logging.getLogger(__name__)


@dataclass
class Deps:
    settings: Any
    sessionmaker: Any
    models: list = field(default_factory=list)
    agent_models: list = field(default_factory=list)
    checkpointer: Any = None
    http: Any = None
    review_graph: Any = None
    ingest_graph: Any = None


# --------------------------------------------------------------------------- review

class ReviewState(TypedDict, total=False):
    case_id: str
    note: str
    draft: dict
    decision: dict
    outcome: str


def build_review_graph(deps: Deps, checkpointer):
    async def draft(state: ReviewState) -> dict:
        async with deps.sessionmaker() as session:
            case = await session.get(Case, state["case_id"])
            facts = await service.case_facts(session, state["case_id"])
            if not case or not facts["reports"]:
                return {"draft": {"sentences": [], "error": "The case has no reports."}}
            label = KIND_TITLES.get(case.kind, "Fraud")
            summary = await write_summary(deps.models, deps.settings.llm_timeout_seconds, facts, label)
            await audit.record(session, "agent:writer", "summary.drafted", "case", case.id, {
                "model": summary.get("model"), "source": summary.get("source"), "sentences": len(summary["sentences"]),
                "dropped_by_citation_check": len(summary.get("dropped", [])),
                "cited_reports": sorted({c for s in summary["sentences"] for c in s["cites"]}),
                "note": state.get("note") or None})
            await session.commit()
        return {"draft": summary}

    async def review(state: ReviewState) -> dict:
        decision = interrupt({"case_id": state["case_id"], "draft": state.get("draft")})
        return {"decision": decision if isinstance(decision, dict) else {"decision": str(decision)}}

    def after_review(state: ReviewState) -> str:
        return "draft" if (state.get("decision") or {}).get("decision") == "redraft" else "finalize"

    async def finalize(state: ReviewState) -> dict:
        d = state.get("decision") or {}
        who = d.get("by") or "unknown"
        async with deps.sessionmaker() as session:
            case = await session.get(Case, state["case_id"])
            if case is None:
                return {"outcome": "missing"}
            if d.get("decision") == "approve":
                case.summary = {**(state.get("draft") or {}), "approved_by": who}
                await service.approve_case(session, case, who)
                outcome = "approved"
            elif d.get("decision") == "reject":
                await service.reject_case(session, case, who, d.get("note") or "")
                outcome = "rejected"
            else:
                outcome = "unchanged"
            await session.commit()
        return {"outcome": outcome}

    g = StateGraph(ReviewState)
    g.add_node("draft", draft)
    g.add_node("review", review)
    g.add_node("finalize", finalize)
    g.add_edge(START, "draft")
    g.add_edge("draft", "review")
    g.add_conditional_edges("review", after_review, {"draft": "draft", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


def review_config(case_id: str, round_: int = 0) -> dict:
    return {"configurable": {"thread_id": f"review-{case_id}-{round_}"}}


async def review_status(graph, case_id: str, round_: int = 0) -> dict:
    snap = await graph.aget_state(review_config(case_id, round_))
    waiting = bool(snap.next) and "review" in snap.next
    payload = None
    for task in snap.tasks or []:
        for intr in getattr(task, "interrupts", ()) or ():
            payload = intr.value
    values = snap.values or {}
    return {"waiting": waiting, "draft": (payload or {}).get("draft") or values.get("draft"),
            "outcome": values.get("outcome"), "started": bool(values)}


async def start_review(graph, case_id: str, round_: int = 0, note: str = "") -> dict:
    await graph.ainvoke({"case_id": case_id, "note": note}, review_config(case_id, round_))
    return await review_status(graph, case_id, round_)


async def resume_review(graph, case_id: str, decision: dict, round_: int = 0) -> dict:
    await graph.ainvoke(Command(resume=decision), review_config(case_id, round_))
    return await review_status(graph, case_id, round_)


# --------------------------------------------------------------------------- ingest

class IngestState(TypedDict, total=False):
    items: list
    actor: str
    use_ai: bool
    new_ids: list
    ai_found: dict
    rebuild: dict
    outcomes: list


def build_ingest_graph(deps: Deps, checkpointer):
    async def store(state: IngestState) -> dict:
        async with deps.sessionmaker() as session:
            ids = await service.store_reports(session, state.get("items") or [], state.get("actor") or "system")
            await session.commit()
        return {"new_ids": ids}

    async def ai_extract(state: IngestState) -> dict:
        found: dict = {}
        if not state.get("use_ai") or not deps.models:
            return {"ai_found": found}
        async with deps.sessionmaker() as session:
            for rid in (state.get("new_ids") or [])[:10]:
                report = await session.get(Report, rid)
                data = await extract_with_ai(deps.models, deps.settings.llm_timeout_seconds, report.text)
                if not data:
                    continue
                report.ai_extraction = data
                if data.get("destination_country") and not report.destination_country:
                    report.destination_country = data["destination_country"]
                for name, core in zip(data["agency_names"], data["agency_cores"], strict=False):
                    ent = (await session.execute(select(Entity).where(Entity.kind == "agency", Entity.value == core))).scalar_one_or_none()
                    if ent is None:
                        ent = Entity(kind="agency", value=core, display=core)
                        session.add(ent)
                        await session.flush()
                    exists = (await session.execute(select(Mention.id).where(Mention.report_id == rid, Mention.entity_id == ent.id))).first()
                    if not exists:
                        session.add(Mention(report_id=rid, entity_id=ent.id, raw=name[:255], role="agency", source="ai"))
                found[rid] = data
                await audit.record(session, "agent:extractor", "report.ai_extracted", "report", rid,
                                   {"model": data.get("model"), "agency_names": data["agency_names"], "people": data["people"]})
            await session.commit()
        return {"ai_found": found}

    async def link(state: IngestState) -> dict:
        async with deps.sessionmaker() as session:
            out = await service.rebuild(session, deps.settings)
            await session.commit()
        return {"rebuild": out}

    async def outcomes(state: IngestState) -> dict:
        results = []
        new = state.get("new_ids") or []
        async with deps.sessionmaker() as session:
            from app.db.models import Suggestion

            pending = (await session.execute(select(Suggestion).where(Suggestion.status == "pending"))).scalars().all()
            others = (await session.execute(select(Report).where(Report.id.notin_(new)))).scalars().all() if new else []
            other_vecs = [(r, embed(r.text)) for r in others]
            for rid in new:
                report = await session.get(Report, rid)
                item = {"report_id": rid, "case_id": report.case_id, "case_status": None, "suggestions": [], "watchlist": [],
                        "duplicate_of": None}
                if report.case_id:
                    case = await session.get(Case, report.case_id)
                    item["case_status"] = case.status if case else None
                item["suggestions"] = [s.id for s in pending if rid in (s.report_ids or [])]
                watched = (await session.execute(
                    select(Entity).join(Mention, Mention.entity_id == Entity.id)
                    .where(Mention.report_id == rid, Entity.watched.is_(True)))).scalars().all()
                for ent in watched:
                    item["watchlist"].append(ent.display)
                    session.add(Alert(kind="watchlist", report_id=rid, case_id=report.case_id,
                                      message=f"Watched {ent.kind} {ent.display} appears in new report {rid}."))
                vec = embed(report.text)
                best = max(((float(vec @ v), r) for r, v in other_vecs), default=(0.0, None), key=lambda x: x[0])
                if best[1] is not None and best[0] >= 0.92:
                    report.duplicate_of = best[1].id
                    item["duplicate_of"] = best[1].id
                    session.add(Alert(kind="duplicate", report_id=rid, case_id=report.case_id,
                                      message=f"{rid} reads almost the same as {best[1].id}; it may be the same complaint twice."))
                results.append(item)
            await session.commit()
        return {"outcomes": results}

    g = StateGraph(IngestState)
    for name, fn in (("store", store), ("ai_extract", ai_extract), ("link", link), ("outcomes", outcomes)):
        g.add_node(name, fn)
    g.add_edge(START, "store")
    g.add_edge("store", "ai_extract")
    g.add_edge("ai_extract", "link")
    g.add_edge("link", "outcomes")
    g.add_edge("outcomes", END)
    return g.compile(checkpointer=checkpointer)


def name_core(name: str) -> str:
    return agency_core(name)
