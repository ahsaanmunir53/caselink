import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import { useEffect, useMemo, useRef, useState } from "react";

import type { GraphData, GraphNode } from "../api";
import { ENTITY_LABEL, FAMILY_LABEL, family, moneyShort, dayShort } from "../lib/format";

type N = GraphNode & SimulationNodeDatum & { r: number };
type L = SimulationLinkDatum<N>;

function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

function shape(ctx: CanvasRenderingContext2D, n: N) {
  const { x = 0, y = 0, r } = n;
  ctx.beginPath();
  if (n.type === "report") {
    ctx.arc(x, y, r, 0, Math.PI * 2);
    return;
  }
  const fam = family(n.kind);
  if (fam === "numbers") {
    const s = r * 0.9;
    ctx.roundRect(x - s, y - s, s * 2, s * 2, 3);
  } else if (fam === "online") {
    ctx.moveTo(x, y - r * 1.15);
    ctx.lineTo(x + r * 1.15, y);
    ctx.lineTo(x, y + r * 1.15);
    ctx.lineTo(x - r * 1.15, y);
    ctx.closePath();
  } else {
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI / 3) * i + Math.PI / 6;
      const px = x + r * 1.05 * Math.cos(a);
      const py = y + r * 1.05 * Math.sin(a);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
  }
}

export function Legend({ help, flat = true }: { help: string; flat?: boolean }) {
  return (
    <>
      <ul className="legend" aria-label="Legend">
        <li><span className="key key--report" aria-hidden />Report</li>
        {(["numbers", "online", "names"] as const).map((f) => (
          <li key={f}><span className={`key key--${f}`} aria-hidden />{FAMILY_LABEL[f]}</li>
        ))}
        {flat && <li><span className="key key--bridge" aria-hidden />Bridge identifier</li>}
        {flat && <li><span className="key key--watch" aria-hidden />On the watchlist</li>}
      </ul>
      <p className="graph__help">{help}</p>
    </>
  );
}

export interface GraphProps {
  data: GraphData;
  onReport?: (id: string) => void;
  onEntity?: (entityId: number) => void;
  height?: number;
}

export default function NetworkGraph({ data, onReport, onEntity, height = 440 }: GraphProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(700);
  const [hover, setHover] = useState<{ n: N; x: number; y: number } | null>(null);
  const view = useRef({ k: 1, x: 0, y: 0 });
  const hoverId = useRef<string | null>(null);
  const draw = useRef<() => void>(() => {});

  const { nodes, links, neighbours } = useMemo(() => {
    const nodes: N[] = data.nodes.map((n) => ({
      ...n,
      r: n.type === "report" ? 5 : Math.min(16, 6 + Math.sqrt(n.reports ?? 1) * 2.2),
    }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const links: L[] = data.edges.filter((e) => byId.has(e.source) && byId.has(e.target)).map((e) => ({ source: e.source, target: e.target }));
    const neighbours = new Map<string, Set<string>>();
    for (const e of data.edges) {
      if (!neighbours.has(e.source)) neighbours.set(e.source, new Set());
      if (!neighbours.has(e.target)) neighbours.set(e.target, new Set());
      neighbours.get(e.source)!.add(e.target);
      neighbours.get(e.target)!.add(e.source);
    }
    return { nodes, links, neighbours };
  }, [data]);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, Math.floor(e.contentRect.width))));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    el.width = width * dpr;
    el.height = height * dpr;
    el.style.width = `${width}px`;
    el.style.height = `${height}px`;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const sim = forceSimulation<N>(nodes)
      .force("link", forceLink<N, L>(links).id((d) => d.id).distance((l) => ((l.target as N).type === "entity" && ((l.target as N).reports ?? 0) > 6 ? 70 : 45)).strength(0.6))
      .force("charge", forceManyBody<N>().strength((d) => (d.type === "entity" ? -260 : -70)))
      .force("collide", forceCollide<N>().radius((d) => d.r + 4))
      .force("x", forceX(0).strength(0.05))
      .force("y", forceY(0).strength(0.07));

    function paint() {
      if (!ctx) return;
      const colours = {
        ink: css("--ink"), muted: css("--ink-3"), line: css("--graph-line"), surface: css("--surface"),
        report: css("--graph-report"), numbers: css("--fam-numbers"), online: css("--fam-online"), names: css("--fam-names"),
        bridge: css("--ink"), watch: css("--danger"),
      };
      const { k, x: tx, y: ty } = view.current;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.translate(width / 2 + tx, height / 2 + ty);
      ctx.scale(k, k);
      const focus = hoverId.current;
      const near = focus ? neighbours.get(focus) ?? new Set<string>() : null;
      const lit = (id: string) => !near || id === focus || near.has(id);

      ctx.lineWidth = 1 / k;
      for (const l of links) {
        const s = l.source as N;
        const t = l.target as N;
        const on = !near || s.id === focus || t.id === focus;
        ctx.strokeStyle = colours.line;
        ctx.globalAlpha = on ? (near ? 0.9 : 0.55) : 0.08;
        ctx.beginPath();
        ctx.moveTo(s.x ?? 0, s.y ?? 0);
        ctx.lineTo(t.x ?? 0, t.y ?? 0);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      for (const n of nodes) {
        ctx.globalAlpha = lit(n.id) ? 1 : 0.15;
        shape(ctx, n);
        ctx.fillStyle = n.type === "report" ? colours.report : colours[family(n.kind)];
        ctx.fill();
        ctx.lineWidth = 2 / k;
        ctx.strokeStyle = colours.surface;
        ctx.stroke();
        if (n.bridge) {
          ctx.beginPath();
          ctx.arc(n.x ?? 0, n.y ?? 0, n.r + 5, 0, Math.PI * 2);
          ctx.lineWidth = 2 / k;
          ctx.strokeStyle = colours.bridge;
          ctx.setLineDash([3 / k, 3 / k]);
          ctx.stroke();
          ctx.setLineDash([]);
        }
        if (n.watched) {
          ctx.beginPath();
          ctx.arc((n.x ?? 0) + n.r, (n.y ?? 0) - n.r, 3.5, 0, Math.PI * 2);
          ctx.fillStyle = colours.watch;
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
      ctx.font = `${12 / Math.max(1, k * 0.9)}px "Atkinson Hyperlegible Next", system-ui, sans-serif`;
      ctx.textBaseline = "middle";
      // Labels: the focused node first, then the most-reported identifiers; skip any that would overlap one already drawn.
      const placed: [number, number, number, number][] = [];
      const fontPx = 12 / Math.max(1, k * 0.9);
      const order = [...nodes].sort((a, b) => (b.id === focus ? 1 : 0) - (a.id === focus ? 1 : 0) || (b.reports ?? 0) - (a.reports ?? 0));
      for (const n of order) {
        const show = n.type === "entity" ? (n.reports ?? 0) >= 3 || n.bridge || n.money || n.id === focus : n.id === focus;
        if (!show || !lit(n.id)) continue;
        const text = n.type === "entity" ? `${n.money ? "Rs " : ""}${n.label}` : n.label;
        const tx2 = (n.x ?? 0) + n.r + 6;
        const ty2 = n.y ?? 0;
        const w = ctx.measureText(text).width;
        const box: [number, number, number, number] = [tx2 - 2, ty2 - fontPx * 0.7, tx2 + w + 2, ty2 + fontPx * 0.7];
        if (n.id !== focus && placed.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) continue;
        placed.push(box);
        ctx.lineWidth = 4 / k;
        ctx.strokeStyle = colours.surface;
        ctx.strokeText(text, tx2, ty2);
        ctx.fillStyle = n.type === "entity" ? colours.ink : colours.muted;
        ctx.fillText(text, tx2, ty2);
      }
    }
    draw.current = paint;

    if (reduced) {
      sim.stop();
      for (let i = 0; i < 300; i++) sim.tick();
      paint();
    } else {
      sim.on("tick", paint);
    }

    // Fit the drawing once the layout settles.
    const fit = () => {
      const xs = nodes.map((n) => n.x ?? 0);
      const ys = nodes.map((n) => n.y ?? 0);
      const w = Math.max(...xs) - Math.min(...xs) + 80;
      const h = Math.max(...ys) - Math.min(...ys) + 60;
      const k = Math.min(2, Math.max(0.3, Math.min(width / w, height / h)));
      view.current = { k, x: -((Math.max(...xs) + Math.min(...xs)) / 2) * k, y: -((Math.max(...ys) + Math.min(...ys)) / 2) * k };
      paint();
    };
    if (reduced) fit();
    else sim.on("end", fit);
    const early = setTimeout(fit, 900);

    // Pointer: hover, drag a node, pan the background, wheel to zoom.
    const toWorld = (ev: PointerEvent | WheelEvent) => {
      const rect = el.getBoundingClientRect();
      const { k, x, y } = view.current;
      return { wx: (ev.clientX - rect.left - width / 2 - x) / k, wy: (ev.clientY - rect.top - height / 2 - y) / k, sx: ev.clientX - rect.left, sy: ev.clientY - rect.top };
    };
    const hit = (wx: number, wy: number) => {
      let best: N | null = null;
      let bestD = Infinity;
      for (const n of nodes) {
        const d = Math.hypot((n.x ?? 0) - wx, (n.y ?? 0) - wy);
        if (d < Math.max(12 / view.current.k, n.r + 6) && d < bestD) {
          best = n;
          bestD = d;
        }
      }
      return best;
    };
    let drag: { n: N | null; sx: number; sy: number; vx: number; vy: number; moved: boolean } | null = null;
    const down = (ev: PointerEvent) => {
      const { wx, wy, sx, sy } = toWorld(ev);
      const n = hit(wx, wy);
      drag = { n, sx, sy, vx: view.current.x, vy: view.current.y, moved: false };
      el.setPointerCapture(ev.pointerId);
      if (n && !reduced) {
        n.fx = n.x;
        n.fy = n.y;
        sim.alphaTarget(0.2).restart();
      }
    };
    const move = (ev: PointerEvent) => {
      const { wx, wy, sx, sy } = toWorld(ev);
      if (drag) {
        if (Math.hypot(sx - drag.sx, sy - drag.sy) > 3) drag.moved = true;
        if (drag.n) {
          drag.n.fx = wx;
          drag.n.fy = wy;
          if (reduced) {
            drag.n.x = wx;
            drag.n.y = wy;
            paint();
          }
        } else {
          view.current.x = drag.vx + (sx - drag.sx);
          view.current.y = drag.vy + (sy - drag.sy);
          paint();
        }
        return;
      }
      const n = hit(wx, wy);
      const id = n?.id ?? null;
      if (id !== hoverId.current) {
        hoverId.current = id;
        paint();
      }
      setHover(n ? { n, x: sx, y: sy } : null);
      el.style.cursor = n ? "pointer" : "grab";
    };
    const up = (ev: PointerEvent) => {
      if (!drag) return;
      const { n, moved } = drag;
      if (n) {
        n.fx = null;
        n.fy = null;
        sim.alphaTarget(0);
        if (!moved) {
          if (n.type === "report") onReport?.(n.id);
          else onEntity?.(Number(n.id.slice(1)));
        }
      }
      drag = null;
      el.releasePointerCapture(ev.pointerId);
    };
    const leave = () => {
      hoverId.current = null;
      setHover(null);
      paint();
    };
    const wheel = (ev: WheelEvent) => {
      if (!ev.ctrlKey && !ev.metaKey && !el.matches(":focus")) return;
      ev.preventDefault();
      const { sx, sy } = toWorld(ev);
      const v = view.current;
      const k = Math.min(4, Math.max(0.25, v.k * (ev.deltaY < 0 ? 1.12 : 1 / 1.12)));
      const cx = sx - width / 2;
      const cy = sy - height / 2;
      v.x = cx - ((cx - v.x) * k) / v.k;
      v.y = cy - ((cy - v.y) * k) / v.k;
      v.k = k;
      paint();
    };
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointerleave", leave);
    el.addEventListener("wheel", wheel, { passive: false });
    const scheme = window.matchMedia("(prefers-color-scheme: dark)");
    const recolour = () => paint();
    scheme.addEventListener("change", recolour);
    window.addEventListener("caselink:theme", recolour);
    return () => {
      clearTimeout(early);
      sim.stop();
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointerleave", leave);
      el.removeEventListener("wheel", wheel);
      scheme.removeEventListener("change", recolour);
      window.removeEventListener("caselink:theme", recolour);
    };
  }, [nodes, links, neighbours, width, height, onReport, onEntity]);

  const zoom = (f: number) => {
    view.current.k = Math.min(4, Math.max(0.25, view.current.k * f));
    view.current.x *= f;
    view.current.y *= f;
    draw.current();
  };

  const entities = nodes.filter((n) => n.type === "entity").length;
  const reports = nodes.length - entities;
  return (
    <div className="graph" ref={wrap}>
      <canvas ref={canvas} tabIndex={0} aria-label={`Network of ${reports} reports and the ${entities} identifiers they share. The same identifiers are listed under Key identifiers.`} />
      <div className="graph__zoom">
        <button className="iconbtn" onClick={() => zoom(1.25)} aria-label="Zoom in">+</button>
        <button className="iconbtn" onClick={() => zoom(0.8)} aria-label="Zoom out">−</button>
      </div>
      {hover && (
        <div className="tip tip--graph" style={{ left: hover.x, top: hover.y - 14 }}>
          {hover.n.type === "report" ? (
            <>
              <strong>{hover.n.id}</strong>
              <span>{dayShort(hover.n.date)}{hover.n.city ? `, ${hover.n.city}` : ""}{hover.n.amount ? `, ${moneyShort(hover.n.amount)} lost` : ""}</span>
            </>
          ) : (
            <>
              <strong>{hover.n.label}</strong>
              <span>{ENTITY_LABEL[hover.n.kind] ?? hover.n.kind}, in {hover.n.reports} reports{hover.n.bridge ? ". Bridge: the case splits without it" : ""}{hover.n.money ? ". Victims paid into it" : ""}</span>
            </>
          )}
        </div>
      )}
      <Legend help="Drag a dot to move it, drag the background to pan, and hold Ctrl while scrolling to zoom. Click a report to read it, or an identifier to see every report it appears in." />
    </div>
  );
}
