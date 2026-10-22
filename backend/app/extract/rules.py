"""Find identifiers in a report and write each one the same way every time.

The same phone number arrives as "0300-1234567", "+92 300 1234567" and "923001234567"; the same
IBAN with or without spaces; the same website as "www.x.com/apply" or "hxxps://x[.]com". Linking
only works when all of these become one value, so every identifier is normalised here:

  phone     +923001234567          (Pakistani mobiles; landlines and UAN numbers too)
  iban      PK36SCBL0000001123456702 (check digits verified)
  domain    alnoor-overseas.com     (registered domain, link disguises undone)
  email     visa.desk@example.com
  license   OEP-2214/RWP            (overseas employment promoter licence)
  handle    @profit_tasks_admin     (Telegram / social handle)
  agency    alnoor                  (agency name with generic words removed, for name matching)

Official contacts (BEOE, FIA, BISP, bank helplines, wallet short codes) are recognised and kept
out of linking: thousands of unrelated victims mention them.
"""

import re
from dataclasses import dataclass, field

from app.core.urls import extract_urls, split_url

# --------------------------------------------------------------------------- patterns

_MOBILE = re.compile(r"(?<![\d+])(?:\+92|0092|92|0)[\s-]?(3\d{2})[\s-]?(\d{3})[\s-]?(\d{4})(?!\d)")
_LANDLINE = re.compile(r"(?<![\d+])(0\d{2,3})-(\d{6,8})(?!\d)")
_UAN = re.compile(r"(?<!\d)(111)-(\d{3})-(\d{3})(?!\d)")
_IBAN = re.compile(r"\bPK\s?\d{2}(?:\s?[A-Z0-9]){20}\b", re.I)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")
_LICENSE = re.compile(r"\bOEP[\s-]?(\d{3,5})\s?/\s?([A-Z]{3})\b", re.I)
_HANDLE = re.compile(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_]{3,31})\b")
_WALLET_CONTEXT = re.compile(r"(jazz\s?cash|easy\s?paisa|wallet|upaisa|sadapay|nayapay|جاز کیش|ایزی پیسہ)\W{0,3}$", re.I)
_MONEY = re.compile(r"(?:rs\.?|pkr|rupees?)\s?(\d[\d,]{2,})|(\d[\d,]{2,})\s?(?:rupees?|rupay|روپے)", re.I)

# Official numbers and websites that victims mention. They never link reports.
OFFICIAL_DOMAINS = {"gov.pk", "beoe.gov.pk", "fia.gov.pk", "bisp.gov.pk", "nadra.gov.pk", "pta.gov.pk", "sbp.org.pk",
                    "hbl.com", "ubldigital.com", "jazzcash.com.pk", "easypaisa.com.pk", "pakpost.gov.pk", "tcsexpress.com"}
OFFICIAL_NUMBERS = {"+92519201059", "UAN-111111425", "UAN-111825888", "UAN-111786786"}
SHORT_CODES = {"4444", "3737", "8171", "1166", "9915"}

# Words that say what an agency is, not who it is. Removing them lets "Al Noor Overseas" and
# "AlNoor Manpower" become the same core name.
_GENERIC = {
    "overseas", "employment", "promoters", "promoter", "manpower", "services", "service", "consultants", "consultant",
    "consultancy", "recruiting", "recruitment", "recruiters", "agency", "agencies", "placements", "placement", "careers",
    "career", "international", "intl", "pvt", "private", "ltd", "limited", "company", "co", "group", "travel", "travels",
    "tours", "and", "the", "of", "scheme", "vip", "official", "jobs", "job", "visa", "visas", "trading", "enterprises",
    "associates", "solutions",
}
_AGENCY_SUFFIX = (r"(?:Overseas(?: Employment Promoters)?|Manpower(?: Services)?|Placements?|Consultan(?:ts|cy)|"
                  r"Recruit(?:ing|ment|ers)(?: Agency)?|Careers|Services|Agency|Travel and Tours|Scheme|VIP|Promoters)")
_AGENCY = re.compile(
    rf"((?:[A-Z][A-Za-z.\-]*|[A-Z]{{2,}})(?:\s(?:[A-Z][A-Za-z.\-]*|[A-Z]{{2,}}|and)){{0,4}}\s{_AGENCY_SUFFIX}"
    rf"|[A-Z][a-z]+[A-Z][a-z]+(?:\s[A-Z][a-z]+){{0,2}}(?:\s{_AGENCY_SUFFIX})?)"
)
_NOT_AGENCY = {"pakistan post", "telegram", "whatsapp", "jazzcash", "easypaisa", "hbl", "bisp", "fia", "beoe", "protector"}


@dataclass
class Found:
    kind: str
    value: str  # normalised
    raw: str
    role: str = "contact"  # contact | wallet | payee | website | sender ...
    official: bool = False
    valid: bool = True


@dataclass
class Extraction:
    entities: list[Found] = field(default_factory=list)
    amount: int | None = None

    def values(self, kind: str | None = None, include_official: bool = False) -> list[str]:
        return sorted({e.value for e in self.entities if (kind is None or e.kind == kind) and (include_official or not e.official)})


def normalize_mobile(raw: str) -> str | None:
    m = _MOBILE.search(raw)
    return f"+92{m.group(1)}{m.group(2)}{m.group(3)}" if m else None


def iban_valid(value: str) -> bool:
    moved = value[4:] + value[:4]
    try:
        return int("".join(str(int(ch, 36)) for ch in moved)) % 97 == 1
    except ValueError:
        return False


def agency_core(name: str) -> str:
    words = re.findall(r"[a-z]+", name.lower().replace("-", " ").replace(".", ""))
    core = "".join(w for w in words if w not in _GENERIC)
    return core


def mask(kind: str, value: str) -> str:
    """How an identifier is shown in lists: enough to recognise it, not the whole thing."""
    if kind == "phone" and value.startswith("+92") and len(value) == 13:
        return f"0{value[3:6]}-***-{value[-4:]}"
    if kind == "iban" and len(value) == 24:
        return f"{value[:8]} **** {value[-4:]}"
    return value


def extract(text: str) -> Extraction:
    out = Extraction()
    seen: set[tuple[str, str]] = set()

    def add(found: Found) -> None:
        key = (found.kind, found.value)
        if key in seen:
            return
        seen.add(key)
        out.entities.append(found)

    # Emails first, so their domains are not also read as websites.
    emails = []
    for m in _EMAIL.finditer(text):
        email = m.group(0).lower()
        emails.append(email)
        domain = split_url(email.split("@", 1)[1])["registered_domain"]
        add(Found("email", email, m.group(0), "contact", official=domain in OFFICIAL_DOMAINS))
    scrubbed = _EMAIL.sub(" ", text)

    for m in _IBAN.finditer(scrubbed):
        value = re.sub(r"\s", "", m.group(0)).upper()
        if len(value) == 24:
            add(Found("iban", value, m.group(0), "payee", valid=iban_valid(value)))
    no_iban = _IBAN.sub(" ", scrubbed)

    for m in _MOBILE.finditer(no_iban):
        value = f"+92{m.group(1)}{m.group(2)}{m.group(3)}"
        before = no_iban[max(0, m.start() - 20):m.start()]
        role = "wallet" if _WALLET_CONTEXT.search(before) else "contact"
        add(Found("phone", value, m.group(0), role, official=value in OFFICIAL_NUMBERS))
    for m in _UAN.finditer(no_iban):
        value = f"UAN-{m.group(1)}{m.group(2)}{m.group(3)}"
        add(Found("phone", value, m.group(0), "helpline", official=True))
    for m in _LANDLINE.finditer(no_iban):
        value = f"+92{m.group(1)[1:]}{m.group(2)}"
        add(Found("phone", value, m.group(0), "landline", official=value in OFFICIAL_NUMBERS))

    for url in extract_urls(scrubbed, limit=10):
        parts = split_url(url)
        domain = parts["registered_domain"]
        if not domain:
            continue
        official = domain in OFFICIAL_DOMAINS or domain.endswith(".gov.pk") or parts["suffix"] == "gov.pk"
        add(Found("domain", domain, url, "website", official=official))

    for m in _LICENSE.finditer(text):
        add(Found("license", f"OEP-{m.group(1)}/{m.group(2).upper()}", m.group(0), "licence"))
    for m in _HANDLE.finditer(scrubbed):
        add(Found("handle", "@" + m.group(1).lower(), m.group(0), "contact"))

    for m in _AGENCY.finditer(text):
        name = m.group(1).strip(" .-")
        core = agency_core(name)
        if len(core) < 2 or name.lower() in _NOT_AGENCY or core in _NOT_AGENCY:
            continue
        add(Found("agency", core, name, "agency"))

    amounts = [int((a or b).replace(",", "")) for a, b in _MONEY.findall(text)]
    out.amount = max(amounts) if amounts else None
    return out
