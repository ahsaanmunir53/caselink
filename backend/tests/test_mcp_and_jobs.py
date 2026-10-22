"""The MCP server passes CaseLink's data through read-only; the daily digest summarises the queue."""

import json

import httpx
import respx
from mcp import Client

from app.mcp_server import create_server

CASES = {"cases": [{"id": "C-002", "title": "AlNoor Manpower: overseas job fraud, Saudi Arabia", "status": "proposed",
                    "priority": 94, "reports": 21, "loss": 4200000, "kind": "overseas_job"}]}


@respx.mock
async def test_mcp_tools_call_the_api():
    respx.get("http://caselink.test/api/cases").mock(return_value=httpx.Response(200, json=CASES))
    respx.post("http://caselink.test/api/ask").mock(return_value=httpx.Response(200, json={"answer": "x [R-0001]", "citations": ["R-0001"]}))
    respx.get("http://caselink.test/api/cases/C-999").mock(return_value=httpx.Response(404, json={"detail": "No such case."}))
    async with httpx.AsyncClient(base_url="http://caselink.test") as http:
        async with Client(create_server(http)) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert names == {"list_cases", "get_case", "search_reports", "ask"}
            data = json.loads((await client.call_tool("list_cases", {"status": "proposed"})).content[0].text)
            assert data["cases"][0]["id"] == "C-002" and "kind" not in data["cases"][0]
            err = json.loads((await client.call_tool("get_case", {"case_id": "C-999"})).content[0].text)
            assert err["error"].startswith("HTTP 404")


def test_digest_needs_the_secret_and_lists_the_queue(client):
    assert client.post("/api/cron/digest").status_code == 401
    out = client.post("/api/cron/digest", headers={"X-Cron-Secret": "cron-secret-for-tests"}).json()
    assert out["sent"] is False and "Proposed cases waiting for review: " in out["text"]


HOSHIYAR_BUNDLE = {"type": "bundle", "id": "bundle--1", "objects": [
    {"type": "identity", "id": "identity--1", "name": "Hoshiyar"},
    {"type": "campaign", "id": "campaign--1", "name": "Pakistan Post parcel fee"},
    {"type": "indicator", "id": "indicator--1", "name": "pakpost-delivery.top", "description": "Seen in delivery reports",
     "labels": ["delivery"], "valid_from": "2026-10-10T10:00:00.000Z", "pattern": "[domain-name:value = 'pakpost-delivery.top']"},
    {"type": "relationship", "id": "relationship--1", "relationship_type": "indicates", "source_ref": "indicator--1",
     "target_ref": "campaign--1"},
]}


def test_import_from_hoshiyar_links_to_the_parcel_case(settings, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import login

    linked = settings.model_copy(update={"hoshiyar_api_url": "https://hoshiyar.test", "hoshiyar_integration_key": "k",
                                         "sqlite_path": str(tmp_path / "h.db")})
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://hoshiyar.test/api/stix").mock(return_value=httpx.Response(200, json=HOSHIYAR_BUNDLE))
        mock.route(host="testserver").pass_through()
        with TestClient(create_app(linked)) as c:
            assert c.get("/api/health").json()["hoshiyar_link"]
            out = c.post("/api/import/hoshiyar", headers=login(c)).json()
            item = out["outcomes"][0]
            assert item["case_id"]
            case = c.get(f"/api/cases/{item['case_id']}").json()
            assert "parcel" in case["case"]["title"].lower()
            r = c.get(f"/api/reports/{item['report_id']}").json()["report"]
            assert r["source"] == "hoshiyar" and r["kind"] == "parcel"
