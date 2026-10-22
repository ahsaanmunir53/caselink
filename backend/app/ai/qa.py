"""Ask the cases: a tool-using agent that answers analysts' questions with citations.

The model can only see what its tools return (search reports, open a case, list cases, look up an
identifier). Its answer must cite report ids [R-0001] or case ids [C-001]; any citation the tools
never returned is removed and the answer is marked. Without a model, the search results are listed.
"""

import asyncio
import json
import re
import uuid

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from app.ai.agents import UNTRUSTED, Redactor, _name
from app.ai.llm import text_of
from app.ai.model_status import note_failure, note_success, usable
from app.intel.search import list_cases, search_reports

SYSTEM = f"""You are CaseLink's assistant for fraud analysts. Answer the question using only what your tools return.
Use the tools first: search_reports for wording or identifiers, list_cases to find cases by type, country or status,
get_case for a case's details. Cite every fact with the report or case id in square brackets, like [R-0012] or
[C-004]. If the tools do not answer the question, say so. Keep answers under 150 words. Identifiers appear as
tokens such as [PHONE_1]; keep them as they are.
{UNTRUSTED}"""


@tool
def search(query: str) -> str:
    """Search the reports by wording or by an identifier (phone number, IBAN, website, licence number)."""
    return ""


@tool
def cases(kind: str = "", country: str = "", status: str = "") -> str:
    """List cases by priority. kind: overseas_job, bisp, parcel, bank_otp, task, family, prize. country: e.g. Saudi Arabia.
    status: proposed, open, investigating, referred, closed."""
    return ""


@tool
def get_case(case_id: str) -> str:
    """Details of one case: title, status, reports, summary."""
    return ""


TOOLS = [search, cases, get_case]
_CITE = re.compile(r"\[((?:R-\d{4,})|(?:C-\d{3,}))\]")


async def ask(deps, question: str) -> dict:
    question = (question or "").strip()[:600]
    red = Redactor()
    seen: set[str] = set()
    trace: list[dict] = []

    async def run_tool(name: str, args: dict) -> dict:
        async with deps.sessionmaker() as session:
            if name == "search":
                rows = await search_reports(session, str(args.get("query") or question), 8)
                for r in rows:
                    seen.add(r["id"])
                    if r["case_id"]:
                        seen.add(r["case_id"])
                    r["text"] = red.redact(r["text"])
                return {"reports": rows}
            if name == "cases":
                rows = await list_cases(session, args.get("kind") or None, args.get("country") or None, args.get("status") or None)
                seen.update(r["id"] for r in rows)
                return {"cases": rows}
            if name == "get_case":
                from sqlalchemy import select

                from app.db.models import Case, Report

                cid = str(args.get("case_id") or "").strip().upper()
                case = await session.get(Case, cid)
                if not case:
                    return {"error": f"No case {cid}."}
                members = (await session.execute(select(Report).where(Report.case_id == cid))).scalars().all()
                seen.add(cid)
                seen.update(r.id for r in members)
                summary = [s["text"] for s in (case.summary or {}).get("sentences", [])]
                return {"id": cid, "title": case.title, "status": case.status, "priority": case.priority,
                        "reports": [{"id": r.id, "date": f"{r.received_at:%Y-%m-%d}", "text": red.redact(r.text)[:300]}
                                    for r in members[:12]], "report_count": len(members),
                        "loss": sum(r.amount_lost or 0 for r in members), "summary": summary}
        return {"error": f"Unknown tool {name}."}

    models = usable(deps.agent_models or deps.models)
    if not models:
        return await _fallback(deps, question)
    messages = [SystemMessage(SYSTEM), HumanMessage(question)]
    answer, used = None, None
    for _ in range(deps.settings.agent_max_tool_rounds):
        reply = None
        for model in usable(deps.agent_models or deps.models):
            try:
                reply = await asyncio.wait_for(model.bind_tools(TOOLS).ainvoke(messages), deps.settings.llm_timeout_seconds)
                note_success(model)
                used = _name(model)
                break
            except Exception as exc:
                note_failure(model, exc)
        if reply is None:
            break
        messages.append(reply)
        calls = list(getattr(reply, "tool_calls", None) or [])[:3]
        if not calls:
            answer = text_of(reply).strip()
            break
        for call in calls:
            result = await run_tool(call.get("name", ""), call.get("args") or {})
            trace.append({"tool": call.get("name"), "args": call.get("args") or {}})
            messages.append(ToolMessage(content=json.dumps(result, default=str)[:7000],
                                        tool_call_id=call.get("id") or str(uuid.uuid4()), name=call.get("name")))
    if not answer:
        out = await _fallback(deps, question)
        out["note"] = "The AI assistant did not finish; these are the matching reports."
        return out
    cited = set(_CITE.findall(answer))
    unknown = sorted(cited - seen)
    for bad in unknown:
        answer = answer.replace(f"[{bad}]", "")
    return {"answer": red.show(answer)[:2000], "citations": sorted(cited - set(unknown)), "removed_citations": unknown,
            "grounded": bool(cited - set(unknown)), "tools": trace, "model": used, "source": "ai"}


async def _fallback(deps, question: str) -> dict:
    async with deps.sessionmaker() as session:
        rows = await search_reports(session, question, 6)
    if not rows:
        return {"answer": "No reports match that question.", "citations": [], "grounded": False, "tools": [], "source": "search"}
    lines = [f"[{r['id']}] {r['date']} {r['kind'].replace('_', ' ')}" + (f", case [{r['case_id']}]" if r["case_id"] else "")
             for r in rows]
    return {"answer": "Reports that match your question:\n" + "\n".join(lines),
            "citations": [r["id"] for r in rows], "grounded": True, "tools": [{"tool": "search", "args": {"query": question}}],
            "source": "search"}
