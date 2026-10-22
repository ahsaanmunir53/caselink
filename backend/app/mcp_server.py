"""MCP server: lets an AI assistant (Claude Desktop, Cursor, any MCP client) query CaseLink.

It runs on your computer over stdio and calls the CaseLink API, so no keys are shared with the
assistant. Read-only: assistants can list cases, open one, search reports and ask questions, but
every decision stays with analysts in the CaseLink app.

    CASELINK_API_URL=https://your-api.onrender.com python app/mcp_server.py

Claude Desktop config (claude_desktop_config.json):

    {"mcpServers": {"caselink": {
        "command": "C:\\path\\to\\backend\\.venv\\Scripts\\python.exe",
        "args": ["C:\\path\\to\\backend\\app\\mcp_server.py"],
        "env": {"CASELINK_API_URL": "https://your-api.onrender.com"}}}}
"""

import os

import httpx
from mcp.server.mcpserver import MCPServer

INSTRUCTIONS = ("CaseLink links fraud reports into cases for analysts. The demo data is synthetic. Report case "
                "statuses as given: 'proposed' cases are not confirmed. Cite report ids (R-0001) and case ids (C-001).")


def create_server(client: httpx.AsyncClient | None = None) -> MCPServer:
    base = os.environ.get("CASELINK_API_URL", "http://localhost:8000").rstrip("/")
    token = os.environ.get("CASELINK_TOKEN")
    http = client or httpx.AsyncClient(base_url=base, timeout=90,
                                       headers={"Authorization": f"Bearer {token}"} if token else {})
    server = MCPServer("CaseLink", instructions=INSTRUCTIONS, version="0.1.0")

    async def call(method: str, path: str, **kwargs) -> dict:
        resp = await http.request(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except ValueError:
                detail = resp.text[:200]
            return {"error": f"HTTP {resp.status_code}: {detail}"}
        return resp.json()

    @server.tool()
    async def list_cases(status: str | None = None, kind: str | None = None) -> dict:
        """List cases by priority. status: proposed, open, investigating, referred, closed.
        kind: overseas_job, bisp, parcel, bank_otp, task, family, prize."""
        out = await call("GET", "/api/cases", params={k: v for k, v in {"status": status, "kind": kind}.items() if v})
        if "error" in out:
            return out
        return {"cases": [{k: c[k] for k in ("id", "title", "status", "priority", "reports", "loss")} for c in out["cases"][:25]]}

    @server.tool()
    async def get_case(case_id: str) -> dict:
        """One case: summary with citations, key identifiers (masked), money trail and members."""
        out = await call("GET", f"/api/cases/{case_id}")
        if "error" in out:
            return out
        return {"case": out["case"], "summary": (out.get("summary") or {}).get("sentences"),
                "key_identifiers": [{k: x[k] for k in ("kind", "display", "reports", "bridge")} for x in out["key_identifiers"][:10]],
                "money": [{k: m[k] for k in ("display", "reports", "total")} for m in out["money"][:10]],
                "reports": [r["id"] for r in out["reports"]]}

    @server.tool()
    async def search_reports(query: str) -> dict:
        """Search reports by wording or by an identifier (phone number, IBAN, website, licence number)."""
        out = await call("GET", "/api/reports", params={"q": query[:300], "size": 15})
        return out if "error" in out else {"total": out["total"], "reports": out["reports"]}

    @server.tool()
    async def ask(question: str) -> dict:
        """Ask CaseLink's assistant a question; the answer cites reports and cases."""
        return await call("POST", "/api/ask", json={"question": question[:600]})

    return server


if __name__ == "__main__":
    create_server().run()
