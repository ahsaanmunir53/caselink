import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { api, type Mention, type Report } from "../api";
import { ENTITY_LABEL, ROLE_LABEL, family, isUrdu } from "../lib/format";
import { useSession } from "../lib/session";

/** Report text with every extracted identifier marked like a highlighter on paper. */
export function Highlighted({ text, mentions }: { text: string; mentions?: Mention[] }) {
  if (!mentions?.length) return <>{text}</>;
  const spans: { start: number; end: number; m: Mention }[] = [];
  const sorted = [...mentions].sort((a, b) => b.raw.length - a.raw.length);
  const lower = text.toLowerCase();
  for (const m of sorted) {
    if (!m.raw) continue;
    // Websites are stored with a scheme added; the text may have none, or be written defanged (site[.]com).
    const bare = m.raw.toLowerCase().replace(/^https?:\/\//, "").replace(/\/$/, "");
    const needles = new Set([m.raw.toLowerCase(), bare, bare.replace(/\./g, "[.]"), bare.replace(/^www\./, "")]);
    for (const needle of needles) {
      if (needle.length < 3) continue;
      let from = 0;
      while (from < text.length) {
        const at = lower.indexOf(needle, from);
        if (at < 0) break;
        const end = at + needle.length;
        if (!spans.some((s) => at < s.end && end > s.start)) spans.push({ start: at, end, m });
        from = end;
      }
    }
  }
  spans.sort((a, b) => a.start - b.start);
  const out: ReactNode[] = [];
  let pos = 0;
  spans.forEach((s, i) => {
    if (s.start > pos) out.push(text.slice(pos, s.start));
    const fam = s.m.official ? "official" : family(s.m.kind);
    const label = s.m.official
      ? `Official ${ENTITY_LABEL[s.m.kind]?.toLowerCase() ?? s.m.kind}: not used for linking`
      : `${ENTITY_LABEL[s.m.kind] ?? s.m.kind}${ROLE_LABEL[s.m.role] && s.m.role !== s.m.kind ? `, ${ROLE_LABEL[s.m.role]}` : ""}`;
    out.push(
      <Link key={i} to={`/identifiers/${s.m.entity_id}`} className={`hl hl--${fam}`} title={label}>
        {text.slice(s.start, s.end)}
      </Link>,
    );
    pos = s.end;
  });
  if (pos < text.length) out.push(text.slice(pos));
  return <>{out}</>;
}

export function ReportBody({ report, mentions, onTranslated }: {
  report: Report; mentions?: Mention[]; onTranslated?: (text: string, model: string) => void;
}) {
  const { can, toast } = useSession();
  const [translation, setTranslation] = useState<{ text: string; model: string | null } | null>(
    report.translation ? { text: report.translation, model: report.translation_model ?? null } : null,
  );
  const [busy, setBusy] = useState(false);
  const urdu = isUrdu(report.text);
  const needsTranslation = report.language !== "en";

  async function translate() {
    setBusy(true);
    try {
      const out = await api.post<{ translation: string; model: string }>(`/api/reports/${report.id}/translate`);
      setTranslation({ text: out.translation, model: out.model });
      onTranslated?.(out.translation, out.model);
    } catch (e) {
      toast((e as Error).message, "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="reportbody">
      <p className={urdu ? "reporttext reporttext--urdu" : "reporttext"} dir={urdu ? "rtl" : "auto"} lang={urdu ? "ur" : undefined}>
        <Highlighted text={report.text} mentions={mentions} />
      </p>
      {translation ? (
        <div className="translation">
          <p className="translation__label">Machine translation into English{translation.model ? `, by ${translation.model}` : ""}. Check names and numbers against the original.</p>
          <p>{translation.text}</p>
        </div>
      ) : needsTranslation && can("analyst") ? (
        <button className="btn btn--quiet btn--small" onClick={translate} disabled={busy}>
          {busy ? "Translating…" : "Translate into English"}
        </button>
      ) : null}
    </div>
  );
}
