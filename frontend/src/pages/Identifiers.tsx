import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, type EntityRow, type Report } from "../api";
import { CaseRef, Empty, ErrorBox, Gate, Loading, PageHead, ReportRef } from "../components/bits";
import { Timeline } from "../components/Charts";
import { ENTITY_LABEL, ROLE_LABEL, SOURCE_SHORT, day, family, money, plural } from "../lib/format";
import { useSession } from "../lib/session";
import { useAction, useApi } from "../lib/useApi";

export default function Identifiers() {
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState(params.get("q") ?? "");
  const urlQ = params.get("q") ?? "";
  useEffect(() => setDraft(urlQ), [urlQ]);
  const query = new URLSearchParams();
  for (const k of ["q", "kind"]) if (params.get(k)) query.set(k, params.get(k)!);
  if (params.get("watched")) query.set("watched", "true");
  const { data, error, loading, reload } = useApi<{ entities: EntityRow[] }>(`/api/entities?${query}`);
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  return (
    <div>
      <PageHead title="Identifiers" lead="Phone numbers, accounts, websites, emails, licence numbers, handles and agency names found in the reports, most reported first. Official numbers, like the FIA helpline, are listed but never used to link." />
      <form className="filters" role="search" onSubmit={(e) => { e.preventDefault(); set("q", draft.trim()); }}>
        <input className="input input--wide" type="search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="0300 1234567, PK36…, a website or a name" aria-label="Find an identifier" />
        <button className="btn">Find</button>
        <label className="select"><span className="sr">Kind</span>
          <select value={params.get("kind") ?? ""} onChange={(e) => set("kind", e.target.value)}>
            <option value="">Every kind</option>
            {Object.entries(ENTITY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="check"><input type="checkbox" checked={!!params.get("watched")} onChange={(e) => set("watched", e.target.checked ? "1" : "")} />Watchlist only</label>
      </form>
      {error && <ErrorBox error={error} retry={reload} />}
      {!data && loading ? <Loading /> : data && data.entities.length === 0 ? (
        <Empty>{params.get("watched") ? "Nothing is on the watchlist. Open an identifier and choose Watch to be alerted when it appears in a new report." : "Nothing matches."}</Empty>
      ) : data && (
        <div className={loading ? "tablewrap is-stale" : "tablewrap"}>
          <table className="table">
            <thead><tr><th scope="col">Identifier</th><th scope="col">Kind</th><th scope="col" className="num">Reports</th><th scope="col">Notes</th></tr></thead>
            <tbody>
              {data.entities.map((e) => (
                <tr key={e.id} className={e.official ? "is-muted" : undefined}>
                  <td><span className={`swatch swatch--${e.official ? "official" : family(e.kind)}`} aria-hidden /><Link to={`/identifiers/${e.id}`} className="ident">{e.display}</Link></td>
                  <td>{ENTITY_LABEL[e.kind] ?? e.kind}</td>
                  <td className="num">{e.reports}</td>
                  <td>
                    {e.official && <span className="tag">Official</span>}
                    {e.watched && <span className="tag tag--bad">Watched{e.watch_note ? `: ${e.watch_note}` : ""}</span>}
                    {!e.valid && <span className="tag">Fails its checksum</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface EntityDetail {
  entity: EntityRow;
  reports: (Report & { role: string })[];
  cases: string[];
  total: number;
}

export function IdentifierPage() {
  const { id = "" } = useParams();
  const { toast } = useSession();
  const { data, error, reload, setData } = useApi<EntityDetail>(`/api/entities/${id}`);
  const { busy, run } = useAction(toast);
  const [note, setNote] = useState("");
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return <Loading />;
  const e = data.entity;

  async function watch(on: boolean) {
    const out = await run("watch", () => api.post(`/api/entities/${e.id}/watch`, { watched: on, note }),
      on ? "On the watchlist. A new report with it raises an alert." : "Off the watchlist.");
    if (out) setData({ ...data!, entity: { ...e, watched: on, watch_note: on ? note || null : null } });
  }
  const paidInto = data.reports.filter((r) => r.role === "wallet" || r.role === "payee");

  return (
    <article className="narrow">
      <nav className="crumbs" aria-label="Breadcrumb"><Link to="/identifiers">Identifiers</Link></nav>
      <header className="pagehead">
        <div>
          <p className="kicker"><span className={`swatch swatch--${e.official ? "official" : family(e.kind)}`} aria-hidden />{ENTITY_LABEL[e.kind] ?? e.kind}</p>
          <h1 className="ident ident--big">{e.display}</h1>
          <p className="lead">
            In {plural(data.reports.length, "report")}{data.cases.length ? <> and {plural(data.cases.length, "case")}</> : null}.
            {paidInto.length ? ` ${plural(paidInto.length, "victim")} say they paid ${money(paidInto.reduce((s, r) => s + (r.amount ?? 0), 0))} into it.` : ""}
            {e.official ? " This is an official contact, so CaseLink never links reports through it." : ""}
          </p>
        </div>
      </header>
      {!e.official && (
        <section className="panel">
          <h2>Watchlist</h2>
          {e.watched ? (
            <p>Watched{e.watch_note ? `: ${e.watch_note}` : ""}. Any new report that contains it raises an alert on the desk.</p>
          ) : <p className="small">Watch it to be alerted when it turns up in a new report.</p>}
          <Gate role="analyst" action="change the watchlist">
            {e.watched ? (
              <button className="btn" onClick={() => watch(false)} disabled={!!busy}>Stop watching</button>
            ) : (
              <div className="actions__row">
                <input className="input" value={note} onChange={(ev) => setNote(ev.target.value)} placeholder="Why (optional)" maxLength={255} aria-label="Reason for watching" />
                <button className="btn btn--primary" onClick={() => watch(true)} disabled={!!busy}>Watch</button>
              </div>
            )}
          </Gate>
        </section>
      )}
      {data.cases.length > 0 && (
        <section className="panel">
          <h2>Cases</h2>
          <ul className="plain">{data.cases.map((c) => <li key={c}><CaseRef id={c} /></li>)}</ul>
        </section>
      )}
      {data.reports.length > 1 && (
        <section className="panel">
          <h2>When it was reported</h2>
          <Timeline points={data.reports.map((r) => ({ id: r.id, date: r.received_at, amount: r.amount, city: r.city }))} />
        </section>
      )}
      <section className="panel">
        <h2>Reports</h2>
        <ul className="replist">
          {data.reports.map((r) => (
            <li key={r.id} className="replist__item">
              <div className="replist__meta">
                <ReportRef id={r.id} /><span>{day(r.received_at)}</span><span>{SOURCE_SHORT[r.source] ?? r.source}</span>
                <span>{ROLE_LABEL[r.role] ?? r.role}</span>{r.amount != null && <span>{money(r.amount)}</span>}
                {r.case_id && <Link to={`/cases/${r.case_id}`} className="id id--link">{r.case_id}</Link>}
              </div>
              <p className="replist__text" dir="auto">{r.text}</p>
            </li>
          ))}
        </ul>
      </section>
    </article>
  );
}
