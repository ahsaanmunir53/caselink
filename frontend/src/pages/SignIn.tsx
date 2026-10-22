import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api, type User } from "../api";
import { ErrorBox, PageHead } from "../components/bits";
import { useSession } from "../lib/session";
import { useApi } from "../lib/useApi";

const WHAT_THEY_DO: Record<string, string> = {
  "ayesha.analyst@caselink.demo": "Reviews proposed cases, decides suggestions, approves cases and writes notes.",
  "bilal.analyst@caselink.demo": "A second analyst. Sign in as Bilal to confirm a case Ayesha approved: the four-eyes rule.",
  "sana.supervisor@caselink.demo": "Everything an analyst can do, plus exporting every confirmed case as one STIX bundle.",
  "viewer@caselink.demo": "Reads cases and reports and downloads confirmed exports. Cannot change anything.",
};

export default function SignIn() {
  const { signIn, toast, user } = useSession();
  const navigate = useNavigate();
  const demo = useApi<{ users: User[] }>("/api/auth/demo-users");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function asDemo(u: User) {
    setBusy(u.email);
    try {
      const out = await api.post<{ token: string; user: User }>("/api/auth/demo", { email: u.email });
      signIn(out.token, { ...out.user, demo: true });
      toast(`Signed in as ${out.user.name}.`);
      navigate(-1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy("form");
    setError(null);
    try {
      const out = await api.post<{ token: string; user: User }>("/api/auth/login", { email, password });
      signIn(out.token, out.user);
      toast(`Signed in as ${out.user.name}.`);
      navigate("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const users = demo.data?.users ?? [];
  return (
    <div className="narrow">
      <PageHead title="Sign in" lead="Anyone can read the demo. To review cases, decide suggestions or export, sign in as one of the demo team." />
      {user && <p className="notice">You are signed in as {user.name}. Pick someone else to switch.</p>}
      {users.length > 0 && (
        <ul className="people">
          {users.map((u) => (
            <li key={u.email}>
              <button className="person" onClick={() => asDemo(u)} disabled={!!busy}>
                <span className="person__initial" aria-hidden>{u.name.charAt(0)}</span>
                <span className="person__text">
                  <span className="person__name">{u.name.replace(/ \(.*\)/, "")}<span className="person__role">{u.role}</span></span>
                  <span className="person__what">{WHAT_THEY_DO[u.email] ?? ""}</span>
                </span>
                <span className="person__go">{busy === u.email ? "Signing in…" : "Sign in"}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <details className="disclosure">
        <summary>Sign in with an email and password</summary>
        <form className="form" onSubmit={submit}>
          <label>Email<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
          <button className="btn btn--primary" disabled={busy === "form"}>{busy === "form" ? "Signing in…" : "Sign in"}</button>
        </form>
      </details>
      {error && <ErrorBox error={error} />}
    </div>
  );
}
