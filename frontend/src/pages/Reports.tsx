import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import type { Mention, Report } from "../api";
import { CaseRef, Empty, ErrorBox, Loading, PageHead, ReportRef } from "../components/bits";
import { ReportBody } from "../components/ReportText";
import { CHANNEL_LABEL, ENTITY_LABEL, KIND_LABEL, LANG_LABEL, ROLE_LABEL, SOURCE_LABEL, SOURCE_SHORT, day, family, isUrdu, money, moneyShort, plural } from "../lib/format";
import { useApi } from "../lib/useApi";

export default function Reports() {
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState(params.get("q") ?? "");
  const urlQ = params.get("q") ?? "";
  useEffect(() => setDraft(urlQ), [urlQ]);
  const page = Number(params.get("page") ?? 1);
  const query = new URLSearchParams();
  for (const k of ["q", "kind", "source", "language", "unassigned"]) if (params.get(k)) query.set(k, params.get(k)!);
  query.set("page", String(page));
  query.set("size", "40");
  const { data, error, loading, reload } = useApi<{ total: number; page: number; reports: Report[] }>(`/api/reports?${query}`);
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    next.delete("page");
    setParams(next, { replace: true });
  };
  const pages = data ? Math.ceil(data.total / 40) : 1;

  return (
    <div>
      <PageHead title="Reports" lead="Every complaint CaseLink holds, newest first. Search by wording or paste an identifier; a phone number matches however it was written." />
      <form className="filters" role="search" onSubmit={(e) => { e.preventDefault(); set("q", draft.trim()); }}>
        <input className="input input--wide" type="search" value={draft} onChange={(e) => setDraft(e.target.value)}
               placeholder="Words, a phone number, an IBAN or a website" aria-label="Search reports" />
        <button className="btn">Search</button>
        <label className="select"><span className="sr">Kind</span>
          <select value={params.get("kind") ?? ""} onChange={(e) => set("kind", e.target.value)} disabled={!!params.get("q")}>
            <option value="">Every kind</option>
            {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="select"><span className="sr">Source</span>
          <select value={params.get("source") ?? ""} onChange={(e) => set("source", e.target.value)} disabled={!!params.get("q")}>
            <option value="">Every source</option>
            {Object.entries(SOURCE_SHORT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="select"><span className="sr">Language</span>
          <select value={params.get("language") ?? ""} onChange={(e) => set("language", e.target.value)} disabled={!!params.get("q")}>
            <option value="">Every language</option>
            {Object.entries(LANG_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={params.get("unassigned") === "true"} onChange={(e) => set("unassigned", e.target.checked ? "true" : "")} disabled={!!params.get("q")} />
          Not in any case
        </label>
      </form>
      {params.get("q") && <p className="small">Showing the closest matches for “{params.get("q")}”. Filters apply to browsing, not to search. <button className="linkbtn" onClick={() => { setDraft(""); set("q", ""); }}>Clear the search</button></p>}
      {error && <ErrorBox error={error} retry={reload} />}
      {!data && loading ? <Loading /> : data && data.reports.length === 0 ? <Empty>No report matches. Try fewer words, or the last seven digits of a number.</Empty> : data && (
        <>
          <p className="small">{plural(data.total, "report")}</p>
          <ul className={loading ? "replist is-stale" : "replist"}>
            {data.reports.map((r) => (
              <li key={r.id} className="replist__item">
                <div className="replist__meta">
                  <ReportRef id={r.id} />
                  <span>{day(r.received_at)}</span>
                  <span>{KIND_LABEL[r.kind] ?? r.kind}</span>
                  <span>{SOURCE_SHORT[r.source] ?? r.source}</span>
                  {r.city && <span>{r.city}</span>}
                  {r.amount != null && <span>{moneyShort(r.amount)}</span>}
                  {r.case_id ? <Link to={`/cases/${r.case_id}`} className="id id--link">{r.case_id}</Link> : <span className="tag">Not in a case</span>}
                </div>
                <p className={isUrdu(r.text) ? "replist__text reporttext--urdu" : "replist__text"} dir="auto">{r.text}</p>
              </li>
            ))}
          </ul>
          {pages > 1 && (
            <nav className="pager" aria-label="Pages">
              <button className="btn btn--quiet" disabled={page <= 1} onClick={() => setParams((p) => { p.set("page", String(page - 1)); return p; })}>Newer</button>
              <span className="small">Page {page} of {pages}</span>
              <button className="btn btn--quiet" disabled={page >= pages} onClick={() => setParams((p) => { p.set("page", String(page + 1)); return p; })}>Older</button>
            </nav>
          )}
        </>
      )}
    </div>
  );
}

interface ReportDetail {
  report: Report;
  entities: { id: number; kind: string; value: string; display: string; official: boolean; watched: boolean; valid: boolean; role: string; found_by: string; raw: string }[];
  similar: { id: string; score: number; case_id: string | null; kind: string; text: string }[];
}

export function ReportPage() {
  const { id = "" } = useParams();
  const { data, error, reload } = useApi<ReportDetail>(`/api/reports/${id.toUpperCase()}`);
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return <Loading />;
  const r = data.report;
  const mentions: Mention[] = data.entities.map((e) => ({ raw: e.raw, kind: e.kind, entity_id: e.id, role: e.role, official: e.official }));
  return (
    <article className="narrow">
      <nav className="crumbs" aria-label="Breadcrumb"><Link to="/reports">Reports</Link></nav>
      <PageHead title={`Report ${r.id}`} lead={`${KIND_LABEL[r.kind] ?? r.kind}, received ${day(r.received_at)} from ${SOURCE_LABEL[r.source] ?? r.source}.`} />
      <dl className="facts">
        <div className="field"><dt>Case</dt><dd>{r.case_id ? <CaseRef id={r.case_id} /> : "Not in a case"}</dd></div>
        <div className="field"><dt>How it came in</dt><dd>{CHANNEL_LABEL[r.channel] ?? r.channel}</dd></div>
        <div className="field"><dt>Victim lives in</dt><dd>{r.city ?? "Not given"}</dd></div>
        {r.destination && <div className="field"><dt>Promised job in</dt><dd>{r.destination}</dd></div>}
        <div className="field"><dt>Lost</dt><dd>{money(r.amount)}</dd></div>
        <div className="field"><dt>Language</dt><dd>{LANG_LABEL[r.language] ?? r.language}</dd></div>
      </dl>
      <section className="panel">
        <h2>What the victim said</h2>
        <ReportBody report={r} mentions={mentions} />
        {r.duplicate_of && <p className="notice">This reads almost the same as <ReportRef id={r.duplicate_of} />. It may be the same complaint sent twice.</p>}
      </section>
      <section className="panel">
        <h2>Identifiers found</h2>
        {data.entities.length ? (
          <table className="table">
            <thead><tr><th scope="col">As written</th><th scope="col">Identifier</th><th scope="col">Kind</th><th scope="col">Used as</th><th scope="col">Found by</th></tr></thead>
            <tbody>
              {data.entities.map((e) => (
                <tr key={`${e.id}-${e.role}`} className={e.official ? "is-muted" : undefined}>
                  <td className="ident">{e.raw}</td>
                  <td><span className={`swatch swatch--${e.official ? "official" : family(e.kind)}`} aria-hidden /><Link to={`/identifiers/${e.id}`} className="ident">{e.display}</Link>{e.watched && <span className="tag tag--bad">Watched</span>}</td>
                  <td>{ENTITY_LABEL[e.kind] ?? e.kind}{e.official ? ", official" : ""}</td>
                  <td>{ROLE_LABEL[e.role] ?? e.role}</td>
                  <td>{e.found_by === "ai" ? "AI, checked by rules" : "Rules"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="small">No phone number, account, website or agency name was found. Walk-in reports often have none; the similar reports below may still help.</p>}
      </section>
      <section className="panel">
        <h2>Reads like</h2>
        <p className="panel__lead">Closest wording among all reports. Similar wording alone never joins reports; it only helps you look.</p>
        <ul className="plain">
          {data.similar.map((s) => (
            <li key={s.id}>
              <p className="tiny"><ReportRef id={s.id} /> {Math.round(s.score * 100)}% similar{s.case_id ? <>, in <Link to={`/cases/${s.case_id}`}>{s.case_id}</Link></> : ", not in a case"}</p>
              <p className="small" dir="auto">{s.text}</p>
            </li>
          ))}
        </ul>
      </section>
    </article>
  );
}
