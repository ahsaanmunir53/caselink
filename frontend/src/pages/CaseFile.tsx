import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, download, type CaseDetail, type GraphData, type Summary, type User } from "../api";
import { ErrorBox, Field, Gate, Loading, Signed, StatusPill, Tlp } from "../components/bits";
import { CitedSentences } from "../components/Cite";
import NetworkGraph from "../components/NetworkGraph";
import { KIND_LABEL, SOURCE_SHORT, STATUS_HINT, day, moneyShort, person, plural } from "../lib/format";
import { useSession } from "../lib/session";
import { useAction, useApi } from "../lib/useApi";
import CaseTabs, { type TabName } from "./CaseTabs";

const Graph3D = lazy(() => import("../components/Graph3D"));
const STEPS = ["proposed", "open", "investigating", "referred", "closed"];

function Stepper({ status }: { status: string }) {
  if (status === "rejected" || status === "merged") return <p className="stepper__off">{STATUS_HINT[status]}</p>;
  const at = STEPS.indexOf(status);
  return (
    <ol className="stepper" aria-label="Where the case is">
      {STEPS.map((s, i) => (
        <li key={s} className={i < at ? "stepper__step is-done" : i === at ? "stepper__step is-now" : "stepper__step"} aria-current={i === at ? "step" : undefined}>
          <span className="stepper__dot" aria-hidden />
          {s.charAt(0).toUpperCase() + s.slice(1)}
        </li>
      ))}
    </ol>
  );
}

const MOVES: Record<string, { to: string; label: string; tone?: "primary" | "quiet" }[]> = {
  open: [{ to: "investigating", label: "Start investigating", tone: "primary" }],
  investigating: [
    { to: "referred", label: "Mark as referred", tone: "primary" },
    { to: "closed", label: "Close the case" },
    { to: "open", label: "Put back to open", tone: "quiet" },
  ],
  referred: [{ to: "closed", label: "Close the case" }, { to: "investigating", label: "Back to investigating", tone: "quiet" }],
  closed: [{ to: "investigating", label: "Reopen", tone: "quiet" }],
};

export default function CaseFile() {
  const { id = "" } = useParams();
  const caseId = id.toUpperCase();
  const navigate = useNavigate();
  const { user, can, toast } = useSession();
  const detail = useApi<CaseDetail>(`/api/cases/${caseId}`);
  const graph = useApi<GraphData>(detail.data?.reports.length ? `/api/cases/${caseId}/graph` : null);
  const people = useApi<{ users: User[] }>("/api/auth/demo-users");
  const { busy, run } = useAction(toast);
  const [tab, setTab] = useState<TabName>("reports");
  const [focus, setFocus] = useState<string | null>(null);
  const [three, setThree] = useState(false);
  const [note, setNote] = useState("");
  const [review, setReview] = useState<CaseDetail["review"] | null>(null);

  useEffect(() => {
    if (detail.data) {
      document.title = `${detail.data.case.id} ${detail.data.case.title} · CaseLink`;
      setReview(detail.data.review);
    }
  }, [detail.data]);

  const reports = useMemo(() => new Map((detail.data?.reports ?? []).map((r) => [r.id, r])), [detail.data]);
  const openReport = useCallback((rid: string) => {
    setTab("reports");
    setFocus(rid);
    requestAnimationFrame(() => document.getElementById(`rep-${rid}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, []);
  const openEntity = useCallback((eid: number) => navigate(`/identifiers/${eid}`), [navigate]);
  const reload = () => {
    detail.reload();
    graph.reload();
  };

  if (detail.error) return <ErrorBox error={detail.error} retry={detail.reload} />;
  if (!detail.data) return <Loading label={`Opening ${caseId}`} />;
  const d = detail.data;
  const c = d.case;
  const approved = !["proposed", "rejected", "merged"].includes(c.status);
  const exportable = approved && (!d.four_eyes || !!c.confirmed_by);
  const draft: Summary | null = review?.waiting ? review.draft : null;
  const summary = d.summary;

  async function startReview() {
    const out = await run("review", () => api.post<CaseDetail["review"]>(`/api/cases/${caseId}/review`));
    if (out) setReview(out);
  }
  async function decide(decision: "approve" | "reject" | "redraft") {
    const out = await run(decision, () => api.post<CaseDetail["review"]>(`/api/cases/${caseId}/review/decision`, { decision, note }),
      decision === "approve" ? "Case approved. It is now open." : decision === "reject" ? "Case rejected. Its reports are free again." : "A new draft is ready.");
    if (!out) return;
    setNote("");
    setReview(out);
    if (decision !== "redraft") reload();
  }
  async function move(to: string) {
    const ok = await run(to, () => api.post(`/api/cases/${caseId}/status`, { status: to, note }), `Case moved to ${to}.`);
    if (ok) {
      setNote("");
      reload();
    }
  }
  async function confirm() {
    if (await run("confirm", () => api.post(`/api/cases/${caseId}/confirm`), "Confirmed. The case can now be referred and exported.")) reload();
  }
  async function assign(email: string) {
    if (await run("assign", () => api.post(`/api/cases/${caseId}/assign`, { assignee: email || null }), email ? `Assigned to ${person(email)}.` : "Unassigned.")) reload();
  }
  async function resummarise() {
    if (await run("summary", () => api.post(`/api/cases/${caseId}/summary`), "New summary written.")) reload();
  }
  async function exportStix() {
    const bundle = await run("stix", () => api.get<unknown>(`/api/cases/${caseId}/export/stix`));
    if (bundle) download(`${caseId}-stix.json`, JSON.stringify(bundle, null, 2));
  }
  async function exportCsv() {
    const csv = await run("csv", () => api.text(`/api/cases/${caseId}/export/csv`));
    if (csv) download(`${caseId}-identifiers.csv`, csv, "text/csv");
  }

  const isApprover = !!user && c.approved_by === user.email;
  const topCities = d.cities.slice(0, 3).map(([k]) => k).join(", ");

  return (
    <article className="casefile">
      <nav className="crumbs" aria-label="Breadcrumb"><Link to="/cases">Cases</Link></nav>
      <header className="casefile__head">
        <div className="casefile__tab">
          <span className="casefile__id">{c.id}</span>
          <Tlp value={c.tlp} />
        </div>
        <h1 className="casefile__title">{c.title}</h1>
        <Stepper status={c.status} />
        <div className="signatures">
          <Signed verb="Approved" who={c.approved_by} at={c.approved_at} />
          <Signed verb="Confirmed" who={c.confirmed_by} at={c.confirmed_at} />
          {c.merged_into && <span>Merged into <Link to={`/cases/${c.merged_into}`}>{c.merged_into}</Link></span>}
        </div>
        <dl className="facts">
          <Field label="Reports">{d.reports.length}</Field>
          <Field label="Reported lost">{moneyShort(c.loss)}</Field>
          <Field label="First report">{day(d.first_seen)}</Field>
          <Field label="Latest report">{day(d.last_seen)}</Field>
          <Field label="Kind">{KIND_LABEL[c.kind] ?? c.kind}</Field>
          {d.countries.length > 0 && <Field label="Promised job in">{d.countries.map(([k]) => k).join(", ")}</Field>}
          {topCities && <Field label="Victims mostly from">{topCities}</Field>}
          <Field label="Sources">{d.sources.map(([k, n]) => `${SOURCE_SHORT[k] ?? k} (${n})`).join(", ")}</Field>
          <Field label="Priority">{c.priority} of 100</Field>
        </dl>
      </header>

      <section className="actions" aria-label="What you can do">
        <Gate role="analyst" action="review, move or assign this case">
          {c.status === "proposed" && !draft && (
            <div className="actions__row">
              <button className="btn btn--primary" onClick={startReview} disabled={!!busy}>{busy === "review" ? "Writing a draft…" : "Start the review"}</button>
              <p className="small">The writer drafts a summary from these reports, citing a report for every sentence. Then you approve, reject or ask for a new draft.</p>
            </div>
          )}
          {approved && (
            <div className="actions__row">
              {MOVES[c.status]?.map((m) => {
                const blocked = m.to === "referred" && d.four_eyes && !c.confirmed_by;
                return (
                  <button key={m.to} className={`btn ${m.tone === "primary" ? "btn--primary" : m.tone === "quiet" ? "btn--quiet" : ""}`}
                          onClick={() => move(m.to)} disabled={!!busy || blocked} title={blocked ? "A second person has to confirm the case first." : undefined}>
                    {busy === m.to ? "Saving…" : m.label}
                  </button>
                );
              })}
              {d.four_eyes && !c.confirmed_by && (c.status === "open" || c.status === "investigating") && (
                isApprover ? (
                  <p className="small">You approved this case, so someone else has to confirm it before it is referred or exported. Sign in as Bilal to try that.</p>
                ) : (
                  <button className="btn" onClick={confirm} disabled={!!busy}>{busy === "confirm" ? "Confirming…" : `Confirm as the second person`}</button>
                )
              )}
              <label className="select select--inline">
                <span>Assigned to</span>
                <select value={c.assignee ?? ""} onChange={(e) => assign(e.target.value)} disabled={!!busy}>
                  <option value="">Nobody</option>
                  {(people.data?.users ?? []).filter((u) => u.role !== "viewer").map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}
                  {user && !people.data?.users.some((u) => u.email === user.email) && <option value={user.email}>{user.name}</option>}
                </select>
              </label>
            </div>
          )}
          {(approved || draft) && (
            <label className="notefield">
              <span>Note for the record (optional, saved with your next decision)</span>
              <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} placeholder="Why you made this decision" />
            </label>
          )}
        </Gate>
        {approved && (
          <div className="actions__row actions__row--exports">
            {exportable ? (
              <>
                <button className="btn" onClick={exportStix} disabled={!!busy || !can("viewer")}>Download STIX 2.1</button>
                <button className="btn" onClick={exportCsv} disabled={!!busy || !can("viewer")}>Download identifiers (CSV)</button>
                {can("viewer") && <Link className="btn" to={`/cases/${caseId}/referral`}>Prepare the referral</Link>}
                {!can("viewer") && <p className="small"><Link to="/sign-in">Sign in</Link> to download exports or prepare the referral.</p>}
              </>
            ) : <p className="small">Exports and the referral open once a second person confirms the case.</p>}
          </div>
        )}
      </section>

      <div className="casefile__grid">
        <section className="panel summary" aria-labelledby="sum">
          {draft ? (
            <>
              <h2 id="sum">Draft summary for your review</h2>
              <p className="panel__lead">
                {draft.source === "ai" || draft.model ? `Written by ${draft.model}.` : "Written from the case facts by the template writer (no AI model answered)."}
                {" "}Every sentence cites reports; sentences that the cited reports do not support were removed.
              </p>
              {draft.error ? <p className="notice notice--bad">{draft.error}</p> : <CitedSentences sentences={draft.sentences} reports={reports} onOpen={openReport} />}
              {draft.next_steps?.length ? <><h3>Suggested next steps</h3><ul className="steps">{draft.next_steps.map((s) => <li key={s}>{s}</li>)}</ul></> : null}
              <Gate role="analyst" action="decide on this draft">
                <div className="decide">
                  <button className="btn btn--primary" onClick={() => decide("approve")} disabled={!!busy}>{busy === "approve" ? "Approving…" : "Approve the case"}</button>
                  <button className="btn" onClick={() => decide("redraft")} disabled={!!busy}>{busy === "redraft" ? "Drafting…" : "Ask for a new draft"}</button>
                  <button className="btn btn--danger" onClick={() => decide("reject")} disabled={!!busy}>{busy === "reject" ? "Rejecting…" : "Reject: these do not belong together"}</button>
                </div>
              </Gate>
            </>
          ) : summary?.sentences?.length ? (
            <>
              <h2 id="sum">Summary</h2>
              <p className="panel__lead">
                {summary.model ? `Written by ${summary.model}` : "Written by the template writer"}
                {summary.approved_by ? `, approved by ${person(summary.approved_by)}` : ""}. Hover a report number to read it.
              </p>
              <CitedSentences sentences={summary.sentences} reports={reports} onOpen={openReport} />
              {summary.next_steps?.length ? <><h3>Next steps</h3><ul className="steps">{summary.next_steps.map((s) => <li key={s}>{s}</li>)}</ul></> : null}
              {approved && can("analyst") && (
                <button className="linkbtn" onClick={resummarise} disabled={!!busy}>{busy === "summary" ? "Writing…" : "Write a fresh summary from the current reports"}</button>
              )}
            </>
          ) : (
            <>
              <h2 id="sum">Summary</h2>
              <p className="small">{c.status === "proposed" ? "No summary yet. Starting the review writes one." : "No summary was saved for this case."}</p>
            </>
          )}

          <h3>Key identifiers</h3>
          <p className="panel__lead">The identifiers that hold the case together. A bridge joins two groups of reports that share nothing else, so check it first.</p>
          <ul className="keys">
            {d.key_identifiers.map((k) => {
              const ent = d.entities.find((e) => e.value === k.value);
              return (
                <li key={k.value}>
                  {ent ? <Link to={`/identifiers/${ent.id}`} className="ident">{k.display}</Link> : <span className="ident">{k.display}</span>}
                  <span className="small">{plural(k.reports, "report")}</span>
                  {k.bridge && <span className="tag tag--ink">Bridge</span>}
                </li>
              );
            })}
          </ul>
        </section>

        <section className="panel panel--graph" aria-labelledby="net">
          <div className="panel__headrow">
            <h2 id="net">How the reports connect</h2>
            <div className="seg" role="group" aria-label="View">
              <button className={!three ? "seg__btn seg__btn--on" : "seg__btn"} aria-pressed={!three} onClick={() => setThree(false)}>Flat</button>
              <button className={three ? "seg__btn seg__btn--on" : "seg__btn"} aria-pressed={three} onClick={() => setThree(true)}>3D</button>
            </div>
          </div>
          {!d.reports.length ? <p className="small">No reports are left in this case, so there is nothing to connect.</p>
            : graph.error ? <ErrorBox error={graph.error} retry={graph.reload} /> : !graph.data ? <Loading label="Laying out the network" /> : three ? (
            <Suspense fallback={<Loading label="Loading the 3D view" />}>
              <Graph3D data={graph.data} onReport={openReport} onEntity={openEntity} />
            </Suspense>
          ) : (
            <NetworkGraph data={graph.data} onReport={openReport} onEntity={openEntity} />
          )}
          {d.related.length > 0 && (
            <>
              <h3>Possibly related cases</h3>
              <p className="panel__lead">These share a weaker clue, such as a similar agency name. Nothing was joined automatically.</p>
              <ul className="plain">
                {d.related.map((r) => (
                  <li key={r.id}>
                    <Link to={`/cases/${r.id}`} className="ref"><span className="id">{r.id}</span><span className="ref__title">{r.title}</span></Link>
                    <span className="small"> shares {r.why.map((w) => w.split(":").pop()).join(", ")}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>

      <CaseTabs detail={d} tab={tab} setTab={setTab} focus={focus} onChanged={reload} openReport={openReport} />
      {c.status !== "proposed" && <p className="small"><StatusPill status={c.status} /> {STATUS_HINT[c.status]}</p>}
    </article>
  );
}
