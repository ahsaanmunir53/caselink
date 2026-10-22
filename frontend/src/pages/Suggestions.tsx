import { useEffect } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api, type Reason, type Report, type Suggestion } from "../api";
import { Empty, ErrorBox, Gate, Loading, PageHead, ReportRef } from "../components/bits";
import { SOURCE_SHORT, dayShort, isUrdu, moneyShort, person, plural } from "../lib/format";
import { useSession } from "../lib/session";
import { useAction, useApi } from "../lib/useApi";

function title(s: Suggestion): string {
  if (s.kind === "attach") return `Add ${s.report_ids.join(", ")} to ${s.case_id}`;
  if (s.kind === "merge") return `Join ${s.case_id} and ${s.other_case_id}`;
  return `Start a case from ${plural(s.report_ids.length, "loose report")}`;
}

export function explain(r: Reason): string {
  const value = r.detail.split(":").slice(1).join(":");
  if (r.kind === "name") return `The same agency name, “${value}”, once words like Overseas, Manpower and Agency are set aside.`;
  if (r.kind === "common_name") return `The same agency name, “${value}”, but it is a common one that unrelated agencies use, so it counts for little.`;
  if (r.kind === "abbreviation") {
    const [short, long] = value.split("=");
    return `“${short.toUpperCase()}” looks like the first letters of “${long}”.`;
  }
  if (r.kind === "spelling") {
    const [a, b] = value.split("~");
    return `“${a}” and “${b ?? ""}” are spelled almost the same.`;
  }
  return r.detail;
}

function Side({ label, reports }: { label: string; reports: Report[] }) {
  return (
    <div className="side">
      <h3>{label}</h3>
      <ol className="side__list">
        {reports.slice(0, 8).map((r) => (
          <li key={r.id}>
            <p className="tiny"><ReportRef id={r.id} /> {dayShort(r.received_at)}, {SOURCE_SHORT[r.source] ?? r.source}{r.city ? `, ${r.city}` : ""}{r.amount ? `, ${moneyShort(r.amount)}` : ""}</p>
            <p className={isUrdu(r.text) ? "side__text reporttext--urdu" : "side__text"} dir="auto">{r.text}</p>
          </li>
        ))}
      </ol>
      {reports.length > 8 && <p className="tiny">and {reports.length - 8} more reports</p>}
    </div>
  );
}

function Detail({ id, next }: { id: number; next: () => void }) {
  const { toast } = useSession();
  const { data, error, reload, setData } = useApi<Suggestion>(`/api/suggestions/${id}`);
  const { busy, run } = useAction(toast);
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return <Loading />;
  const s = data;

  async function opinion() {
    const out = await run("ai", () => api.post<{ verdict?: string; reason?: string; model?: string; error?: string }>(`/api/suggestions/${id}/second-opinion`));
    if (out?.verdict) setData({ ...s, ai_verdict: out.verdict, ai_reason: out.reason ?? null, ai_model: out.model ?? null });
    else if (out) toast((out as { reason?: string }).reason ?? "No AI model answered. Decide on the evidence shown.", "bad");
  }
  async function decide(accept: boolean) {
    const out = await run(accept ? "yes" : "no", () => api.post<{ status: string; case_id: string | null }>(`/api/suggestions/${id}/decision`, { accept }),
      accept ? "Accepted. The reports are joined." : "Rejected. CaseLink will not suggest this pair again.");
    if (out) next();
  }

  const leftLabel = s.kind === "new_case" ? "Some of the reports" : `${s.case_id}${s.case_title ? `: ${s.case_title}` : ""}`;
  const rightLabel = s.kind === "attach" ? `The report to add` : s.kind === "merge" ? `${s.other_case_id}${s.other_case_title ? `: ${s.other_case_title}` : ""}` : "The others";
  return (
    <article className="suggestion">
      <header>
        <h2>{title(s)}</h2>
        {s.case_title && s.kind === "attach" && <p className="small"><Link to={`/cases/${s.case_id}`}>{s.case_title}</Link></p>}
      </header>
      <div className="why">
        <div className="why__score">
          <span className="why__n">{s.score.toFixed(2)}</span>
          <span className="tiny">score out of 1. The linker never joins on these clues alone.</span>
        </div>
        <ul className="why__list">
          {s.reasons.map((r, i) => <li key={i}>{explain(r)} <span className="tiny">({r.pairs.length} report pairs, weight {r.score})</span></li>)}
        </ul>
      </div>
      {s.ai_verdict ? (
        <div className={`opinion opinion--${s.ai_verdict}`}>
          <p><strong>Second opinion: {s.ai_verdict === "same" ? "probably the same operation" : s.ai_verdict === "different" ? "probably different operations" : "not sure"}.</strong> {s.ai_reason}</p>
          <p className="tiny">From {s.ai_model}. It read the reports with phone numbers and accounts hidden. It advises; the decision is yours.</p>
        </div>
      ) : (
        <Gate role="analyst" action="ask the AI for a second opinion">
          <button className="btn btn--quiet" onClick={opinion} disabled={!!busy}>{busy === "ai" ? "Reading both sides…" : "Ask the AI for a second opinion"}</button>
        </Gate>
      )}
      <div className="sides">
        <Side label={leftLabel} reports={s.side_a ?? []} />
        <Side label={rightLabel} reports={s.side_b ?? []} />
      </div>
      {s.status === "pending" ? (
        <Gate role="analyst" action="decide this suggestion">
          <div className="decide decide--sticky">
            <button className="btn btn--primary" onClick={() => decide(true)} disabled={!!busy}>{busy === "yes" ? "Joining…" : "Accept: same operation"}</button>
            <button className="btn" onClick={() => decide(false)} disabled={!!busy}>{busy === "no" ? "Saving…" : "Reject: keep them apart"}</button>
          </div>
        </Gate>
      ) : (
        <p className="notice">{s.status === "accepted" ? "Accepted" : "Rejected"} by {person(s.decided_by)} on {dayShort(s.decided_at)}.</p>
      )}
    </article>
  );
}

export default function Suggestions() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") || "pending";
  const navigate = useNavigate();
  const list = useApi<{ suggestions: Suggestion[] }>(`/api/suggestions?status=${status}`);
  const rows = list.data?.suggestions ?? [];
  const current = id ? Number(id) : rows[0]?.id;

  useEffect(() => {
    if (!id && rows[0] && window.matchMedia("(min-width: 1100px)").matches) navigate(`/suggestions/${rows[0].id}?status=${status}`, { replace: true });
  }, [id, rows, navigate, status]);

  const next = () => {
    const i = rows.findIndex((r) => r.id === current);
    const after = rows[i + 1] ?? rows[i - 1];
    list.reload();
    navigate(after ? `/suggestions/${after.id}?status=${status}` : "/suggestions");
  };

  return (
    <div>
      <PageHead title="Suggestions" lead="Weak clues the linker will not act on by itself: similar agency names, abbreviations, spelling variants. Read both sides and decide." />
      <div className="chips" role="group" aria-label="Show">
        {[["pending", "Waiting"], ["accepted", "Accepted"], ["rejected", "Rejected"]].map(([k, label]) => (
          <button key={k} className={status === k ? "chip chip--on" : "chip"} aria-pressed={status === k} onClick={() => setParams({ status: k })}>{label}</button>
        ))}
      </div>
      {list.error && <ErrorBox error={list.error} retry={list.reload} />}
      {!list.data ? <Loading /> : rows.length === 0 && !id ? (
        <Empty>{status === "pending" ? "Nothing is waiting. New reports bring new suggestions." : "None yet."}</Empty>
      ) : (
        <div className="split">
          <ol className="split__list">
            {rows.map((s) => (
              <li key={s.id}>
                <Link to={`/suggestions/${s.id}?status=${status}`} className={s.id === current ? "sugrow sugrow--on" : "sugrow"} aria-current={s.id === current ? "true" : undefined}>
                  <span className="sugrow__title">{title(s)}</span>
                  <span className="tiny">{s.case_title ?? `${s.report_ids.length} reports`}</span>
                  <span className="sugrow__score">{s.score.toFixed(2)}{s.ai_verdict ? `, AI: ${s.ai_verdict}` : ""}</span>
                </Link>
              </li>
            ))}
          </ol>
          <div className="split__detail">{current ? <Detail key={current} id={current} next={next} /> : null}</div>
        </div>
      )}
    </div>
  );
}
