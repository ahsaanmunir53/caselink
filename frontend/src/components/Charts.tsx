import { useEffect, useRef, useState, type ReactNode } from "react";

import { compact, dayShort, moneyShort, toDate } from "../lib/format";

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

/** A chart with a title, a way to read it as a table, and the chart itself. */
export function ChartFrame({ title, note, table, children }: { title: string; note?: string; table: [string, string][]; children: ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className="chart">
      <figcaption className="chart__head">
        <span className="chart__title">{title}</span>
        <button className="linkbtn" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
          {asTable ? "Show chart" : "Show table"}
        </button>
      </figcaption>
      {note && <p className="chart__note">{note}</p>}
      {asTable ? (
        <table className="table table--compact">
          <tbody>{table.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td className="num">{v}</td></tr>)}</tbody>
        </table>
      ) : children}
    </figure>
  );
}

interface Tip { x: number; y: number; value: string; label: string }

function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null;
  return (
    <div className="tip" style={{ left: tip.x, top: tip.y }} role="presentation">
      <strong>{tip.value}</strong>
      <span>{tip.label}</span>
    </div>
  );
}

/** Columns over time (one series). */
export function Columns({ data, label, unit = "reports" }: { data: [string, number][]; label: (k: string) => string; unit?: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  const height = 170;
  const pad = { l: 34, r: 8, t: 14, b: 24 };
  const max = niceMax(Math.max(...data.map((d) => d[1]), 1));
  const band = (width - pad.l - pad.r) / Math.max(1, data.length);
  const bar = Math.min(24, band * 0.6);
  const y = (v: number) => pad.t + (height - pad.t - pad.b) * (1 - v / max);
  const ticks = [0, max / 2, max];
  const peak = data.reduce((best, d, i) => (d[1] > data[best][1] ? i : best), 0);
  return (
    <div className="plot" ref={ref} onPointerLeave={() => setTip(null)}>
      <svg width={width} height={height} role="img" aria-label={`Columns: ${data.map(([k, v]) => `${label(k)} ${v}`).join(", ")}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={pad.l - 6} y={y(t) + 4} className="axis" textAnchor="end">{compact(t)}</text>
          </g>
        ))}
        {data.map(([k, v], i) => {
          const cx = pad.l + band * i + band / 2;
          const top = y(v);
          const h = Math.max(0, y(0) - top);
          const r = Math.min(4, h);
          const show = () => setTip({ x: cx, y: top - 8, value: `${v} ${unit}`, label: label(k) });
          return (
            <g key={k} tabIndex={0} onPointerEnter={show} onFocus={show} onBlur={() => setTip(null)} className="mark">
              <rect x={cx - band / 2} y={pad.t} width={band} height={height - pad.t - pad.b} fill="transparent" />
              <path className="bar" d={`M${cx - bar / 2},${y(0)} V${top + r} Q${cx - bar / 2},${top} ${cx - bar / 2 + r},${top} H${cx + bar / 2 - r} Q${cx + bar / 2},${top} ${cx + bar / 2},${top + r} V${y(0)} Z`} />
              {i === peak && <text x={cx} y={top - 5} className="value" textAnchor="middle">{v}</text>}
              <text x={cx} y={height - 6} className="axis" textAnchor="middle">{label(k)}</text>
            </g>
          );
        })}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

/** Ranked horizontal bars; every bar carries its value, so the list is its own table. */
export function Bars({ data, label, format = (n) => n.toLocaleString("en"), onPick, max }: {
  data: [string, number][]; label?: (k: string) => string; format?: (n: number) => string; onPick?: (k: string) => void; max?: number;
}) {
  const top = max ?? Math.max(...data.map((d) => d[1]), 1);
  return (
    <ul className="bars">
      {data.map(([k, v]) => {
        const body = (
          <>
            <span className="bars__label">{label ? label(k) : k}</span>
            <span className="bars__track"><span className="bars__fill" style={{ width: `${(v / top) * 100}%` }} /></span>
            <span className="bars__value">{format(v)}</span>
          </>
        );
        return (
          <li key={k}>
            {onPick ? <button className="bars__row" onClick={() => onPick(k)}>{body}</button> : <div className="bars__row">{body}</div>}
          </li>
        );
      })}
    </ul>
  );
}

/** Each report as a dot: when it came in, and how much was lost. */
export function Timeline({ points, onPick }: { points: { id: string; date: string; amount: number | null; city: string | null }[]; onPick?: (id: string) => void }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  if (!points.length) return null;
  const height = 190;
  const pad = { l: 58, r: 16, t: 18, b: 26 };
  const times = points.map((p) => toDate(p.date).getTime());
  let t0 = Math.min(...times);
  let t1 = Math.max(...times);
  if (t1 - t0 < 864e5) {
    t0 -= 864e5 * 3;
    t1 += 864e5 * 3;
  }
  const max = niceMax(Math.max(...points.map((p) => p.amount ?? 0), 1));
  const x = (t: number) => pad.l + ((t - t0) / (t1 - t0)) * (width - pad.l - pad.r);
  const y = (v: number) => pad.t + (height - pad.t - pad.b) * (1 - v / max);
  const months: number[] = [];
  const d = new Date(t0);
  d.setUTCDate(1);
  d.setUTCHours(0, 0, 0, 0);
  while (d.getTime() <= t1) {
    if (d.getTime() >= t0) months.push(d.getTime());
    d.setUTCMonth(d.getUTCMonth() + 1);
  }
  const biggest = points.reduce((b, p, i) => ((p.amount ?? 0) > (points[b].amount ?? 0) ? i : b), 0);
  return (
    <div className="plot" ref={ref} onPointerLeave={() => setTip(null)}>
      <svg width={width} height={height} role="img" aria-label={`${points.length} reports from ${dayShort(points[0].date)} to ${dayShort(points[points.length - 1].date)}`}>
        {[0, max / 2, max].map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={pad.l - 6} y={y(t) + 4} className="axis" textAnchor="end">{t === 0 ? "0" : moneyShort(t).replace("Rs ", "")}</text>
          </g>
        ))}
        {months.map((m) => (
          <text key={m} x={x(m)} y={height - 7} className="axis" textAnchor="middle">
            {new Date(m).toLocaleString("en-GB", { month: "short", timeZone: "UTC" })}
          </text>
        ))}
        {points.map((p, i) => {
          const cx = x(times[i]);
          const cy = y(p.amount ?? 0);
          const show = () => setTip({ x: cx, y: cy - 12, value: moneyShort(p.amount), label: `${p.id}, ${dayShort(p.date)}${p.city ? `, ${p.city}` : ""}` });
          return (
            <g key={p.id} className="mark" tabIndex={0} onPointerEnter={show} onFocus={show} onBlur={() => setTip(null)}
               onClick={() => onPick?.(p.id)} onKeyDown={(e) => e.key === "Enter" && onPick?.(p.id)}>
              <circle cx={cx} cy={cy} r={12} fill="transparent" />
              <circle cx={cx} cy={cy} r={5} className={p.amount == null ? "dot dot--none" : "dot"} />
            </g>
          );
        })}
        {points[biggest].amount ? (
          <text x={Math.min(x(times[biggest]) + 9, width - 90)} y={y(points[biggest].amount ?? 0) + 4} className="value">
            {moneyShort(points[biggest].amount)}
          </text>
        ) : null}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}
