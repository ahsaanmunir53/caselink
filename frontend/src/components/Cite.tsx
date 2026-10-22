import { useState } from "react";

import type { Report } from "../api";
import { dayShort, moneyShort } from "../lib/format";

/** A citation: the report id, with the report itself one hover or focus away. */
export function Cite({ id, report, onOpen }: { id: string; report?: Report; onOpen?: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="cite" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button className="cite__id" onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onClick={() => onOpen?.(id)}
              aria-describedby={open && report ? `cite-${id}` : undefined}>
        {id}
      </button>
      {open && report && (
        <span className="cite__pop" role="tooltip" id={`cite-${id}`}>
          <span className="cite__meta">{dayShort(report.received_at)}{report.city ? `, ${report.city}` : ""}{report.amount ? `, ${moneyShort(report.amount)}` : ""}</span>
          <span className="cite__text">{report.text.slice(0, 220)}{report.text.length > 220 ? "…" : ""}</span>
        </span>
      )}
    </span>
  );
}

export function CitedSentences({ sentences, reports, onOpen }: {
  sentences: { text: string; cites: string[] }[]; reports: Map<string, Report>; onOpen?: (id: string) => void;
}) {
  return (
    <ul className="cited">
      {sentences.map((s, i) => (
        <li key={i}>
          <span>{s.text}</span>{" "}
          <span className="cited__refs">
            {s.cites.slice(0, 6).map((c) => <Cite key={c} id={c} report={reports.get(c)} onOpen={onOpen} />)}
            {s.cites.length > 6 && <span className="tiny">and {s.cites.length - 6} more</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}
