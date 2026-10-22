"""The analyst workflow end to end, with no AI key (template summaries)."""

import stix2

from tests.conftest import login

AYESHA, BILAL, SANA, GUEST = ("ayesha.analyst@caselink.demo", "bilal.analyst@caselink.demo",
                              "sana.supervisor@caselink.demo", "viewer@caselink.demo")


def top_case(client):
    return client.get("/api/cases", params={"status": "proposed"}).json()["cases"][0]


def test_health_overview_and_public_reading(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["demo_mode"] and h["llm"] is False
    o = client.get("/api/overview").json()
    assert o["reports"] == 275 and o["synthetic"] and o["cases"] >= 15 and o["pending_suggestions"] > 20
    assert o["top_money"] and o["top_money"][0]["reports"] >= 3
    cases = client.get("/api/cases").json()["cases"]
    assert all(c["status"] == "proposed" for c in cases)


def test_case_detail_graph_and_money(client):
    case = top_case(client)
    d = client.get(f"/api/cases/{case['id']}").json()
    assert d["case"]["reports"] == len(d["reports"]) >= 10
    assert d["money"] and d["key_identifiers"] and d["timeline"]
    # Every mention's raw text is in its report, so the page can highlight it.
    texts = {r["id"]: r["text"].lower() for r in d["reports"]}
    spans = [(rid, m) for rid, ms in d["mentions"].items() for m in ms]
    assert spans and all(rid in texts for rid, _ in spans)
    found = [m["raw"].lower().removeprefix("http://").removeprefix("https://") in texts[rid] for rid, m in spans]
    assert sum(found) / len(found) > 0.9
    g = client.get(f"/api/cases/{case['id']}/graph").json()
    assert {n["type"] for n in g["nodes"]} == {"report", "entity"} and g["edges"]


def test_acting_needs_a_login_and_the_right_role(client):
    case = top_case(client)
    assert client.post(f"/api/cases/{case['id']}/review").status_code == 401
    assert client.post(f"/api/cases/{case['id']}/review", headers=login(client, GUEST)).status_code == 403


def test_review_with_human_approval_then_four_eyes_then_export(client):
    case = top_case(client)
    cid = case["id"]
    a = login(client, AYESHA)
    started = client.post(f"/api/cases/{cid}/review", headers=a).json()
    assert started["waiting"] and started["draft"]["sentences"]
    for s in started["draft"]["sentences"]:
        assert s["cites"]  # every sentence cites reports
    # Nothing changed yet: the graph is paused at the human step.
    assert client.get(f"/api/cases/{cid}").json()["case"]["status"] == "proposed"
    done = client.post(f"/api/cases/{cid}/review/decision", json={"decision": "approve"}, headers=a).json()
    assert done["outcome"] == "approved"
    detail = client.get(f"/api/cases/{cid}").json()
    assert detail["case"]["status"] == "open" and detail["case"]["approved_by"] == AYESHA and detail["summary"]["sentences"]
    # Export and referral need a second person
    assert client.get(f"/api/cases/{cid}/export/stix", headers=a).status_code == 409
    assert client.post(f"/api/cases/{cid}/confirm", headers=a).status_code == 409  # not the approver
    assert client.post(f"/api/cases/{cid}/status", json={"status": "investigating"}, headers=a).status_code == 200
    assert client.post(f"/api/cases/{cid}/status", json={"status": "referred"}, headers=a).status_code == 409
    b = login(client, BILAL)
    assert client.post(f"/api/cases/{cid}/confirm", headers=b).json()["confirmed_by"] == BILAL
    assert client.post(f"/api/cases/{cid}/status", json={"status": "referred", "note": "Sent to FIA"}, headers=b).status_code == 200
    bundle = client.get(f"/api/cases/{cid}/export/stix", headers=b).json()
    stix2.parse(bundle, allow_custom=False)
    assert any(o["type"] == "grouping" for o in bundle["objects"])
    ref = client.get(f"/api/cases/{cid}/referral", headers=b).json()
    assert ref["freeze_requests"] and "FIA Cybercrime Wing" in ref["recipients"]
    csv = client.get(f"/api/cases/{cid}/export/csv", headers=b)
    assert csv.status_code == 200 and csv.text.startswith("kind,value")
    assert client.get("/api/audit/verify").json()["ok"]


def test_rejecting_a_case_is_remembered(client):
    cases = client.get("/api/cases", params={"status": "proposed"}).json()["cases"]
    small = cases[-1]
    a = login(client, AYESHA)
    client.post(f"/api/cases/{small['id']}/review", headers=a)
    out = client.post(f"/api/cases/{small['id']}/review/decision", json={"decision": "reject", "note": "different gangs"}, headers=a).json()
    assert out["outcome"] == "rejected"
    # Running the linker again does not bring it back.
    client.post("/api/cron/rebuild", headers={"X-Cron-Secret": "cron-secret-for-tests"})
    members = {r["id"] for r in client.get("/api/reports", params={"case": small["id"]}).json()["reports"]}
    assert not members


def test_suggestions_accept_and_reject(client):
    sugs = client.get("/api/suggestions").json()["suggestions"]
    attach = next(s for s in sugs if s["kind"] == "attach")
    common = next(s for s in sugs if s["kind"] == "new_case" and s["score"] < 0.5)
    a = login(client, AYESHA)
    detail = client.get(f"/api/suggestions/{attach['id']}").json()
    assert detail["side_a"] and detail["side_b"]
    opinion = client.post(f"/api/suggestions/{attach['id']}/second-opinion", headers=a).json()
    assert opinion["verdict"] is None  # no model configured
    assert client.post(f"/api/suggestions/{attach['id']}/decision", json={"accept": True}, headers=a).json()["case_id"] == attach["case_id"]
    for rid in attach["report_ids"]:
        r = client.get(f"/api/reports/{rid}").json()["report"]
        assert r["case_id"] == attach["case_id"] and r["pinned"]
    assert client.post(f"/api/suggestions/{common['id']}/decision", json={"accept": False}, headers=a).json()["status"] == "rejected"
    client.post("/api/cron/rebuild", headers={"X-Cron-Secret": "cron-secret-for-tests"})
    pending = client.get("/api/suggestions").json()["suggestions"]
    assert not any(s["report_ids"] == common["report_ids"] and s["kind"] == "new_case" for s in pending)
    assert client.post(f"/api/suggestions/{attach['id']}/decision", json={"accept": True}, headers=a).status_code == 409


def test_new_report_joins_an_open_case_and_triggers_the_watchlist(client):
    a = login(client, AYESHA)
    case = top_case(client)
    client.post(f"/api/cases/{case['id']}/review", headers=a)
    client.post(f"/api/cases/{case['id']}/review/decision", json={"decision": "approve"}, headers=a)
    detail = client.get(f"/api/cases/{case['id']}").json()
    key = next(e for e in detail["entities"] if e["kind"] == "phone" and len(e["reports"]) > 2 and not e["official"])
    assert client.post(f"/api/entities/{key['id']}/watch", json={"watched": True, "note": "main number"}, headers=a).status_code == 200
    number = "0" + key["value"][3:]
    out = client.post("/api/reports", json={"reports": [{"text": f"Walk-in complaint: a man on {number} took Rs 90,000 for a visa and switched off his phone."}]},
                      headers=a).json()
    item = out["outcomes"][0]
    assert item["case_id"] == case["id"] and item["case_status"] == "open"
    assert item["watchlist"]
    alerts = client.get("/api/alerts").json()["alerts"]
    assert {"joined_case", "watchlist"} <= {x["kind"] for x in alerts}


def test_search_entities_and_ask_without_ai(client):
    hits = client.get("/api/reports", params={"q": "Saudi driver visa"}).json()
    assert hits["total"] > 0
    ents = client.get("/api/entities", params={"kind": "iban"}).json()["entities"]
    assert ents and ents[0]["reports"] >= 2
    e = client.get(f"/api/entities/{ents[0]['id']}").json()
    assert e["reports"] and e["total"] > 0
    ans = client.post("/api/ask", json={"question": "Which reports mention Lion City Placements in Singapore?"}).json()
    assert ans["source"] == "search" and ans["citations"]


def test_audit_chain_detects_tampering(client):
    import asyncio

    from sqlalchemy import select

    from app.db.models import AuditEntry

    assert client.get("/api/audit/verify").json()["ok"]
    deps = client.app.state.deps

    async def tamper():
        async with deps.sessionmaker() as session:
            row = (await session.execute(select(AuditEntry).order_by(AuditEntry.id).limit(1))).scalar_one()
            row.details = {**row.details, "count": 1}
            await session.commit()

    asyncio.run(tamper())
    v = client.get("/api/audit/verify").json()
    assert not v["ok"] and v["broken_at"] == 1


def test_quality_endpoint_and_demo_reset(client):
    q = client.get("/api/quality").json()
    assert q["available"] and q["rules_only"]["precision"] == 1.0 and q["current_cases"]["precision"] == 1.0
    assert client.post("/api/cron/reset-demo").status_code == 401
    out = client.post("/api/cron/reset-demo", headers={"X-Cron-Secret": "cron-secret-for-tests"}).json()
    assert out["reports"] == 275


def test_upload_reports_csv(client):
    a = login(client, AYESHA)
    csv = "text,reporter_city\nSomeone on 0345-7788990 took Rs 50000 for Dubai visa,Lahore\nSame man 0345-7788990 asked for more,Lahore\n"
    out = client.post("/api/reports/upload", files={"file": ("r.csv", csv, "text/csv")}, headers=a).json()
    assert len(out["new_ids"]) == 2
    assert out["outcomes"][0]["case_id"] and out["outcomes"][0]["case_id"] == out["outcomes"][1]["case_id"]


def test_the_last_report_cannot_be_taken_out(client):
    case = client.get("/api/cases").json()["cases"][-1]
    h = login(client, AYESHA)
    ids = [r["id"] for r in client.get(f"/api/cases/{case['id']}").json()["reports"]]
    for rid in ids[:-1]:
        assert client.post(f"/api/cases/{case['id']}/remove-report", json={"report_id": rid}, headers=h).status_code == 200
    r = client.post(f"/api/cases/{case['id']}/remove-report", json={"report_id": ids[-1]}, headers=h)
    assert r.status_code == 409 and "last report" in r.json()["detail"]
    assert client.get(f"/api/cases/{case['id']}").json()["case"]["reports"] == 1
