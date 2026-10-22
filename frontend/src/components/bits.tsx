import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { onWaking, probeHealth, type Role } from "../api";
import { STATUS_HINT, STATUS_LABEL, day, person } from "../lib/format";
import { useSession } from "../lib/session";

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`status status--${status}`} title={STATUS_HINT[status]}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** Traffic Light Protocol marking, drawn the way FIRST specifies: coloured text on black. */
export function Tlp({ value = "TLP:AMBER" }: { value?: string }) {
  const level = value.replace("TLP:", "").toLowerCase().replace("+strict", "-strict");
  return <span className={`tlp tlp--${level}`} title="Traffic Light Protocol: share within your organisation and with clients who need to know.">{value}</span>;
}

export function Priority({ value }: { value: number }) {
  const band = value >= 85 ? "high" : value >= 60 ? "mid" : "low";
  return (
    <span className={`priority priority--${band}`} title="Priority from victims, money lost and how recent the reports are (0 to 100).">
      <span className="priority__track" aria-hidden><span className="priority__bar" style={{ width: `${Math.max(4, value)}%` }} /></span>
      <span className="priority__n">{value}</span>
    </span>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return <div className="loading" role="status"><span className="loading__dot" aria-hidden />{label}…</div>;
}

export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <div className="notice notice--bad" role="alert">
      <p>{error}</p>
      {retry && <button className="btn btn--quiet" onClick={retry}>Try again</button>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function CaseRef({ id, title }: { id: string; title?: string | null }) {
  return (
    <Link className="ref" to={`/cases/${id}`} title={title ?? undefined}>
      <span className="id">{id}</span>
      {title && <span className="ref__title">{title}</span>}
    </Link>
  );
}

export function ReportRef({ id }: { id: string }) {
  return <Link className="id id--link" to={`/reports/${id}`}>{id}</Link>;
}

export function Signed({ verb, who, at }: { verb: string; who: string | null; at?: string | null }) {
  if (!who) return null;
  return (
    <span className="signed">
      <span className="signed__initial" aria-hidden>{person(who).charAt(0)}</span>
      {verb} by {person(who)}{at ? ` on ${day(at)}` : ""}
    </span>
  );
}

const ROLE_NAME: Record<Role, string> = { viewer: "a viewer", analyst: "an analyst", supervisor: "a supervisor" };

/** Shows the children only to people with the role; others see how to get it. */
export function Gate({ role, action, children }: { role: Role; action: string; children: ReactNode }) {
  const { user, can } = useSession();
  if (can(role)) return <>{children}</>;
  return (
    <p className="gate">
      {user ? `You are signed in as ${ROLE_NAME[user.role]}. ` : ""}
      <Link to="/sign-in">Sign in as {ROLE_NAME[role]}</Link> to {action}.
    </p>
  );
}

/** Bottom bar while the free Render server wakes up, with a running count of seconds. */
export function WakingNotice() {
  const [state, setState] = useState<"hidden" | "waking" | "ready" | "failed">("hidden");
  const [seconds, setSeconds] = useState(0);
  const [since, setSince] = useState<number | null>(null);

  useEffect(() => {
    let hide: ReturnType<typeof setTimeout> | undefined;
    const off = onWaking((waking) => {
      clearTimeout(hide);
      if (waking) {
        setSince((s) => s ?? Date.now() - 3000);
        setState("waking");
      } else {
        setSince(null);
        setState((st) => (st === "waking" ? "ready" : st));
        hide = setTimeout(() => setState((st) => (st === "ready" ? "hidden" : st)), 2500);
      }
    });
    probeHealth(3000).then((ok) => !ok && setState("failed"));
    return () => {
      off();
      clearTimeout(hide);
    };
  }, []);

  useEffect(() => {
    if (state !== "waking" || since === null) return;
    const tick = () => setSeconds(Math.round((Date.now() - since) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [state, since]);

  if (state === "hidden") return null;
  return (
    <div className={`wakebar wakebar--${state}`} role="status" aria-live="polite">
      {state === "waking" && (
        <>
          <span className="loading__dot" aria-hidden />
          <span className="wakebar__text">Waking up the free server. Render's free plan puts it to sleep after 15 quiet minutes; it is back in 30 to 60 seconds.</span>
          <span className="wakebar__secs" aria-hidden>{seconds}s</span>
        </>
      )}
      {state === "ready" && <span className="wakebar__text">The server is awake.</span>}
      {state === "failed" && (
        <>
          <span className="wakebar__text">The server is not answering. Check your connection, then try again.</span>
          <button className="btn btn--small" onClick={() => {
            setState("hidden");
            probeHealth(3000).then((ok) => !ok && setState("failed"));
          }}>Try again</button>
        </>
      )}
    </div>
  );
}

export function SyntheticBanner() {
  return (
    <p className="synthetic">
      Demo data. Every report, person, phone number, account and website here is invented.
    </p>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function PageHead({ title, lead, children }: { title: string; lead?: ReactNode; children?: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · CaseLink`;
  }, [title]);
  return (
    <header className="pagehead">
      <div>
        <h1>{title}</h1>
        {lead && <p className="lead">{lead}</p>}
      </div>
      {children && <div className="pagehead__actions">{children}</div>}
    </header>
  );
}
