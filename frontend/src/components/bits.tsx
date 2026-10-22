import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { onWaking, type Role } from "../api";
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

export function WakingNotice() {
  const [waking, setWaking] = useState(false);
  useEffect(() => onWaking(setWaking), []);
  if (!waking) return null;
  return (
    <div className="waking" role="status">
      <span className="loading__dot" aria-hidden />
      The demo server is waking up. Free hosting puts it to sleep after 15 quiet minutes, so the first page takes about a minute.
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
