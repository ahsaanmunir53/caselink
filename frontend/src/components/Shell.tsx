import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";

import { api } from "../api";
import { useSession } from "../lib/session";
import { SyntheticBanner, WakingNotice } from "./bits";
import CommandPalette from "./CommandPalette";

const NAV: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Desk", end: true },
  { to: "/cases", label: "Cases" },
  { to: "/suggestions", label: "Suggestions" },
  { to: "/reports", label: "Reports" },
  { to: "/identifiers", label: "Identifiers" },
  { to: "/ask", label: "Ask the cases" },
  { to: "/add", label: "Add reports" },
  { to: "/audit", label: "Audit log" },
  { to: "/quality", label: "How well it links" },
  { to: "/about", label: "About and privacy" },
];

type Theme = "system" | "light" | "dark";

function applyTheme(t: Theme) {
  const root = document.documentElement;
  if (t === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", t);
  window.dispatchEvent(new Event("caselink:theme"));
}

function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem("caselink.theme") as Theme) || "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem("caselink.theme", theme);
    } catch {
      /* fine */
    }
  }, [theme]);
  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  const label: Record<Theme, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };
  return <button className="linkbtn" onClick={() => setTheme(next[theme])}>{label[theme]}</button>;
}

export default function Shell({ children }: { children: ReactNode }) {
  const { user, signOut, health } = useSession();
  const [menu, setMenu] = useState(false);
  const [palette, setPalette] = useState(false);
  const [waiting, setWaiting] = useState<number | null>(null);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => setMenu(false), [location.pathname]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((v) => !v);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    api.get<{ pending_suggestions: number }>("/api/overview").then((o) => setWaiting(o.pending_suggestions)).catch(() => {});
  }, [location.pathname]);

  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <aside className={menu ? "rail rail--open" : "rail"}>
        <div className="rail__top">
          <Link to="/" className="wordmark" aria-label="CaseLink, home">
            <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden><rect width="32" height="32" rx="7" className="wordmark__tile" /><circle cx="10" cy="11" r="3.6" className="wordmark__hl" /><circle cx="22" cy="11" r="3.6" className="wordmark__dot" /><circle cx="16" cy="22" r="3.6" className="wordmark__dot" /><path d="M10 11 16 22 22 11" className="wordmark__line" /></svg>
            <span>CaseLink</span>
          </Link>
          <button className="rail__menu iconbtn" aria-expanded={menu} aria-controls="nav" onClick={() => setMenu((v) => !v)}>
            <span className="sr">Menu</span>
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden><path d="M2 4h14M2 9h14M2 14h14" stroke="currentColor" strokeWidth="1.8" /></svg>
          </button>
        </div>
        <nav id="nav" className="nav" aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "nav__item nav__item--on" : "nav__item")}>
              {n.label}
              {n.to === "/suggestions" && waiting ? <span className="count" aria-label={`${waiting} waiting`}>{waiting}</span> : null}
            </NavLink>
          ))}
        </nav>
        <div className="rail__foot">
          {user ? (
            <div className="whoami">
              <span className="whoami__name">{user.name}</span>
              <span className="whoami__role">{user.role.charAt(0).toUpperCase() + user.role.slice(1)}{user.demo ? ", demo account" : ""}</span>
              <button className="linkbtn" onClick={() => { signOut(); navigate("/"); }}>Sign out</button>
            </div>
          ) : (
            <Link className="btn btn--primary btn--block" to="/sign-in">Sign in</Link>
          )}
          <ThemeSwitch />
          {health && <span className="rail__status" title={health.model}>{health.llm ? "AI models connected" : "Running on rules only (no AI key)"}</span>}
        </div>
      </aside>
      <div className="main">
        <div className="topbar">
          <button className="search" onClick={() => setPalette(true)}>
            <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden><circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.6" fill="none" /><path d="m11 11 3.5 3.5" stroke="currentColor" strokeWidth="1.6" /></svg>
            <span>Find a case, report or number</span>
            <kbd>Ctrl K</kbd>
          </button>
        </div>
        <WakingNotice />
        <SyntheticBanner />
        <main id="main" tabIndex={-1}>{children}</main>
      </div>
      {palette && <CommandPalette onClose={() => setPalette(false)} />}
    </div>
  );
}
