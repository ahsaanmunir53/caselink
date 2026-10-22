import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api, type AuditEntry, type CaseDetail } from "../api";
import { Empty, Gate, ReportRef } from "../components/bits";
import { Bars, ChartFrame, Timeline } from "../components/Charts";
import { ReportBody } from "../components/ReportText";
import { CHANNEL_LABEL, ENTITY_LABEL, LANG_LABEL, ROLE_LABEL, SOURCE_SHORT, day, family, money, moneyShort, person, plural, when } from "../lib/format";
import { useSession } from "../lib/session";
import { useAction, useApi } from "../lib/useApi";

export type TabName = "reports" | "money" | "timeline" | "identifiers" | "notes" | "waiting";

export default function CaseTabs({ detail: d, tab, setTab, focus, onChanged, openReport }: {
  detail: CaseDetail; tab: TabName; setTab: (t: TabName) => void; focus: string | null; onChanged: () => void; openReport: (id: string) => void;
}) {
  const waiting = d.suggestions.filter((s) => s.status === "pending");
  const tabs: [TabName, string][] = [
    ["reports", `Reports (${d.reports.length})`],
    ["money", `Follow the money (${d.money.length})`],
    ["timeline", "Timeline and places"],
    ["identifiers", `Identifiers (${d.entities.filter((e) => !e.official).length})`],
    ["notes", `Notes and history (${d.notes.length})`],
    ["waiting", `Waiting links (${waiting.length})`],
  ];
  return (
    <section className="tabs">
      <div className="tabs__list" role="tablist" aria-label="Case details">
        {tabs.map(([k, label]) => (
          <button key={k} role="tab" id={`tab-${k}`} aria-selected={tab === k} aria-controls={`panel-${k}`}
                  className={tab === k ? "tabs__tab tabs__tab--on" : "tabs__tab"} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="tabs__panel">
        {tab === "reports" && <ReportsTab d={d} focus={focus} onChanged={onChanged} />}
        {tab === "money" && <MoneyTab d={d} />}
        {tab === "timeline" && <TimelineTab d={d} openReport={openReport} />}
        {tab === "identifiers" && <IdentifiersTab d={d} />}
        {tab === "notes" && <NotesTab d={d} onChanged={onChanged} />}
        {tab === "waiting" && <WaitingTab d={d} />}
      </div>
    </section>
  );
}

function ReportsTab({ d, focus, onChanged }: { d: CaseDetail; focus: string | null; onChanged: () => void }) {
  const { can, toast } = useSession();
  const { busy, run } = useAction(toast);
  async function remove(rid: string) {
    if (await run(rid, () => api.post(`/api/cases/${d.case.id}/remove-report`, { report_id: rid }), `${rid} taken out of the case. The linker will not put it back.`)) onChanged();
  }
  return (
    <>
      <p className="small">Marked text is what the rules extracted. Follow a mark to see every report that identifier appears in.</p>
      <ol className="evidence">
        {d.reports.map((r) => (
          <li key={r.id} id={`rep-${r.id}`} className={focus === r.id ? "evidence__item is-focus" : "evidence__item"}>
            <div className="evidence__meta">
              <ReportRef id={r.id} />
              <span>{day(r.received_at)}</span>
              <span>{SOURCE_SHORT[r.source] ?? r.source}, {CHANNEL_LABEL[r.channel] ?? r.channel}</span>
              {r.city && <span>From {r.city}</span>}
              {r.destination && <span>Job in {r.destination}</span>}
              <span>{LANG_LABEL[r.language] ?? r.language}</span>
              <span className="evidence__amount">{r.amount != null ? money(r.amount) : "No amount given"}</span>
            </div>
            <ReportBody report={r} mentions={d.mentions[r.id]} />
            <div className="evidence__foot">
              {r.pinned && <span className="tag">Placed by a person</span>}
              {r.duplicate_of && <span className="tag">Reads like a repeat of <ReportRef id={r.duplicate_of} /></span>}
              {can("analyst") && d.case.status !== "rejected" && d.reports.length > 1 && (
                <button className="linkbtn linkbtn--danger" onClick={() => remove(r.id)} disabled={!!busy}>
                  {busy === r.id ? "Taking out…" : "Take out of this case"}
                </button>
              )}
            </div>
          </li>
        ))}
      </ol>
    </>
  );
}

function MoneyTab({ d }: { d: CaseDetail }) {
  if (!d.money.length) return <Empty>No report names an account or wallet that money was sent to.</Empty>;
  const total = d.money.reduce((s, m) => s + m.total, 0);
  return (
    <>
      <p className="small">
        Victims say they paid {moneyShort(total)} into {plural(d.money.length, "account")}. A freeze request to each bank or wallet goes in the referral.
      </p>
      <table className="table">
        <thead><tr><th scope="col">Account</th><th scope="col">Type</th><th scope="col" className="num">Victims</th><th scope="col" className="num">Paid in</th><th scope="col">Reports</th></tr></thead>
        <tbody>
          {d.money.map((m) => (
            <tr key={m.entity_id}>
              <td><Link to={`/identifiers/${m.entity_id}`} className="ident">{m.display}</Link></td>
              <td>{m.kind === "iban" ? "Bank account" : "Mobile wallet"}</td>
              <td className="num">{m.reports}</td>
              <td className="num">{money(m.total)}</td>
              <td className="idlist">{m.report_ids.map((r) => <ReportRef key={r} id={r} />)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function TimelineTab({ d, openReport }: { d: CaseDetail; openReport: (id: string) => void }) {
  return (
    <div className="twocol">
      <ChartFrame title="Each report: when it came in and how much was lost" note="Hollow dots are reports that gave no amount."
                  table={d.timeline.map((t) => [`${t.id}, ${day(t.date)}`, t.amount != null ? money(t.amount) : "Not given"])}>
        <Timeline points={d.timeline} onPick={openReport} />
      </ChartFrame>
      <div>
        <ChartFrame title="Where the victims live" table={d.cities.map(([k, v]) => [k, String(v)])}>
          <Bars data={d.cities.slice(0, 10)} />
        </ChartFrame>
        {d.countries.length > 0 && (
          <ChartFrame title="Country of the promised job" table={d.countries.map(([k, v]) => [k, String(v)])}>
            <Bars data={d.countries} />
          </ChartFrame>
        )}
        <ChartFrame title="Language of the reports" table={d.languages.map(([k, v]) => [LANG_LABEL[k] ?? k, String(v)])}>
          <Bars data={d.languages} label={(k) => LANG_LABEL[k] ?? k} />
        </ChartFrame>
      </div>
    </div>
  );
}

function IdentifiersTab({ d }: { d: CaseDetail }) {
  return (
    <table className="table">
      <thead><tr><th scope="col">Identifier</th><th scope="col">Kind</th><th scope="col">Used as</th><th scope="col" className="num">Reports</th><th scope="col">Found by</th></tr></thead>
      <tbody>
        {d.entities.map((e) => (
          <tr key={e.id} className={e.official ? "is-muted" : undefined}>
            <td>
              <span className={`swatch swatch--${e.official ? "official" : family(e.kind)}`} aria-hidden />
              <Link to={`/identifiers/${e.id}`} className="ident">{e.display}</Link>
              {e.watched && <span className="tag tag--bad">Watched</span>}
              {!e.valid && <span className="tag" title="The IBAN checksum fails or the number is malformed.">Fails its checksum</span>}
            </td>
            <td>{ENTITY_LABEL[e.kind] ?? e.kind}{e.official ? ", official (never used to link)" : ""}</td>
            <td>{e.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ")}</td>
            <td className="num">{e.reports.length}</td>
            <td>{e.sources.map((s) => (s === "rules" ? "Rules" : s === "ai" ? "AI (checked)" : s)).join(", ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NotesTab({ d, onChanged }: { d: CaseDetail; onChanged: () => void }) {
  const { toast } = useSession();
  const { busy, run } = useAction(toast);
  const [text, setText] = useState("");
  const history = useApi<{ entries: AuditEntry[] }>(`/api/audit?object_id=${d.case.id}&size=100`);
  async function add(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    if (await run("note", () => api.post(`/api/cases/${d.case.id}/notes`, { text }), "Note saved.")) {
      setText("");
      onChanged();
      history.reload();
    }
  }
  return (
    <div className="twocol">
      <div>
        <h3>Notes</h3>
        {d.notes.length ? (
          <ul className="notes">
            {d.notes.map((n) => (
              <li key={n.id}><p>{n.text}</p><p className="tiny">{person(n.author)}, {when(n.created_at)}</p></li>
            ))}
          </ul>
        ) : <p className="small">No notes yet.</p>}
        <Gate role="analyst" action="add a note">
          <form className="form" onSubmit={add}>
            <label>Add a note<textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} placeholder="What you checked, who you called, what is still open" /></label>
            <button className="btn" disabled={busy === "note" || !text.trim()}>{busy === "note" ? "Saving…" : "Save note"}</button>
          </form>
        </Gate>
      </div>
      <div>
        <h3>History</h3>
        <p className="small">From the audit log. Each entry carries the hash of the one before it, so a changed or deleted entry shows up when the chain is checked.</p>
        <ol className="history">
          {(history.data?.entries ?? []).map((a) => (
            <li key={a.id}>
              <span className="history__what">{describe(a)}</span>
              <span className="tiny">{actor(a.actor)}, {when(a.ts)}</span>
            </li>
          ))}
        </ol>
        <Link className="more" to={`/audit?object_id=${d.case.id}`}>Open in the audit log</Link>
      </div>
    </div>
  );
}

export function actor(a: string): string {
  if (a.startsWith("agent:")) return `${a.slice(6).charAt(0).toUpperCase()}${a.slice(7)} agent`;
  if (a.startsWith("system:")) return "System";
  return person(a);
}

export function describe(a: AuditEntry): string {
  const det = a.details as Record<string, unknown>;
  switch (a.action) {
    case "case.proposed": return `Proposed the case from ${Array.isArray(det.reports) ? det.reports.length : "its"} reports`;
    case "case.approved": return "Approved the case";
    case "case.rejected": return `Rejected the case${det.reason ? `: ${det.reason}` : ""}`;
    case "case.report_attached": return `Added ${det.report ?? "a report"} through a ${det.rule ?? "shared identifier"}`;
    case "suggestion.accepted": return `Accepted suggestion #${a.object_id}`;
    case "suggestion.rejected": return `Rejected suggestion #${a.object_id}`;
    case "suggestion.second_opinion": return `Gave a second opinion: ${det.verdict}`;
    case "report.translated": return `Translated ${a.object_id}`;
    case "report.ai_extracted": return `Read ${a.object_id} for identifiers the rules missed`;
    case "entity.watch": return `Put ${det.display ?? "an identifier"} on the watchlist`;
    case "entity.unwatch": return `Took ${det.display ?? "an identifier"} off the watchlist`;
    case "linker.rebuild": return `Relinked ${det.reports ?? ""} reports`;
    case "question.answered": return `Answered: “${String(det.question ?? "").slice(0, 80)}”`;
    case "demo.reset": return "Reset the demo";
    case "cases.exported": return "Exported every confirmed case as STIX";
    case "case.confirmed": return "Confirmed the case as the second person";
    case "case.status": return `Moved from ${det.from} to ${det.to}${det.note ? `: ${det.note}` : ""}`;
    case "case.assigned": return det.assignee ? `Assigned to ${person(String(det.assignee))}` : "Unassigned";
    case "case.note": return "Added a note";
    case "case.exported": return `Exported as ${String(det.format).toUpperCase()}`;
    case "case.referral_prepared": return "Prepared the referral";
    case "summary.drafted": return "Drafted a summary";
    case "summary.written": return "Wrote a new summary";
    case "case.report_removed": return `Took out ${det.report ?? "a report"}`;
    default: return a.action.replace(/[._]/g, " ");
  }
}

function WaitingTab({ d }: { d: CaseDetail }) {
  const waiting = d.suggestions.filter((s) => s.status === "pending");
  const decided = d.suggestions.filter((s) => s.status !== "pending");
  return (
    <>
      {waiting.length ? (
        <ul className="plain">
          {waiting.map((s) => (
            <li key={s.id}>
              <Link to={`/suggestions/${s.id}`}>
                {s.kind === "attach" ? `Add ${s.report_ids.join(", ")} to this case` : s.kind === "merge" ? `Join with ${s.case_id === d.case.id ? s.other_case_id : s.case_id}` : "Start a new case"}
              </Link>
              <span className="small"> because of {s.reasons.map((r) => r.detail.split(":").pop()).join(", ")}, score {s.score.toFixed(2)}</span>
            </li>
          ))}
        </ul>
      ) : <Empty>No suggested links are waiting for this case.</Empty>}
      {decided.length > 0 && (
        <>
          <h3>Decided</h3>
          <ul className="plain">
            {decided.map((s) => <li key={s.id} className="small">#{s.id} {s.status} by {person(s.decided_by)} on {day(s.decided_at)}</li>)}
          </ul>
        </>
      )}
    </>
  );
}
