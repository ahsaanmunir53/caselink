// Talking to the CaseLink API. Types mirror the backend's JSON.

export const API_URL = ((import.meta.env.VITE_API_URL as string | undefined) || "").replace(/\/$/, "");

export type Role = "viewer" | "analyst" | "supervisor";
export type CaseStatus = "proposed" | "open" | "investigating" | "referred" | "closed" | "rejected" | "merged";

export interface User { email: string; name: string; role: Role; demo?: boolean }

export interface CaseRow {
  id: string; title: string; status: CaseStatus; kind: string; priority: number;
  created_at: string; updated_at: string;
  approved_by: string | null; approved_at: string | null;
  confirmed_by: string | null; confirmed_at: string | null;
  assignee: string | null; tlp: string; merged_into: string | null;
  reports?: number; loss?: number; last_report?: string | null; pending_suggestions?: number;
}

export interface Report {
  id: string; source: string; channel: string; received_at: string; language: string;
  city: string | null; destination: string | null; amount: number | null; currency: string;
  kind: string; case_id: string | null; pinned: boolean; synthetic: boolean; duplicate_of: string | null;
  text: string; translation?: string | null; translation_model?: string | null;
  ai_extraction?: Record<string, unknown> | null; role?: string;
}

export interface Mention { raw: string; kind: string; entity_id: number; role: string; official: boolean }

export interface CaseEntity {
  id: number; kind: string; value: string; display: string; official: boolean; watched: boolean; valid: boolean;
  reports: string[]; roles: string[]; sources: string[];
}

export interface MoneyRow {
  entity_id: number; kind: string; display: string; value: string; reports: number; total: number; report_ids: string[];
}

export interface Sentence { text: string; cites: string[] }
export interface Summary {
  sentences: Sentence[]; modus_operandi?: string; next_steps?: string[]; source?: string; model?: string | null;
  dropped?: unknown[]; approved_by?: string; requested_by?: string; error?: string;
}

export interface Reason { kind: string; detail: string; score: number; pairs: [string, string][] }

export interface Suggestion {
  id: number; kind: "attach" | "merge" | "new_case"; case_id: string | null; other_case_id: string | null;
  report_ids: string[]; reasons: Reason[]; score: number;
  ai_verdict: string | null; ai_reason: string | null; ai_model: string | null;
  status: string; decided_by: string | null; decided_at: string | null;
  case_title?: string | null; other_case_title?: string | null;
  side_a?: Report[]; side_b?: Report[];
}

export interface CaseDetail {
  case: CaseRow;
  summary: Summary | null;
  review: { waiting: boolean; draft: Summary | null; outcome: string | null; started: boolean };
  reports: Report[];
  mentions: Record<string, Mention[]>;
  entities: CaseEntity[];
  money: MoneyRow[];
  key_identifiers: { kind: string; value: string; reports: number; bridge: boolean; display: string }[];
  links: { a: string; b: string; kind: string; strength: string; detail: string; score: number }[];
  timeline: { id: string; date: string; amount: number | null; city: string | null }[];
  cities: [string, number][]; countries: [string, number][]; sources: [string, number][]; languages: [string, number][];
  first_seen: string | null; last_seen: string | null;
  notes: { id: number; author: string; text: string; created_at: string }[];
  suggestions: Suggestion[];
  related: { id: string; title: string; status: string; why: string[] }[];
  four_eyes: boolean;
}

export interface GraphNode {
  id: string; type: "report" | "entity"; kind: string; label: string;
  date?: string; amount?: number | null; city?: string | null; pinned?: boolean;
  reports?: number; bridge?: boolean; money?: boolean; watched?: boolean; sources?: string[];
}
export interface GraphData { nodes: GraphNode[]; edges: { source: string; target: string }[] }

export interface Alert { id: number; kind: string; message: string; case_id: string | null; report_id: string | null; seen: boolean; created_at: string }
export interface Emerging { case_id: string; recent: number; earlier: number; days: number; title?: string | null }

export interface Overview {
  reports: number; reports_in_cases: number; cases: number; cases_by_status: Record<string, number>;
  pending_suggestions: number; total_loss: number; synthetic: boolean;
  by_kind: [string, number][]; by_source: [string, number][]; by_language: [string, number][];
  by_city: [string, number][]; by_country: [string, number][]; by_month: [string, number][];
  top_cases: CaseRow[]; emerging: Emerging[]; alerts: Alert[];
  top_money: { entity_id: number; kind: string; display: string; reports: number; total: number; cases: string[] }[];
}

export interface EntityRow {
  id: number; kind: string; value: string; display: string; official: boolean; watched: boolean;
  watch_note: string | null; valid: boolean; reports: number;
}

export interface Health {
  status: string; app: string; llm: string | false; model: string; models: { model: string; status: string }[];
  storage: string; demo_mode: boolean; four_eyes: boolean; hoshiyar_link: boolean; version: string;
}

export interface AskResult {
  answer: string; citations: string[]; removed_citations?: string[]; grounded: boolean;
  tools: { tool: string; args: Record<string, unknown> }[]; model?: string | null; source: string; note?: string;
}

export interface AuditEntry {
  id: number; ts: string; actor: string; action: string; object_type: string; object_id: string;
  details: Record<string, unknown>; hash: string; prev_hash: string;
}

export interface Pairwise { precision: number; recall: number; f1: number; pairs_predicted: number; pairs_true: number; pairs_correct: number }
export interface Quality {
  available: boolean; reason?: string;
  dataset: { reports: number; operations: number; one_off_reports: number };
  rules_only: Pairwise; rules_plus_suggestions: Pairwise; current_cases: Pairwise;
  suggestions: { total: number; correct: number; wrong: number };
  extraction: { precision: number; recall: number; identifiers_injected: number; identifiers_found: number;
    by_kind: Record<string, { injected: number; found: number; recall: number }> };
  decisions: Record<string, number>;
}

export interface IngestResult {
  new_ids: string[]; outcomes: { report_id: string; case_id: string | null; duplicate_of?: string | null; watch_hits?: string[]; [k: string]: unknown }[];
  linker?: Record<string, unknown>; ai_extracted?: string[]; note?: string;
}

// --------------------------------------------------------------------------- the token

const TOKEN_KEY = "caselink.token";
const USER_KEY = "caselink.user";

export function savedSession(): { token: string; user: User } | null {
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    const user = localStorage.getItem(USER_KEY);
    return token && user ? { token, user: JSON.parse(user) as User } : null;
  } catch {
    return null;
  }
}

let token: string | null = savedSession()?.token ?? null;
let onSignedOut: (() => void) | null = null;

export function setSession(t: string | null, user?: User) {
  token = t;
  try {
    if (t && user) {
      localStorage.setItem(TOKEN_KEY, t);
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    } else {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    }
  } catch {
    /* storage can be blocked; the session then lasts until the tab closes */
  }
}

export function whenSignedOut(fn: () => void) {
  onSignedOut = fn;
}

// --------------------------------------------------------------------------- waking the free server
// Render's free plan stops the API after 15 quiet minutes; the next request starts it again, which
// takes 30-60 seconds. A slow request alone proves nothing (an AI draft can take 10 seconds), so
// when one is slow we ask /api/health: if that does not answer within 2 seconds either, the server
// is asleep and the bottom bar shows until health answers.

type WakeListener = (waking: boolean) => void;
const wakeListeners = new Set<WakeListener>();
let probing = false;

export function onWaking(fn: WakeListener) {
  wakeListeners.add(fn);
  return () => void wakeListeners.delete(fn);
}

function emitWaking(waking: boolean) {
  wakeListeners.forEach((fn) => fn(waking));
}

/** Ask /api/health; show the bar if it is slow too, hide it when it answers. Resolves true if it answered. */
export function probeHealth(showAfterMs: number): Promise<boolean> {
  if (probing) return Promise.resolve(true);
  probing = true;
  let shown = false;
  const show = setTimeout(() => {
    shown = true;
    emitWaking(true);
  }, showAfterMs);
  const controller = new AbortController();
  const giveUp = setTimeout(() => controller.abort(), 150_000);
  return fetch(`${API_URL}/api/health`, { cache: "no-store", signal: controller.signal })
    .then((r) => r.ok, () => false)
    .finally(() => {
      clearTimeout(show);
      clearTimeout(giveUp);
      probing = false;
      if (shown) emitWaking(false);
    });
}

// --------------------------------------------------------------------------- requests

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown, raw = false): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const slow = setTimeout(() => void probeHealth(2000), 3500);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "The server could not be reached. Check your connection; if the demo was asleep, try again in a minute.");
  } finally {
    clearTimeout(slow);
  }
  if (res.status === 401 && token) {
    setSession(null);
    onSignedOut?.();
  }
  if (!res.ok) {
    let message = `Request failed (${res.status}).`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg?: string }) => d.msg).join(" ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  if (raw) return (await res.text()) as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, form),
  text: (path: string) => request<string>("GET", path, undefined, true),
};

export function download(name: string, content: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
