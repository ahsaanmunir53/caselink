import { Link } from "react-router-dom";

import { PageHead } from "../components/bits";
import { useSession } from "../lib/session";
import { useApi } from "../lib/useApi";

const STAGES: [string, string][] = [
  ["Reports arrive", "From Hoshiyar (scam messages people check), Pardes Guard (overseas job offers) and police desks. Typed, uploaded, or pulled as STIX."],
  ["Identifiers are read", "Rules find phone and wallet numbers, IBANs (checksum tested), websites, emails, licence numbers, handles and agency names, whatever the format. An AI may suggest more; the rules check each one."],
  ["Reports are linked", "Two reports that share a strong identifier join automatically. Similar agency names, abbreviations and spellings only become suggestions. Numbers shared by too many reports, and official helplines, are ignored."],
  ["A person reviews", "The writer agent drafts a summary in which every sentence cites reports. An analyst approves, rejects or asks for a new draft. The graph pauses and waits for that decision."],
  ["A second person confirms", "Someone other than the approver confirms the case before it can be referred or exported."],
  ["The case goes out", "As a printable referral (FIA, Bureau of Emigration, freeze requests to banks and wallets), a STIX 2.1 bundle, or a CSV of identifiers. Every step is in the audit log."],
];

const AGENTS: [string, string][] = [
  ["Linker", "Rules, not AI. Joins on strong identifiers and proposes cases."],
  ["Writer", "Drafts the cited case summary. Sentences the cited reports do not support are dropped."],
  ["Adjudicator", "Gives a second opinion on a suggestion, reading both sides with numbers hidden."],
  ["Translator", "Turns Urdu and Roman Urdu reports into English, marked as machine translation."],
  ["Extractor", "Looks for identifiers the rules missed. Its finds are re-checked by the rules."],
  ["Assistant", "Answers questions using search tools, and must cite what the tools returned."],
];

export default function About() {
  const { health } = useSession();
  const privacy = useApi<{ points: string[] }>("/api/privacy");
  return (
    <div className="narrow">
      <PageHead title="About CaseLink" lead="A desk for fraud analysts: it joins scattered complaints into cases, so one agency or one wallet behind fifty victims shows up as one case instead of fifty files." />
      <section className="panel">
        <h2>How a report becomes a case</h2>
        <ol className="pipeline">
          {STAGES.map(([t, d]) => <li key={t}><strong>{t}</strong><span>{d}</span></li>)}
        </ol>
      </section>
      <section className="panel">
        <h2>AI suggests, rules and people decide</h2>
        <dl className="agents">
          {AGENTS.map(([n, d]) => <div key={n}><dt>{n}</dt><dd>{d}</dd></div>)}
        </dl>
        <p className="small">
          {health?.llm ? `Models in use, in order of preference: ${health.model}. When one is rate-limited or down, the next one answers.` : "No AI key is set on this server, so the agents fall back to templates and search. Everything still works; summaries are plainer."}
          {" "}Agents run as LangGraph graphs. Review drafts are checkpointed in the database, so a draft waiting for an analyst survives a restart.
        </p>
      </section>
      <section className="panel">
        <h2>Privacy and safety</h2>
        <ul className="steps">{(privacy.data?.points ?? []).map((p) => <li key={p}>{p}</li>)}</ul>
        <p className="small">Read access is open in this demo because the data is invented. A real deployment switches demo mode off, so every page needs a login.</p>
      </section>
      <section className="panel">
        <h2>For other tools</h2>
        <p className="small">
          CaseLink runs an MCP server with read-only tools (list cases, open a case, search reports, ask), so another AI assistant can query the cases without being able to change them.
          Confirmed cases export as STIX 2.1 for threat-intelligence platforms. See the <Link to="/quality">evaluation</Link> for how well linking works on the demo data.
        </p>
        <p className="tiny">Version {health?.version ?? "?"}, storage {health?.storage ?? "?"}, four-eyes rule {health?.four_eyes ? "on" : "off"}.</p>
      </section>
    </div>
  );
}
