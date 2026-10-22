export const KIND_LABEL: Record<string, string> = {
  overseas_job: "Overseas job fraud",
  bisp: "Fake BISP payment",
  parcel: "Fake parcel fee",
  bank_otp: "Bank impersonation and OTP",
  task: "Online tasks and investment",
  family: "Fake family emergency",
  prize: "Fake prize or lucky draw",
  other: "Other fraud",
};

export const SOURCE_LABEL: Record<string, string> = {
  hoshiyar: "Hoshiyar (public scam checker)",
  pardes_guard: "Pardes Guard (overseas jobs)",
  police_desk: "Police desk",
  upload: "Uploaded file",
};

export const SOURCE_SHORT: Record<string, string> = {
  hoshiyar: "Hoshiyar",
  pardes_guard: "Pardes Guard",
  police_desk: "Police desk",
};

export const CHANNEL_LABEL: Record<string, string> = {
  sms: "SMS", whatsapp: "WhatsApp", call: "Phone call", web_form: "Web form", walk_in: "Walk-in", stix: "STIX feed",
};

export const LANG_LABEL: Record<string, string> = { en: "English", ur: "Urdu", roman: "Roman Urdu", mixed: "Mixed" };

export const ENTITY_LABEL: Record<string, string> = {
  phone: "Phone or wallet number", iban: "Bank account (IBAN)", domain: "Website", email: "Email address",
  license: "Licence number", handle: "Social handle", agency: "Agency name",
};

export const ROLE_LABEL: Record<string, string> = {
  wallet: "money sent to", payee: "money sent to", contact: "contact", sender: "sender", agency: "agency",
  website: "website", mention: "mentioned",
};

export const STATUS_LABEL: Record<string, string> = {
  proposed: "Proposed", open: "Open", investigating: "Investigating", referred: "Referred", closed: "Closed",
  rejected: "Rejected", merged: "Merged",
};

export const STATUS_HINT: Record<string, string> = {
  proposed: "The linker grouped these reports. A person has not checked them yet.",
  open: "Approved by an analyst. Nobody is working on it yet.",
  investigating: "An analyst is working on it.",
  referred: "Sent to the agencies who can act on it.",
  closed: "No further work planned.",
  rejected: "An analyst decided these reports do not belong together.",
  merged: "Joined into another case.",
};

/** Families of identifiers, each with one validated chart colour (see styles.css, --fam-*). */
export function family(kind: string): "numbers" | "online" | "names" {
  if (kind === "phone" || kind === "iban") return "numbers";
  if (kind === "domain" || kind === "email" || kind === "handle") return "online";
  return "names";
}

export const FAMILY_LABEL = { numbers: "Phone numbers and accounts", online: "Websites, emails, handles", names: "Agency names and licences" };

const pkr = new Intl.NumberFormat("en-PK", { maximumFractionDigits: 0 });

export function money(n: number | null | undefined): string {
  if (n == null) return "Not given";
  return `Rs ${pkr.format(n)}`;
}

/** Rs 1.2 crore / 4.5 lakh: how money is read in Pakistan. */
export function moneyShort(n: number | null | undefined): string {
  if (n == null) return "Not given";
  if (n >= 1e7) return `Rs ${(n / 1e7).toFixed(n >= 1e8 ? 0 : 1)} crore`;
  if (n >= 1e5) return `Rs ${(n / 1e5).toFixed(n >= 1e6 ? 0 : 1)} lakh`;
  return `Rs ${pkr.format(n)}`;
}

export function compact(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1).replace(/\.0$/, "")}K`;
  return String(n);
}

const dayFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
const shortFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const timeFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const monthFmt = new Intl.DateTimeFormat("en-GB", { month: "short", year: "2-digit" });

function parse(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

export const day = (iso: string | null | undefined) => (iso ? dayFmt.format(parse(iso)) : "");
export const dayShort = (iso: string | null | undefined) => (iso ? shortFmt.format(parse(iso)) : "");
export const when = (iso: string | null | undefined) => (iso ? timeFmt.format(parse(iso)) : "");
export const monthLabel = (ym: string) => monthFmt.format(new Date(`${ym}-01T00:00:00Z`));
export const toDate = parse;

export function person(email: string | null | undefined): string {
  if (!email) return "";
  if (email.startsWith("agent:")) return `${email.slice(6)} agent`;
  if (email.startsWith("system:")) return "the system";
  const who = email.replace(/^(analyst|user):/, "").split("@")[0].split(".")[0];
  return who.charAt(0).toUpperCase() + who.slice(1);
}

export function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

export function plural(n: number, one: string, many = `${one}s`) {
  return `${n.toLocaleString("en")} ${n === 1 ? one : many}`;
}

export function isUrdu(text: string): boolean {
  const arabic = (text.match(/[؀-ۿ]/g) || []).length;
  return arabic > text.length * 0.2;
}
