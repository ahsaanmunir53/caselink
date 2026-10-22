"""AI agents with a scripted model: citations are checked, identifiers never reach the model."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.ai.agents import (
    Redactor,
    adjudicate,
    extract_with_ai,
    translate,
    validate_sentences,
    write_summary,
)
from app.ai.qa import ask
from tests.conftest import login
from tests.fakes import FakeLLM

T = datetime(2026, 9, 1, tzinfo=UTC)


def facts():
    reports = [SimpleNamespace(id="R-0001", text="Gulf Star Manpower took Rs 90,000. JazzCash 0301-2345671. Contact 0333-1112223.",
                               received_at=T, source="pardes_guard", language="en", destination_country="UAE", reporter_city="Lahore"),
               SimpleNamespace(id="R-0002", text="GulfStar Recruiting asked fee on JazzCash 0301-2345671 for a UAE guard job.",
                               received_at=T, source="police_desk", language="en", destination_country="UAE", reporter_city="Sialkot")]
    return {"reports": reports, "first_seen": T, "last_seen": T, "total_loss": 90000, "countries": [("UAE", 2)],
            "cities": [], "key_identifiers": [{"kind": "phone", "value": "+923012345671", "reports": 2, "bridge": False}],
            "money": [{"value": "+923012345671", "display": "0301-***-5671", "reports": 2, "total": 90000, "report_ids": ["R-0001", "R-0002"],
                       "kind": "phone", "entity_id": 1}],
            "entities": [{"id": 1, "kind": "phone", "value": "+923012345671", "display": "0301-***-5671", "official": False,
                          "reports": ["R-0001", "R-0002"]},
                         {"id": 2, "kind": "phone", "value": "+923331112223", "display": "0333-***-2223", "official": False,
                          "reports": ["R-0001"]}]}


def test_redactor_keeps_tokens_stable_and_masks_for_display():
    red = Redactor()
    a = red.redact("Pay 0301-2345671 or +92 301 2345671, IBAN PK36SCBL0000001123456702, mail x@y.com")
    assert a.count("[PHONE_1]") == 2 and "[IBAN_1]" in a and "[EMAIL_1]" in a and "2345671" not in a
    assert red.show("[PHONE_1]") == "0301-***-5671"
    assert red.restore("[PHONE_1]") in ("0301-2345671", "+92 301 2345671")


def test_writer_keeps_only_supported_sentences_and_never_sends_numbers():
    reply = {"sentences": [
        {"text": "Victims paid fees to [PHONE_1] for UAE jobs.", "cites": ["R-0001", "R-0002"]},
        {"text": "The agent also used [PHONE_2].", "cites": ["R-0002"]},  # PHONE_2 is only in R-0001
        {"text": "The gang is run by a politician.", "cites": []},  # no citation
        {"text": "Another report exists.", "cites": ["R-0999"]},  # not in the case
    ], "modus_operandi": "Advance fee for jobs", "next_steps": ["Freeze [PHONE_1]"]}
    llm = FakeLLM(replies={"case summary": reply})
    out = asyncio.run(write_summary([llm], 10, facts(), "Overseas job fraud"))
    assert out["source"] == "ai" and len(out["sentences"]) == 1
    assert out["sentences"][0]["text"] == "Victims paid fees to 0301-***-5671 for UAE jobs."
    assert {d["problem"] for d in out["dropped"]} == {"[PHONE_2] is not in the cited reports", "no citation",
                                                       "cites a report that is not in this case"}
    sent = " ".join(str(m.content) for m in llm.calls[0])
    assert "2345671" not in sent and "1112223" not in sent


def test_writer_falls_back_to_the_template():
    out = asyncio.run(write_summary([FakeLLM(error=RuntimeError("Error code: 429 - rate limit"))], 10, facts(), "Overseas job fraud"))
    assert out["source"] == "template" and all(s["cites"] for s in out["sentences"])
    kept, dropped = validate_sentences(out["sentences"], facts(), Redactor())
    assert len(kept) == len(out["sentences"]) and not dropped


def test_adjudicator_translator_and_extractor():
    f = facts()
    llm = FakeLLM(replies={"same criminal operation": {"verdict": "SAME", "reason": "Both use [PHONE_1] [R-0001]."},
                           "Translate": "Gulf Star took money. Number [PHONE_1].",
                           "list what it says": {"agency_names": ["Gulf Star Manpower"], "people": ["Imran"], "destination_country": "UAE",
                                                 "payment_methods": ["JazzCash"], "modus_operandi": "fee for visa"}})
    verdict = asyncio.run(adjudicate([llm], 10, f["reports"][:1], f["reports"][1:], [{"kind": "name", "detail": "agency:gulfstar"}]))
    assert verdict["verdict"] == "same" and "0301-***-5671" in verdict["reason"]
    text, model = asyncio.run(translate([llm], 10, "Gulf Star ne paise liye. Number 0301-2345671."))
    assert text == "Gulf Star took money. Number 0301-2345671." and model == "fake-model"
    found = asyncio.run(extract_with_ai([llm], 10, "Gulf Star Manpower ka agent Imran"))
    assert found["agency_cores"] == ["gulfstar"] and found["people"] == ["Imran"]


def test_review_graph_uses_the_model_and_waits_for_a_person(client):
    deps = client.app.state.deps
    deps.models = [FakeLLM(replies={"case summary": {"sentences": [], "modus_operandi": "x"}})]  # nothing valid -> template
    cid = client.get("/api/cases", params={"status": "proposed"}).json()["cases"][0]["id"]
    out = client.post(f"/api/cases/{cid}/review", headers=login(client)).json()
    assert out["waiting"] and out["draft"]["source"] == "template" and "every model sentence failed" in out["draft"]["errors"][0]
    again = client.post(f"/api/cases/{cid}/review/decision", json={"decision": "redraft", "note": "shorter"}, headers=login(client)).json()
    assert again["waiting"]  # a fresh draft waits for a decision again


def test_assistant_cites_only_what_its_tools_returned(client):
    deps = client.app.state.deps
    plan = [AIMessage(content="", tool_calls=[{"name": "search", "args": {"query": "Lion City Singapore hotel"}, "id": "t1"}])]
    llm = FakeLLM(tool_plan=plan)
    deps.models = deps.agent_models = [llm]
    first = client.get("/api/reports", params={"q": "Lion City Singapore hotel"}).json()["reports"][0]["id"]
    llm.final_answer = f"Lion City Placements promised hotel jobs in Singapore [{first}]. It also ran a casino [R-9999]."
    out = asyncio.run(ask(deps, "What do we know about Lion City?"))
    assert out["source"] == "ai" and out["grounded"]
    assert out["citations"] == [first] and out["removed_citations"] == ["R-9999"] and "[R-9999]" not in out["answer"]
