import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, download, type CaseRow } from "../api";
import { Empty, ErrorBox, Loading, PageHead, Priority, Signed, StatusPill } from "../components/bits";
import { KIND_LABEL, STATUS_LABEL, day, moneyShort, person } from "../lib/format";
import { useSession } from "../lib/session";
import { useAction, useApi } from "../lib/useApi";

const STATUSES = ["proposed", "open", "investigating", "referred", "closed", "rejected"];

export default function Cases() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const kind = params.get("kind") ?? "";
  const q = params.get("q") ?? "";
  const path = `/api/cases?${new URLSearchParams({ ...(status && { status }), ...(kind && { kind }) })}`;
  const { data, error, loading, reload } = useApi<{ cases: CaseRow[] }>(path);
  const { can, toast } = useSession();
  const { busy, run } = useAction(toast);
  async function exportAll() {
    const bundle = await run("all", () => api.get<{ objects?: unknown[] }>("/api/export/stix"));
    if (bundle) download(`caselink-confirmed-cases-stix.json`, JSON.stringify(bundle, null, 2));
  }
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (data?.cases ?? []).filter((c) => !t || c.title.toLowerCase().includes(t) || c.id.toLowerCase().includes(t) || (c.assignee ?? "").includes(t));
  }, [data, q]);
  const chosen = new Set(status.split(",").filter(Boolean));
  const toggle = (s: string) => {
    const next = new Set(chosen);
    if (next.has(s)) next.delete(s);
    else next.add(s);
    set("status", [...next].join(","));
  };

  return (
    <div>
      <PageHead title="Cases" lead="Each case is a group of reports the linker joined through a shared identifier, or that an analyst joined by hand.">
        {can("supervisor") && (
          <button className="btn" onClick={exportAll} disabled={!!busy} title="Every approved case that a second person confirmed, as one STIX 2.1 bundle">
            {busy ? "Preparing…" : "Export all confirmed cases (STIX)"}
          </button>
        )}
      </PageHead>
      <div className="filters" role="group" aria-label="Filter cases">
        <div className="chips">
          {STATUSES.map((s) => (
            <button key={s} className={chosen.has(s) ? "chip chip--on" : "chip"} aria-pressed={chosen.has(s)} onClick={() => toggle(s)}>
              {STATUS_LABEL[s]}
            </button>
          ))}
        </div>
        <label className="select">
          <span className="sr">Kind of fraud</span>
          <select value={kind} onChange={(e) => set("kind", e.target.value)}>
            <option value="">Every kind of fraud</option>
            {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <input className="input" type="search" placeholder="Filter by title, case number or assignee" value={q} onChange={(e) => set("q", e.target.value)} aria-label="Filter cases" />
      </div>
      {error && <ErrorBox error={error} retry={reload} />}
      {!data && loading ? <Loading /> : rows.length === 0 ? (
        <Empty>No case matches these filters. <button className="linkbtn" onClick={() => setParams({})}>Clear the filters</button></Empty>
      ) : (
        <div className={loading ? "tablewrap is-stale" : "tablewrap"}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Priority</th><th scope="col">Case</th><th scope="col">Status</th>
                <th scope="col" className="num">Reports</th><th scope="col" className="num">Reported lost</th>
                <th scope="col">Latest report</th><th scope="col">With</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td><Priority value={c.priority} /></td>
                  <td>
                    <Link to={`/cases/${c.id}`} className="casecell">
                      <span className="id">{c.id}</span>
                      <span className="casecell__title">{c.title}</span>
                    </Link>
                    {c.pending_suggestions ? <span className="tag">{c.pending_suggestions} waiting</span> : null}
                  </td>
                  <td>
                    <StatusPill status={c.status} />
                    {c.confirmed_by && <div className="tiny"><Signed verb="Confirmed" who={c.confirmed_by} /></div>}
                  </td>
                  <td className="num">{c.reports}</td>
                  <td className="num">{moneyShort(c.loss)}</td>
                  <td>{day(c.last_report)}</td>
                  <td>{c.assignee ? person(c.assignee) : <span className="muted">Nobody</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
