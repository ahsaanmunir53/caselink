import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, type CaseRow, type EntityRow } from "../api";
import { ENTITY_LABEL } from "../lib/format";

interface Item { key: string; label: string; hint: string; go: () => void }

const PAGES: [string, string][] = [
  ["Desk", "/"], ["Cases", "/cases"], ["Suggestions waiting", "/suggestions"], ["Reports", "/reports"],
  ["Identifiers", "/identifiers"], ["Watchlist", "/identifiers?watched=1"], ["Ask the cases", "/ask"], ["Add reports", "/add"],
  ["Audit log", "/audit"], ["How well it links", "/quality"], ["About and privacy", "/about"], ["Sign in", "/sign-in"],
];

let casesCache: CaseRow[] | null = null;

export default function CommandPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [cases, setCases] = useState<CaseRow[]>(casesCache ?? []);
  const [entities, setEntities] = useState<EntityRow[]>([]);
  const [active, setActive] = useState(0);

  useEffect(() => {
    input.current?.focus();
    api.get<{ cases: CaseRow[] }>("/api/cases").then((d) => setCases((casesCache = d.cases))).catch(() => {});
  }, []);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 4 || /^[RC]-\d+$/i.test(term)) {
      setEntities([]);
      return;
    }
    const t = setTimeout(() => {
      api.get<{ entities: EntityRow[] }>(`/api/entities?q=${encodeURIComponent(term)}`).then((d) => setEntities(d.entities.slice(0, 5))).catch(() => {});
    }, 220);
    return () => clearTimeout(t);
  }, [q]);

  const items = useMemo<Item[]>(() => {
    const term = q.trim().toLowerCase();
    const go = (to: string) => () => {
      navigate(to);
      onClose();
    };
    const out: Item[] = [];
    const rid = term.match(/^r-?(\d{1,4})$/);
    if (rid) out.push({ key: "r", label: `Open report R-${rid[1].padStart(4, "0")}`, hint: "Report", go: go(`/reports/R-${rid[1].padStart(4, "0")}`) });
    const cid = term.match(/^c-?(\d{1,3})$/);
    if (cid) out.push({ key: "c", label: `Open case C-${cid[1].padStart(3, "0")}`, hint: "Case", go: go(`/cases/C-${cid[1].padStart(3, "0")}`) });
    for (const c of cases) {
      if (!term || c.title.toLowerCase().includes(term) || c.id.toLowerCase() === term) {
        out.push({ key: c.id, label: `${c.id}  ${c.title}`, hint: "Case", go: go(`/cases/${c.id}`) });
      }
      if (out.length > 7) break;
    }
    for (const e of entities) out.push({ key: `e${e.id}`, label: e.display, hint: `${ENTITY_LABEL[e.kind] ?? e.kind}, ${e.reports} reports`, go: go(`/identifiers/${e.id}`) });
    for (const [label, to] of PAGES) if (!term || label.toLowerCase().includes(term)) out.push({ key: to, label, hint: "Page", go: go(to) });
    if (term.length > 2) {
      out.push({ key: "search", label: `Search reports for “${q.trim()}”`, hint: "Search", go: go(`/reports?q=${encodeURIComponent(q.trim())}`) });
      out.push({ key: "ask", label: `Ask: “${q.trim()}”`, hint: "AI answer with sources", go: go(`/ask?q=${encodeURIComponent(q.trim())}`) });
    }
    return out.slice(0, 14);
  }, [q, cases, entities, navigate, onClose]);

  useEffect(() => setActive(0), [q]);

  return (
    <div className="palette__backdrop" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Find anything" onMouseDown={(e) => e.stopPropagation()}>
        <input
          ref={input}
          className="palette__input"
          placeholder="Case title, C-004, R-0120, a phone number, or a question"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-activedescendant={items[active] ? `pi-${items[active].key}` : undefined}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            else if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(items.length - 1, a + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(0, a - 1));
            } else if (e.key === "Enter") items[active]?.go();
          }}
        />
        <ul className="palette__list" id="palette-list" role="listbox">
          {items.map((it, i) => (
            <li key={it.key} id={`pi-${it.key}`} role="option" aria-selected={i === active}
                className={i === active ? "palette__item palette__item--on" : "palette__item"}
                onMouseEnter={() => setActive(i)} onClick={it.go}>
              <span>{it.label}</span>
              <span className="palette__hint">{it.hint}</span>
            </li>
          ))}
          {!items.length && <li className="palette__empty">Nothing matches. Try a case number like C-004 or part of a phone number.</li>}
        </ul>
      </div>
    </div>
  );
}
