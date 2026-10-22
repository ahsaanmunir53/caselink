import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";

import type { CaseRow, Report, Summary } from "../api";
import { ErrorBox, Loading, Tlp } from "../components/bits";
import { ENTITY_LABEL, KIND_LABEL, day, money, person, when } from "../lib/format";
import { useApi } from "../lib/useApi";

interface ReferralData {
  case: CaseRow; summary: Summary | null; recipients: string[];
  freeze_requests: { kind: string; value: string; victims: number; amount: number; reports: string[] }[];
  identifiers: { id: number; kind: string; value: string; display: string; reports: string[]; roles: string[] }[];
  reports: Report[]; total_loss: number; first_seen: string; last_seen: string;
  prepared_by: string; prepared_at: string; tlp: string;
}

/** A printable case file: one page per agency to send it to, ready for the browser's print dialog. */
export default function Referral() {
  const { id = "" } = useParams();
  const { data, error, reload } = useApi<ReferralData>(`/api/cases/${id.toUpperCase()}/referral`);
  useEffect(() => {
    document.title = `Referral ${id.toUpperCase()} · CaseLink`;
  }, [id]);
  if (error) return <div className="narrow"><ErrorBox error={error} retry={reload} /><Link to={`/cases/${id}`}>Back to the case</Link></div>;
  if (!data) return <Loading label="Preparing the referral" />;
  const c = data.case;
  return (
    <div className="referral">
      <div className="referral__bar noprint">
        <Link to={`/cases/${c.id}`}>Back to {c.id}</Link>
        <button className="btn btn--primary" onClick={() => window.print()}>Print or save as PDF</button>
      </div>
      <article className="paper">
        <header className="paper__head">
          <Tlp value={data.tlp} />
          <p className="paper__demo">Demonstration document. All people, numbers and accounts are invented.</p>
          <h1>Case referral {c.id}</h1>
          <p className="paper__title">{c.title}</p>
          <dl className="facts facts--paper">
            <div className="field"><dt>Kind</dt><dd>{KIND_LABEL[c.kind] ?? c.kind}</dd></div>
            <div className="field"><dt>Reports</dt><dd>{data.reports.length}</dd></div>
            <div className="field"><dt>Reported lost</dt><dd>{money(data.total_loss)}</dd></div>
            <div className="field"><dt>Period</dt><dd>{day(data.first_seen)} to {day(data.last_seen)}</dd></div>
            <div className="field"><dt>Approved by</dt><dd>{person(c.approved_by)} on {day(c.approved_at)}</dd></div>
            <div className="field"><dt>Confirmed by</dt><dd>{person(c.confirmed_by)} on {day(c.confirmed_at)}</dd></div>
            <div className="field"><dt>Prepared by</dt><dd>{person(data.prepared_by)}, {when(data.prepared_at)}</dd></div>
          </dl>
        </header>

        <section>
          <h2>To</h2>
          <ul>{data.recipients.map((r) => <li key={r}>{r}</li>)}</ul>
        </section>

        {data.summary?.sentences?.length ? (
          <section>
            <h2>What happened</h2>
            {data.summary.sentences.map((s, i) => (
              <p key={i}>{s.text} <span className="paper__cite">({s.cites.slice(0, 6).join(", ")}{s.cites.length > 6 ? ", and others" : ""})</span></p>
            ))}
          </section>
        ) : null}

        {data.freeze_requests.length > 0 && (
          <section>
            <h2>Accounts to freeze</h2>
            <p>We ask each bank and wallet provider to freeze the account below and keep its records, pending a request from the investigating agency.</p>
            <table className="table">
              <thead><tr><th scope="col">Account</th><th scope="col">Type</th><th scope="col" className="num">Victims</th><th scope="col" className="num">Paid in</th><th scope="col">Reports</th></tr></thead>
              <tbody>
                {data.freeze_requests.map((f) => (
                  <tr key={f.value}><td className="ident">{f.value}</td><td>{f.kind === "iban" ? "Bank account" : "Mobile wallet"}</td><td className="num">{f.victims}</td><td className="num">{money(f.amount)}</td><td>{f.reports.join(", ")}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <section>
          <h2>Identifiers</h2>
          <table className="table">
            <thead><tr><th scope="col">Identifier</th><th scope="col">Kind</th><th scope="col" className="num">Reports</th></tr></thead>
            <tbody>
              {data.identifiers.map((e) => <tr key={e.id}><td className="ident">{e.value}</td><td>{ENTITY_LABEL[e.kind] ?? e.kind}</td><td className="num">{e.reports.length}</td></tr>)}
            </tbody>
          </table>
        </section>

        <section>
          <h2>Reports</h2>
          <table className="table">
            <thead><tr><th scope="col">Report</th><th scope="col">Received</th><th scope="col">From</th><th scope="col" className="num">Lost</th><th scope="col">Opening words</th></tr></thead>
            <tbody>
              {data.reports.map((r) => <tr key={r.id}><td className="ident">{r.id}</td><td>{day(r.received_at)}</td><td>{r.city}</td><td className="num">{r.amount != null ? money(r.amount) : ""}</td><td>{r.text.slice(0, 120)}…</td></tr>)}
            </tbody>
          </table>
        </section>
        <footer className="paper__foot">
          {data.tlp}: share with the organisations named above and the people in them who need to know. Generated by CaseLink; the full audit trail for {c.id} is kept with the case.
        </footer>
      </article>
    </div>
  );
}
