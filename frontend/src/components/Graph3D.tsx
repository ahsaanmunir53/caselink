// The same network in three dimensions. Loaded only when someone asks for it (three.js is large).
import { forceLink, forceManyBody, forceSimulation, forceCenter } from "d3-force-3d";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { GraphData, GraphNode } from "../api";
import { ENTITY_LABEL, family } from "../lib/format";
import { Legend } from "./NetworkGraph";

type N = GraphNode & { x?: number; y?: number; z?: number; index?: number };

function css(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

export default function Graph3D({ data, height = 440, onReport, onEntity }: {
  data: GraphData; height?: number; onReport?: (id: string) => void; onEntity?: (id: number) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{ text: string; sub: string; x: number; y: number } | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const width = el.clientWidth;
    const nodes: N[] = data.nodes.map((n) => ({ ...n }));
    const links = data.edges.map((e) => ({ source: e.source, target: e.target }));
    const sim = forceSimulation(nodes, 3)
      .force("link", forceLink(links).id((d: N) => d.id).distance(28))
      .force("charge", forceManyBody().strength((d: N) => (d.type === "entity" ? -90 : -25)))
      .force("center", forceCenter())
      .stop();
    for (let i = 0; i < 260; i++) sim.tick();

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(width, height);
    el.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("aria-label", "Three-dimensional view of the network. Drag to turn it.");
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, width / height, 1, 4000);
    const radius = Math.max(40, ...nodes.map((n) => Math.hypot(n.x ?? 0, n.y ?? 0, n.z ?? 0)));
    camera.position.set(0, 0, radius * 2.3);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.autoRotate = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    controls.autoRotateSpeed = 0.6;
    scene.add(new THREE.AmbientLight(0xffffff, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(100, 200, 300);
    scene.add(sun);

    const colour = { report: css("--graph-report"), numbers: css("--fam-numbers"), online: css("--fam-online"), names: css("--fam-names") };
    const meshes: THREE.Mesh[] = [];
    const geo = {
      report: new THREE.SphereGeometry(2.6, 16, 12),
      numbers: new THREE.BoxGeometry(7, 7, 7),
      online: new THREE.OctahedronGeometry(5.5),
      names: new THREE.CylinderGeometry(4.6, 4.6, 5, 6),
    };
    for (const n of nodes) {
      const fam = n.type === "report" ? "report" : family(n.kind);
      const mesh = new THREE.Mesh(geo[fam], new THREE.MeshLambertMaterial({ color: new THREE.Color(colour[fam]) }));
      const s = n.type === "entity" ? Math.min(2, 0.7 + Math.sqrt(n.reports ?? 1) * 0.25) : 1;
      mesh.scale.setScalar(s);
      mesh.position.set(n.x ?? 0, n.y ?? 0, n.z ?? 0);
      mesh.userData = n;
      scene.add(mesh);
      meshes.push(mesh);
    }
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const pts: number[] = [];
    for (const l of links) {
      const s = (typeof l.source === "object" ? l.source : byId.get(l.source as string)) as N | undefined;
      const t = (typeof l.target === "object" ? l.target : byId.get(l.target as string)) as N | undefined;
      if (s && t) pts.push(s.x ?? 0, s.y ?? 0, s.z ?? 0, t.x ?? 0, t.y ?? 0, t.z ?? 0);
    }
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    scene.add(new THREE.LineSegments(lineGeo, new THREE.LineBasicMaterial({ color: new THREE.Color(css("--graph-line")), transparent: true, opacity: 0.6 })));

    const ray = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let downAt = { x: 0, y: 0 };
    const pick = (ev: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
      ray.setFromCamera(mouse, camera);
      const hit = ray.intersectObjects(meshes)[0];
      return { n: hit ? (hit.object.userData as N) : null, x: ev.clientX - rect.left, y: ev.clientY - rect.top };
    };
    const move = (ev: PointerEvent) => {
      const { n, x, y } = pick(ev);
      renderer.domElement.style.cursor = n ? "pointer" : "grab";
      setTip(n ? { text: n.label, sub: n.type === "report" ? `${n.city ?? ""}` : `${ENTITY_LABEL[n.kind] ?? n.kind}, ${n.reports} reports`, x, y } : null);
    };
    const down = (ev: PointerEvent) => void (downAt = { x: ev.clientX, y: ev.clientY });
    const up = (ev: PointerEvent) => {
      if (Math.hypot(ev.clientX - downAt.x, ev.clientY - downAt.y) > 4) return;
      const { n } = pick(ev);
      if (!n) return;
      if (n.type === "report") onReport?.(n.id);
      else onEntity?.(Number(n.id.slice(1)));
    };
    renderer.domElement.addEventListener("pointermove", move);
    renderer.domElement.addEventListener("pointerdown", down);
    renderer.domElement.addEventListener("pointerup", up);
    let frame = 0;
    const loop = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(loop);
    };
    loop();
    return () => {
      cancelAnimationFrame(frame);
      controls.dispose();
      renderer.dispose();
      Object.values(geo).forEach((g) => g.dispose());
      lineGeo.dispose();
      renderer.domElement.remove();
    };
  }, [data, height, onReport, onEntity]);

  return (
    <div className="graph">
      <div className="graph--3d" ref={wrap} style={{ height, position: "relative" }}>
        {tip && <div className="tip tip--graph" style={{ left: tip.x, top: tip.y - 14 }}><strong>{tip.text}</strong><span>{tip.sub}</span></div>}
      </div>
      <Legend flat={false} help="Drag to turn the network, scroll to zoom. Click a report to read it, or an identifier to open it. The flat view marks bridges and watched identifiers." />
    </div>
  );
}
