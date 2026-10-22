import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { CaseRow, Overview } from "../api";
import { CaseRef, ErrorBox, Loading, Priority, StatusPill } from "../components/bits";
import { Bars, ChartFrame, Columns } from "../components/Charts";
import { KIND_LABEL, LANG_LABEL, SOURCE_SHORT, monthLabel, moneyShort, plural, when } from "../lib/format";
import { useSession } from "../lib/session";
import { useApi } from "../lib/useApi";

export default function Desk() {
  const ov = useApi<Overview>("/api/overview");
  const cs = useApi<{ cases: CaseRow[] }>("/api/cases");
  const navigate = useNavigate();
  const { health } = useSession();
  useEffect(() => {
    document.title = "Desk · CaseLink";
  }, []);

  if (ov.error) return <ErrorBox error={ov.error} retry={ov.reload} />;
  if (!ov.data) return <Loading label="Loading the desk" />;
  const o = ov.data;
  const cases = cs.data?.cases ?? [];
  const proposed = cases.filter((c) => c.status === "proposed");
  const fourEyes = health?.four_eyes ?? true;
  const unconfirmed = fourEyes ? cases.filter((c) => (c.status === "open" || c.status === "investigating") && !c.confirmed_by) : [];
  const unseen = o.alerts.filter((a) => !a.seen);
  const decisions = proposed.length + o.pending_suggestions + unconfirmed.length;

  return (
    <div className="desk">
      <section className="desk__hero" aria-labelledby="desk-title">
        <h1 id="desk-title" className="statement">
          {decisions ? (
            <>
              <Link to="/cases?status=proposed">{plural(proposed.length, "proposed case")}</Link>
              {", "}
              <Link to="/suggestions">{plural(o.pending_suggestions, "suggested link")}</Link>
              {unconfirmed.length ? <>{" and "}<Link to="/cases?status=open,investigating">{plural(unconfirmed.length, "case")} without a second check</Link></> : null}
              {" are waiting for a person."}
            </>
          ) : "Nothing is waiting for a decision."}
        </h1>
        <p className="lead">
          {plural(o.reports, "report")} from Hoshiyar, Pardes Guard and police desks, with {moneyShort(o.total_loss)} reported lost.
          The linker put {plural(o.reports_in_cases, "report")} into {plural(o.cases, "case")} using shared phone numbers, accounts and websites.
          Weaker clues, like similar agency names, wait for an analyst.
        </p>
      </section>

      <div className="desk__grid">
        <section className="panel" aria-labelledby="queue">
          <h2 id="queue">Review next</h2>
          <p className="panel__lead">Proposed cases, highest priority first. Priority weighs the number of victims, the money lost, and how recent the reports are.</p>
          {cs.loading && !cs.data ? <Loading /> : (
            <ol className="queue">
              {proposed.slice(0, 7).map((c) => (
                <li key={c.id} className="queue__row">
                  <Priority value={c.priority} />
                  <CaseRef id={c.id} title={c.title} />
                  <span className="queue__meta">{plural(c.reports ?? 0, "report")}, {moneyShort(c.loss)}</span>
                  {c.pending_suggestions ? <span className="tag">{plural(c.pending_suggestions, "suggestion")}</span> : <span />}
                </li>
              ))}
            </ol>
          )}
          {proposed.length > 7 && <Link className="more" to="/cases?status=proposed">All {proposed.length} proposed cases</Link>}
          {unconfirmed.length > 0 && (
            <>
              <h3>Needs a second person</h3>
              <p className="panel__lead">Approved, but someone other than the approver has to confirm before a case is referred or exported.</p>
              <ul className="queue">
                {unconfirmed.slice(0, 5).map((c) => (
                  <li key={c.id} className="queue__row">
                    <StatusPill status={c.status} />
                    <CaseRef id={c.id} title={c.title} />
                    <span className="queue__meta">approved by {c.approved_by?.split("@")[0].split(".")[0]}</span>
                    <span />
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <div className="desk__side">
          <section className="panel" aria-labelledby="growing">
            <h2 id="growing">Growing fast</h2>
            {o.emerging.length ? (
              <ul className="plain">
                {o.emerging.map((e) => (
                  <li key={e.case_id}>
                    <CaseRef id={e.case_id} title={e.title} />
                    <p className="small">{plural(e.recent, "new report")} in the last {e.days} days, against {e.earlier} before that.</p>
                  </li>
                ))}
              </ul>
            ) : <p className="small">No case is growing faster than usual.</p>}
          </section>

          <section className="panel" aria-labelledby="money">
            <h2 id="money">Follow the money</h2>
            <p className="panel__lead">Accounts and wallets victims paid into, by total reported.</p>
            <ol className="money">
              {o.top_money.map((m) => (
                <li key={m.entity_id}>
                  <Link to={`/identifiers/${m.entity_id}`} className="ident">{m.display}</Link>
                  <span className="money__kind">{m.kind === "iban" ? "Bank account" : "Wallet"}</span>
                  <span className="money__total">{moneyShort(m.total)}</span>
                  <span className="money__who">{plural(m.reports, "victim")}{m.cases.length ? ", " : ""}{m.cases.map((c) => <Link key={c} to={`/cases/${c}`} className="id id--link">{c}</Link>)}</span>
                </li>
              ))}
            </ol>
          </section>

          {unseen.length > 0 && (
            <section className="panel" aria-labelledby="alerts">
              <h2 id="alerts">Alerts</h2>
              <ul className="plain">
                {unseen.slice(0, 5).map((a) => (
                  <li key={a.id}>
                    <p className="small"><span className="tag">{a.kind}</span> {a.message}</p>
                    <p className="tiny">{when(a.created_at)} {a.case_id && <Link to={`/cases/${a.case_id}`}>Open {a.case_id}</Link>}</p>
                  </li>
                ))}
              </ul>
              <Link className="more" to="/alerts">All alerts</Link>
            </section>
          )}
        </div>
      </div>

      <section className="desk__charts" aria-label="Reports at a glance">
        <ChartFrame title="Reports received each month" table={o.by_month.map(([k, v]) => [monthLabel(k), String(v)])}>
          <Columns data={o.by_month} label={monthLabel} />
        </ChartFrame>
        <ChartFrame title="Kind of fraud" table={o.by_kind.map(([k, v]) => [KIND_LABEL[k] ?? k, String(v)])}>
          <Bars data={o.by_kind} label={(k) => KIND_LABEL[k] ?? k} onPick={(k) => navigate(`/reports?kind=${k}`)} />
        </ChartFrame>
        <ChartFrame title="Where the victims live" table={o.by_city.map(([k, v]) => [k, String(v)])}>
          <Bars data={o.by_city} />
        </ChartFrame>
        <ChartFrame title="Country of the promised job" table={o.by_country.map(([k, v]) => [k, String(v)])}>
          <Bars data={o.by_country} />
        </ChartFrame>
        <ChartFrame title="Where reports come from" table={o.by_source.map(([k, v]) => [SOURCE_SHORT[k] ?? k, String(v)])}>
          <Bars data={o.by_source} label={(k) => SOURCE_SHORT[k] ?? k} onPick={(k) => navigate(`/reports?source=${k}`)} />
        </ChartFrame>
        <ChartFrame title="Language of the report" table={o.by_language.map(([k, v]) => [LANG_LABEL[k] ?? k, String(v)])}>
          <Bars data={o.by_language} label={(k) => LANG_LABEL[k] ?? k} onPick={(k) => navigate(`/reports?language=${k}`)} />
        </ChartFrame>
      </section>
      <p className="tiny">Phone numbers and accounts are shown part-hidden in lists, as they would be on a shared screen. Bank accounts show the bank code and the last four digits.</p>
    </div>
  );
}
