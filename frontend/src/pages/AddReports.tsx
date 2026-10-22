import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api, type IngestResult } from "../api";
import { Gate, PageHead, ReportRef } from "../components/bits";
import { KIND_LABEL, SOURCE_SHORT, plural } from "../lib/format";
import { useSession } from "../lib/session";

const EXAMPLES = [
  {
    label: "Shares a phone number with a case",
    text: "My cousin paid Rs 120,000 to Al-Noor Overseas for a driver visa to Saudi Arabia. Their agent kept saying the protector stamp was coming. Call 0301 4170753, now switched off.",
    city: "Gujrat", destination: "Saudi Arabia", amount: 120000,
  },
  {
    label: "Only a similar agency name",
    text: "Walk-in complaint: Gulf Star Overseas Employment took PKR 95,000 for a cleaner job in Dubai and gave a fake offer letter. Victim did not keep the number.",
    city: "Sialkot", destination: "UAE", amount: 95000,
  },
  {
    label: "Roman Urdu, nothing to link",
    text: "Kisi ne WhatsApp pe kaha ke aap ka inaam nikla hai, fees bhejo. Maine 8000 bhej diye, ab block kar diya.",
    city: "Multan", destination: "", amount: 8000,
  },
];

function Outcome({ result }: { result: IngestResult }) {
  return (
    <section className="panel" aria-live="polite">
      <h2>What happened</h2>
      {result.note && <p>{result.note}</p>}
      <ul className="plain">
        {result.outcomes.map((o) => {
          const sugs = (o.suggestions as number[] | undefined) ?? [];
          const watch = (o.watchlist as string[] | undefined) ?? [];
          return (
            <li key={o.report_id}>
              <p>
                <ReportRef id={o.report_id} />{" "}
                {o.case_id ? <>joined <Link to={`/cases/${o.case_id}`}>{o.case_id}</Link> through a shared identifier{o.case_status && o.case_status !== "proposed" ? `. The case is ${o.case_status}, so its team got an alert` : ""}.</>
                  : sugs.length ? <>is not in a case yet. It is waiting in <Link to={`/suggestions/${sugs[0]}`}>{plural(sugs.length, "suggestion")}</Link> for an analyst.</>
                  : "shares nothing with other reports yet. It stays on its own until something links it."}
              </p>
              {watch.length > 0 && <p className="notice notice--bad">Watchlist: {watch.join(", ")} {watch.length > 1 ? "appear" : "appears"} in it. An alert is on the desk.</p>}
              {o.duplicate_of && <p className="notice">It reads almost the same as <ReportRef id={String(o.duplicate_of)} />, so it may be a repeat.</p>}
            </li>
          );
        })}
      </ul>
      {result.ai_extracted && result.ai_extracted.length > 0 && <p className="tiny">The AI found identifiers the rules missed in {result.ai_extracted.join(", ")}; the rules checked each one before it was kept.</p>}
    </section>
  );
}

export default function AddReports() {
  const { health, toast } = useSession();
  const [text, setText] = useState("");
  const [city, setCity] = useState("");
  const [destination, setDestination] = useState("");
  const [amount, setAmount] = useState("");
  const [source, setSource] = useState("police_desk");
  const [kind, setKind] = useState("");
  const [useAi, setUseAi] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResult | null>(null);
  const file = useRef<HTMLInputElement>(null);

  async function go<T extends IngestResult>(name: string, fn: () => Promise<T>) {
    setBusy(name);
    setResult(null);
    try {
      const out = await fn();
      setResult(out);
      toast(out.new_ids.length ? `${plural(out.new_ids.length, "report")} added and linked.` : "Nothing new to add.");
    } catch (e) {
      toast((e as Error).message, "bad");
    } finally {
      setBusy(null);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    go("one", () => api.post<IngestResult>("/api/reports", {
      use_ai: useAi,
      reports: [{
        text, source, channel: source === "police_desk" ? "walk_in" : source === "pardes_guard" ? "web_form" : "sms",
        reporter_city: city || null, destination_country: destination || null, amount_lost: amount ? Number(amount.replace(/[^\d]/g, "")) : null,
        kind: kind || null,
      }],
    }));
  }
  function upload() {
    const f = file.current?.files?.[0];
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    go("file", () => api.upload<IngestResult>("/api/reports/upload", form));
  }

  return (
    <div className="narrow">
      <PageHead title="Add reports" lead="New reports are stored, read for identifiers, and linked straight away. Strong matches join a case; weak ones become suggestions." />
      <Gate role="analyst" action="add reports">
        <section className="panel">
          <h2>Type or paste a report</h2>
          <div className="chips" role="group" aria-label="Examples">
            {EXAMPLES.map((x) => (
              <button key={x.label} className="chip" onClick={() => { setText(x.text); setCity(x.city); setDestination(x.destination); setAmount(String(x.amount)); }}>{x.label}</button>
            ))}
          </div>
          <form className="form" onSubmit={submit}>
            <label>What the victim said<textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} minLength={10} maxLength={6000} required placeholder="In English, Urdu or Roman Urdu" dir="auto" /></label>
            <div className="form__row">
              <label>Victim lives in<input value={city} onChange={(e) => setCity(e.target.value)} maxLength={64} /></label>
              <label>Promised job in<input value={destination} onChange={(e) => setDestination(e.target.value)} maxLength={64} /></label>
              <label>Amount lost (Rs)<input inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
            </div>
            <div className="form__row">
              <label>Source
                <select value={source} onChange={(e) => setSource(e.target.value)}>
                  {Object.entries(SOURCE_SHORT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
              <label>Kind of fraud
                <select value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="">Let CaseLink decide</option>
                  {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
            </div>
            <label className="check"><input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />Also let the AI look for identifiers the rules miss (numbers are hidden from it first)</label>
            <button className="btn btn--primary" disabled={!!busy || text.trim().length < 10}>{busy === "one" ? "Adding and linking…" : "Add and link"}</button>
          </form>
        </section>

        <section className="panel">
          <h2>Upload a file</h2>
          <p className="small">A JSON list of reports, JSON lines, a CSV with a <code>text</code> column, or a STIX 2.1 bundle. Up to 200 reports at a time. Optional fields: source, received_at, reporter_city, destination_country, amount_lost, kind.</p>
          <div className="actions__row">
            <input ref={file} type="file" accept=".json,.jsonl,.csv,.txt,application/json,text/csv" aria-label="Report file" />
            <button className="btn" onClick={upload} disabled={!!busy}>{busy === "file" ? "Reading…" : "Upload and link"}</button>
          </div>
        </section>

        <section className="panel">
          <h2>Pull from Hoshiyar</h2>
          <p className="small">Hoshiyar is the public scam checker. Its moderators confirm scam websites; CaseLink reads them as a STIX 2.1 feed and links them like any other report.</p>
          {health?.hoshiyar_link ? (
            <button className="btn" onClick={() => go("hoshiyar", () => api.post<IngestResult>("/api/import/hoshiyar"))} disabled={!!busy}>
              {busy === "hoshiyar" ? "Pulling…" : "Pull confirmed websites now"}
            </button>
          ) : <p className="small">This deployment is not connected to Hoshiyar. Set HOSHIYAR_API_URL and HOSHIYAR_INTEGRATION_KEY on the server to switch it on.</p>}
        </section>
      </Gate>
      {result && <Outcome result={result} />}
    </div>
  );
}
