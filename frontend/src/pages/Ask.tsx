import { Fragment, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, type AskResult } from "../api";
import { ErrorBox, Loading, PageHead } from "../components/bits";

const EXAMPLES = [
  "Which agencies promised jobs in Saudi Arabia, and how much did victims lose?",
  "Are there reports about fake BISP payments from Mardan?",
  "Which wallet received the most money in the parcel fee scam?",
  "What do the Romania work permit reports have in common?",
];

function withLinks(text: string): ReactNode[] {
  const parts = text.split(/(\[(?:R-\d{4,}|C-\d{3,})\])/g);
  return parts.map((p, i) => {
    const m = p.match(/^\[((R|C)-\d+)\]$/);
    if (!m) return <Fragment key={i}>{p}</Fragment>;
    return <Link key={i} className="cite__id" to={m[2] === "R" ? `/reports/${m[1]}` : `/cases/${m[1]}`}>{m[1]}</Link>;
  });
}

export default function Ask() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [result, setResult] = useState<AskResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const asked = useRef<string | null>(null);

  async function ask(question: string) {
    if (question.trim().length < 3) return;
    asked.current = question;
    setBusy(true);
    setError(null);
    setParams({ q: question }, { replace: true });
    try {
      setResult(await api.post<AskResult>("/api/ask", { question }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const fromUrl = params.get("q");
  useEffect(() => {
    // A question in the address (from the Ctrl K palette, a shared link, or a reload) is asked once.
    if (fromUrl && fromUrl !== asked.current) {
      setQ(fromUrl);
      ask(fromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromUrl]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    ask(q);
  };

  return (
    <div className="narrow">
      <PageHead title="Ask the cases" lead="Ask in plain words. The assistant searches the reports and cases with its tools, and must cite a report or case for every fact. Citations to things its tools never returned are removed." />
      <form className="ask" onSubmit={submit}>
        <textarea rows={2} value={q} onChange={(e) => setQ(e.target.value)} maxLength={600} placeholder="For example: which numbers appear in both the Gulf Star and Doha Link reports?" aria-label="Your question"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q); } }} />
        <button className="btn btn--primary" disabled={busy || q.trim().length < 3}>{busy ? "Looking…" : "Ask"}</button>
      </form>
      {!result && !busy && (
        <ul className="examples">
          {EXAMPLES.map((x) => <li key={x}><button className="linkbtn" onClick={() => { setQ(x); ask(x); }}>{x}</button></li>)}
        </ul>
      )}
      {busy && <Loading label="Searching the reports" />}
      {error && <ErrorBox error={error} />}
      {result && !busy && (
        <section className="panel answer">
          <p className="answer__text">{withLinks(result.answer)}</p>
          {result.note && <p className="notice">{result.note}</p>}
          <p className="tiny">
            {result.source === "ai" ? `Answered by ${result.model}` : "No AI model answered, so these are the closest search results"}.
            {result.grounded ? ` ${result.citations.length} citations checked against what the tools returned.` : " The answer cites nothing, so treat it with care."}
            {result.removed_citations?.length ? ` Removed ${result.removed_citations.length} citation${result.removed_citations.length > 1 ? "s" : ""} the tools never returned: ${result.removed_citations.join(", ")}.` : ""}
          </p>
          {result.tools.length > 0 && (
            <details className="disclosure">
              <summary>What the assistant looked up</summary>
              <ol className="small">
                {result.tools.map((t, i) => <li key={i}>{t.tool === "search" ? "Searched reports for" : t.tool === "cases" ? "Listed cases" : "Opened case"} {Object.values(t.args).filter(Boolean).map((v) => `“${String(v)}”`).join(", ")}</li>)}
              </ol>
            </details>
          )}
        </section>
      )}
    </div>
  );
}
