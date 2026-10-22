import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, type AuditEntry } from "../api";
import { ErrorBox, Loading, PageHead } from "../components/bits";
import { when } from "../lib/format";
import { useApi } from "../lib/useApi";
import { actor, describe } from "./CaseTabs";

function target(a: AuditEntry) {
  if (a.object_type === "case" && /^C-\d+$/.test(a.object_id)) return <Link to={`/cases/${a.object_id}`} className="id id--link">{a.object_id}</Link>;
  if (a.object_type === "report" && /^R-\d+$/.test(a.object_id)) return <Link to={`/reports/${a.object_id}`} className="id id--link">{a.object_id}</Link>;
  if (a.object_type === "suggestion") return <Link to={`/suggestions/${a.object_id}`} className="id id--link">#{a.object_id}</Link>;
  if (a.object_type === "entity" && /^\d+$/.test(a.object_id)) return <Link to={`/identifiers/${a.object_id}`} className="id id--link">identifier {a.object_id}</Link>;
  return <span className="muted">{a.object_type === "report" || a.object_type === "case" ? a.object_id : a.object_type}</span>;
}

export default function Audit() {
  const [params, setParams] = useSearchParams();
  const page = Number(params.get("page") ?? 1);
  const q = new URLSearchParams({ page: String(page), size: "50" });
  if (params.get("actor")) q.set("actor", params.get("actor")!);
  if (params.get("object_id")) q.set("object_id", params.get("object_id")!);
  const { data, error, loading, reload } = useApi<{ total: number; entries: AuditEntry[] }>(`/api/audit?${q}`);
  const [check, setCheck] = useState<{ ok: boolean; entries: number; head?: string; broken_at?: number; detail?: string } | null>(null);
  const [checking, setChecking] = useState(false);

  async function verify() {
    setChecking(true);
    try {
      setCheck(await api.get("/api/audit/verify"));
    } catch (e) {
      setCheck({ ok: false, entries: 0, detail: `the check could not run (${(e as Error).message})` });
    } finally {
      setChecking(false);
    }
  }
  const pages = data ? Math.max(1, Math.ceil(data.total / 50)) : 1;
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    next.delete("page");
    setParams(next, { replace: true });
  };

  return (
    <div>
      <PageHead title="Audit log" lead="Everything the agents and the people did, newest first. Each entry stores a SHA-256 hash of itself and of the entry before it, so editing or deleting one breaks the chain.">
        <button className="btn" onClick={verify} disabled={checking}>{checking ? "Checking…" : "Check the chain"}</button>
      </PageHead>
      {check && (
        <div className={check.ok ? "notice notice--ok" : "notice notice--bad"} role="status">
          {check.ok ? (
            <p>All {check.entries.toLocaleString("en")} entries check out. Latest hash <code className="hash">{check.head?.slice(0, 16)}</code>.</p>
          ) : (
            <p>{check.broken_at ? `The chain breaks at entry ${check.broken_at}: ${check.detail ?? "a hash does not match"}.` : `Not checked: ${check.detail}.`}</p>
          )}
        </div>
      )}
      <div className="filters">
        <label className="select"><span className="sr">Who</span>
          <select value={params.get("actor") ?? ""} onChange={(e) => set("actor", e.target.value)}>
            <option value="">Everyone</option>
            <option value="agent:">Agents only</option>
            <option value="@">People only</option>
            <option value="system:">System</option>
          </select>
        </label>
        <input className="input" placeholder="Case, report or suggestion id" defaultValue={params.get("object_id") ?? ""} aria-label="Filter by object"
               onKeyDown={(e) => e.key === "Enter" && set("object_id", (e.target as HTMLInputElement).value.trim().toUpperCase())} />
      </div>
      {error && <ErrorBox error={error} retry={reload} />}
      {!data && loading ? <Loading /> : data && (
        <>
          <div className={loading ? "tablewrap is-stale" : "tablewrap"}>
            <table className="table">
              <thead><tr><th scope="col">When</th><th scope="col">Who</th><th scope="col">What</th><th scope="col">On</th><th scope="col">Hash</th></tr></thead>
              <tbody>
                {data.entries.map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap">{when(a.ts)}</td>
                    <td className={a.actor.startsWith("agent:") ? "who who--agent" : "who"}>{actor(a.actor)}</td>
                    <td>{describe(a)}</td>
                    <td>{target(a)}</td>
                    <td><code className="hash" title={`This entry ${a.hash}\nPrevious ${a.prev_hash}`}>{a.hash.slice(0, 10)}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav className="pager" aria-label="Pages">
            <button className="btn btn--quiet" disabled={page <= 1} onClick={() => setParams((p) => { p.set("page", String(page - 1)); return p; })}>Newer</button>
            <span className="small">Page {page} of {pages}</span>
            <button className="btn btn--quiet" disabled={page >= pages} onClick={() => setParams((p) => { p.set("page", String(page + 1)); return p; })}>Older</button>
          </nav>
        </>
      )}
    </div>
  );
}
