"""Synthetic fraud reports with a hidden answer key.

Everything here is invented: agencies, people, phone numbers, IBANs and websites. The reports
imitate what reaches an analyst in Pakistan from two citizen tools (Hoshiyar for scam messages,
Pardes Guard for overseas-job fraud) and from police complaint desks.

Twelve operations ("gangs") each produce 14 to 26 reports. To make linking hard on purpose:

* operations rotate phone numbers over time; a few "bridge" reports mention an old and a new number;
* some reports carry no identifier at all, only the agency name, spelled several ways;
* many reports mention official numbers and websites (BEOE, FIA, bank helplines) that must NOT
  link anything;
* about 45 unrelated one-off reports, some with look-alike agency names.

The answer key (which operation each report belongs to) is returned separately and is used only
by the evaluation, never by the linker.
"""

import random
from datetime import UTC, datetime, timedelta

SEED = 2026
END = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)

CITIES = ["Lahore", "Rawalpindi", "Gujranwala", "Sialkot", "Faisalabad", "Karachi", "Peshawar", "Multan",
          "Mardan", "Swat", "Jhelum", "Mirpur", "Bahawalpur", "Sargodha", "Quetta", "Hyderabad"]
FIRST = ["Imran", "Raza", "Sajid", "Bilal", "Nadeem", "Shahid", "Kamran", "Waqas", "Zubair", "Asif", "Tariq",
         "Farhan", "Junaid", "Adnan", "Yasir", "Naveed", "Sohail", "Arshad"]
BANKS = ["MEZN", "HABB", "UNIL", "MUCB", "ALFH", "SCBL", "BAHL", "ABPA", "JSBL", "FAYS"]
# Official contacts victims mention ("I checked on beoe.gov.pk"). They appear across many
# operations and must never link reports.
OFFICIAL = {
    "overseas_job": ["I checked the licence on beoe.gov.pk and it was not listed.",
                     "BEOE helpline 051-9201059 told me the agency is not registered.",
                     "Complaint also filed on complaint.fia.gov.pk.",
                     "Protector of Emigrants office said do not pay agents in cash."],
    "bank": ["I called the HBL helpline 111-111-425 and they blocked my card.",
             "UBL helpline 111-825-888 confirmed the transfer.", "Reported on complaint.fia.gov.pk."],
    "wallet": ["I called JazzCash helpline 4444 to stop the transaction.", "Easypaisa helpline 3737 said the money was gone.",
               "Reported to FIA cybercrime on complaint.fia.gov.pk."],
    "bisp": ["BISP only sends messages from 8171, I checked on 8171.bisp.gov.pk later."],
}


def iban(rng: random.Random, bank: str | None = None) -> str:
    """A Pakistani IBAN with valid check digits (24 characters)."""
    bank = bank or rng.choice(BANKS)
    bban = bank + "".join(rng.choice("0123456789") for _ in range(16))
    moved = bban + "PK00"
    number = int("".join(str(int(ch, 36)) for ch in moved))
    return f"PK{98 - number % 97:02d}{bban}"


def phone(rng: random.Random, used: set[str]) -> str:
    while True:
        p = "03" + rng.choice(["00", "01", "03", "05", "06", "11", "12", "13", "21", "22", "33", "35", "41", "45", "47"]) + \
            "".join(rng.choice("0123456789") for _ in range(7))
        if p not in used and not _sequence(p):
            used.add(p)
            return p


def _sequence(p: str) -> bool:
    digits = p[2:]
    return any(digits[i:i + 5] in "0123456789" or digits[i:i + 5] in "9876543210" for i in range(len(digits) - 4))


def fmt_phone(rng: random.Random, p: str) -> str:
    """The same number written the ways people write it."""
    return rng.choice([p, f"{p[:4]}-{p[4:]}", f"+92 {p[1:4]} {p[4:]}", f"{p[:4]} {p[4:]}", f"92{p[1:]}"])


def fmt_iban(rng: random.Random, value: str) -> str:
    return value if rng.random() < 0.5 else " ".join(value[i:i + 4] for i in range(0, 24, 4))


def fmt_domain(rng: random.Random, domain: str) -> str:
    return rng.choice([domain, f"www.{domain}", f"https://{domain}/apply", f"{domain.replace('.', '[.]', 1)}"])


# --------------------------------------------------------------------------- operations

OPERATIONS = [
    # id, kind, names (variants), destination, job, extra
    {"id": "OP-01", "kind": "overseas_job", "names": ["Al-Noor Overseas Employment Promoters", "Al Noor Overseas", "AlNoor Manpower"],
     "country": "Saudi Arabia", "job": "heavy driver", "domain": "alnoor-overseas.com", "license": "OEP-2214/RWP", "fee": (120000, 260000)},
    {"id": "OP-02", "kind": "overseas_job", "names": ["Gulf Star Manpower Services", "Gulf Star Manpower", "GulfStar Recruiting"],
     "country": "UAE", "job": "security guard", "domain": "gulfstar-jobs.pk", "license": "OEP-3108/LHR", "fee": (90000, 180000)},
    {"id": "OP-03", "kind": "overseas_job", "names": ["Euro Work Permit Consultants", "EuroWork Permit", "Euro Workpermit Consultancy"],
     "country": "Romania", "job": "warehouse", "domain": "euro-workpermit.online", "email": "visa.desk@euro-workpermit.online",
     "fee": (350000, 900000)},
    {"id": "OP-04", "kind": "overseas_job", "names": ["Kuala Lumpur Manpower Services", "KL Manpower", "K.L Manpower Services"],
     "country": "Malaysia", "job": "factory", "fee": (150000, 300000)},
    {"id": "OP-05", "kind": "overseas_job", "names": ["Lion City Placements", "LionCity Placement", "Lion City Careers"],
     "country": "Singapore", "job": "hotel housekeeping", "domain": "lioncity-careers.com", "email": "hr@lioncity-careers.com",
     "fee": (250000, 500000)},
    {"id": "OP-06", "kind": "overseas_job", "names": ["Doha Link Recruiting Agency", "Doha Link", "DohaLink Recruitment"],
     "country": "Qatar", "job": "construction", "license": "OEP-1890/KHI", "fee": (110000, 220000)},
    {"id": "OP-07", "kind": "bisp", "names": [], "domain": "bisp-8171-check.online", "fee": (500, 2500)},
    {"id": "OP-08", "kind": "parcel", "names": [], "domain": "pakpost-delivery.top", "fee": (3000, 45000)},
    {"id": "OP-09", "kind": "bank_otp", "names": [], "domain": "hbl-verify.top", "fee": (25000, 400000)},
    {"id": "OP-10", "kind": "task", "names": ["Profit Tasks", "ProfitTasks VIP"], "domain": "profit-tasks.vip",
     "handle": "@profit_tasks_admin", "fee": (10000, 300000)},
    {"id": "OP-11", "kind": "family", "names": [], "fee": (15000, 120000)},
    {"id": "OP-12", "kind": "prize", "names": ["Jeeto Inaam Scheme"], "fee": (2000, 30000)},
]
SIZES = {"OP-01": 26, "OP-02": 22, "OP-03": 18, "OP-04": 20, "OP-05": 18, "OP-06": 16,
         "OP-07": 22, "OP-08": 20, "OP-09": 18, "OP-10": 20, "OP-11": 14, "OP-12": 16}
SOURCES = {"overseas_job": ["pardes_guard", "police_desk", "pardes_guard"],
           "bisp": ["hoshiyar"], "parcel": ["hoshiyar"], "bank_otp": ["hoshiyar", "police_desk"],
           "task": ["hoshiyar", "police_desk"], "family": ["hoshiyar", "police_desk"], "prize": ["hoshiyar"]}


def _amount(rng: random.Random, lo: int, hi: int) -> int:
    return int(rng.randint(lo, hi) // 500 * 500) or lo


def _rs(rng: random.Random, value: int) -> str:
    return rng.choice([f"Rs {value:,}", f"Rs. {value:,}", f"{value:,} rupees", f"PKR {value:,}", f"{value}"])


# --------------------------------------------------------------------------- templates

def _overseas(rng, v, lang: str, strong: bool) -> str:
    agency, alias, country, job, city = v["agency"], v["alias"], v["country"], v["job"], v["city"]
    money = _rs(rng, v["amount"])
    if not strong:  # walk-in complaint with no identifier
        return _pick(rng, lang, [
            ("en", f"Walk-in complaint at {city}: {agency} took {money} for a {job} visa to {country}. Agent called himself {alias}. No receipt was given."),
            ("roman", f"{agency} ke office ({city}) mein {alias} naam ke banday ne {country} ki {job} job ke liye {money} cash liye. Raseed nahi di."),
            ("ur", f"{agency} نے {city} میں {country} کی نوکری کے نام پر {money} نقد لیے۔ ایجنٹ کا نام {alias} بتایا۔"),
        ])
    ids = v["ids"]
    pay = ids.get("wallet") and f"JazzCash {ids['wallet']}" or ids.get("iban") and f"account {ids['iban']}" or "cash"
    contact = ids.get("phone") or ids.get("phone2") or ""
    extra = []
    if ids.get("phone2") and ids.get("phone"):
        extra.append(f"Later they called from {ids['phone2']}.")
    if ids.get("domain"):
        extra.append(rng.choice([f"Their website was {ids['domain']}.", f"Website {ids['domain']} par form bhara."]))
    if ids.get("email"):
        extra.append(f"Offer letter came from {ids['email']}.")
    if ids.get("license"):
        extra.append(rng.choice([f"They showed licence number {ids['license']}.", f"License {ids['license']} likha hua tha."]))
    tail = " ".join(extra)
    if lang == "en":
        body = rng.choice([
            f"I paid {money} to {agency} for a {job} job in {country}. Their agent {alias} gave me number {contact} and asked me to send the fee to {pay}. After payment the number was switched off.",
            f"Complaint against {agency}. They promised {job} work in {country} with a free ticket, took my passport copy and {money} as visa processing fee in {pay}. Contact: {contact}.",
            f"My brother was offered a {job} job in {country} by {agency} ({city}). {alias} took {money} through {pay} and stopped replying on {contact}.",
        ])
    elif lang == "roman":
        body = rng.choice([
            f"{agency} walon ne {country} mein {job} ki naukri ka keh kar {money} le liye. {alias} ka number {contact} tha, paise {pay} par bhejwaye. Ab phone band hai.",
            f"Mere bhai se {agency} ne {country} visa ke naam par {money} liye, {pay} mein jama karwaye. Contact {contact}. Bola {job} ka kaam hai.",
        ])
    else:
        body = rng.choice([
            f"{agency} نے {country} میں {job} کی نوکری کا جھانسہ دے کر {money} لیے۔ رابطہ نمبر {contact}۔ رقم {pay} میں بھجوائی گئی۔",
            f"{agency} کے ایجنٹ {alias} نے {country} کے ویزے کے لیے {money} لیے اور اب نمبر {contact} بند ہے۔ ادائیگی {pay}۔",
        ])
    return f"{body} {tail}".strip()


def _pick(rng: random.Random, lang: str, options: list[tuple[str, str]]) -> str:
    """Choose a template written in the report's language when there is one."""
    same = [text for code, text in options if code == lang]
    return rng.choice(same or [text for _, text in options])


def _scam(rng, op: dict, v, lang: str) -> str:
    ids = v["ids"]
    caller = ids.get("phone") or ids.get("phone2") or "an unknown number"
    wallet = ids.get("wallet") or caller
    domain = ids.get("domain")
    kind = op["kind"]
    if kind == "bisp":
        fee_value = rng.choice([500, 1000, 1500, 2000])
        fee, money = _rs(rng, fee_value), _rs(rng, fee_value * rng.choice([1, 1, 2, 3]))
        link_en = f" and check status at {domain}." if domain else "."
        link_ro = f", link {domain} bhi diya." if domain else "."
        return _pick(rng, lang, [
            ("en", f"Got an SMS from {caller}: BISP payment of 25000 approved, pay registration fee {fee} to JazzCash {wallet}{link_en} I paid and lost {money}."),
            ("roman", f"Mujhe {caller} se message aya ke BISP ki qist aa gayi, {fee} fee {wallet} par bhejein{link_ro} Kul {money} gaye."),
            ("ur", f"{caller} سے پیغام آیا کہ بی آئی ایس پی کی رقم آ گئی ہے، فیس {fee} جاز کیش {wallet} پر بھیجیں۔ میرے {money} گئے۔"),
        ])
    money = _rs(rng, v["amount"])
    if kind == "parcel":
        return _pick(rng, lang, [
            ("en", f"SMS from {caller}: your Pakistan Post parcel is on hold, pay Rs 150 at {domain or 'a link'}. I entered my card details and {money} was deducted."),
            ("roman", f"{caller} se SMS: parcel address ghalat hai, {domain or 'link'} par Rs 150 pay karein. Card details daalin aur {money} kat gaye."),
            ("ur", f"{caller} سے ایس ایم ایس آیا کہ پارسل رکا ہوا ہے، {domain or 'لنک'} پر 150 روپے دیں۔ کارڈ کی تفصیل ڈالی اور {money} کٹ گئے۔"),
        ])
    if kind == "bank_otp":
        target = ids.get("iban") or wallet
        return _pick(rng, lang, [
            ("en", f"Caller from {caller} said he is from HBL head office and my account will be blocked. He sent {domain or 'a link'} and asked for the OTP. {money} was transferred out to {target}."),
            ("roman", f"{caller} se call aayi, bola bank se hoon, account band ho jayega. {domain or 'link'} khulwaya aur OTP le liya. {money} {target} mein chale gaye."),
            ("ur", f"{caller} سے کال آئی کہ میں بینک سے ہوں، اکاؤنٹ بند ہو جائے گا۔ او ٹی پی لے لیا اور {money} {target} میں منتقل ہو گئے۔"),
        ])
    if kind == "task":
        handle, alias = ids.get("handle"), v["alias"]
        pay = ids.get("iban") or wallet
        site = f" Website {domain} shows a balance but withdrawal never comes." if domain else ""
        return _pick(rng, lang, [
            ("en", f"Joined a Telegram group run by {alias}" + (f" ({handle})" if handle else "") + f" promising Rs 5000 daily for liking videos. Paid {money} to {pay} as task deposit.{site}"),
            ("roman", f"{v['agency']} naam ki online earning scheme mein {money} lagaye, {pay} par bheje." + (f" Admin {handle}." if handle else "") + " Ab withdrawal band hai."),
            ("ur", f"{v['agency']} نامی آن لائن کمائی اسکیم میں {money} لگائے، رقم {pay} پر بھیجی۔ اب رقم نہیں نکل رہی۔"),
        ])
    if kind == "family":
        alias = v["alias"]
        return _pick(rng, lang, [
            ("en", f"WhatsApp from {caller}: 'Mum, it's {alias}, this is my new number, send {money} right now, I am in trouble.' We sent it to JazzCash {wallet}."),
            ("roman", f"WhatsApp {caller} se: 'Ammi main {alias} hoon, ye naya number hai, foran {money} bhej dein, mushkil mein hoon.' Humne JazzCash {wallet} par bhej diye."),
            ("ur", f"{caller} سے پیغام آیا کہ میں {alias} ہوں، نیا نمبر ہے، فوراً {money} بھیج دیں۔ رقم {wallet} پر بھیجی۔"),
        ])
    fee = _rs(rng, rng.choice([1500, 2500, 5000]))
    scheme = v["agency"] or "Jeeto"
    return _pick(rng, lang, [
        ("en", f"I got a call from {caller} saying I won a car in the {scheme} lucky draw. They asked for {fee} tax on Easypaisa {wallet}. I paid {money}."),
        ("roman", f"Call from {caller}: '{scheme} lucky draw mein aap ka inaam nikla hai', tax {fee} Easypaisa {wallet} par bhejne ko kaha. Total {money} de diye."),
        ("ur", f"{caller} سے کال آئی کہ {scheme} لکی ڈرا میں آپ کا انعام نکلا ہے، ٹیکس {fee} ایزی پیسہ {wallet} پر بھیجیں۔ میں نے {money} دے دیے۔"),
    ])


# --------------------------------------------------------------------------- generator

def generate(seed: int = SEED) -> tuple[list[dict], dict[str, str | None]]:
    rng = random.Random(seed)
    used: set[str] = set()
    reports: list[dict] = []
    truth: dict[str, str | None] = {}

    for op in OPERATIONS:
        n = SIZES[op["id"]]
        # Two or three "eras" of phone numbers; a bridge report mentions numbers from two eras.
        eras = [[phone(rng, used) for _ in range(rng.randint(1, 2))] for _ in range(rng.randint(2, 3))]
        wallets = [phone(rng, used) for _ in range(rng.randint(1, 2))]
        ibans = [iban(rng) for _ in range(rng.randint(1, 2))] if op["kind"] in ("overseas_job", "bank_otp", "task") else []
        aliases = rng.sample(FIRST, 2)
        start = END - timedelta(days=rng.randint(60, 170))
        span = (END - start).days
        lang_weights = {"en": 0.4, "roman": 0.4, "ur": 0.2}
        for i in range(n):
            era = min(len(eras) - 1, i * len(eras) // n)
            when = start + timedelta(days=span * i / n + rng.uniform(-3, 3), hours=rng.uniform(8, 20))
            lang = rng.choices(list(lang_weights), weights=list(lang_weights.values()))[0]
            strong = not (op["kind"] == "overseas_job" and rng.random() < 0.18)
            ids: dict[str, str] = {}
            if strong:
                pool = eras[era]
                ids["phone"] = fmt_phone(rng, rng.choice(pool))
                if i % 7 == 3 and era + 1 < len(eras):  # bridge to the next era
                    ids["phone2"] = fmt_phone(rng, rng.choice(eras[era + 1]))
                if rng.random() < 0.55:
                    ids["wallet"] = fmt_phone(rng, rng.choice(wallets))
                if ibans and rng.random() < 0.5:
                    ids["iban"] = fmt_iban(rng, rng.choice(ibans))
                if op.get("domain") and rng.random() < 0.45:
                    ids["domain"] = fmt_domain(rng, op["domain"])
                if op.get("email") and rng.random() < 0.3:
                    ids["email"] = op["email"]
                if op.get("license") and rng.random() < 0.35:
                    ids["license"] = op["license"]
                if op.get("handle") and rng.random() < 0.5:
                    ids["handle"] = op["handle"]
            v = {"agency": rng.choice(op["names"]) if op["names"] else "", "alias": rng.choice(aliases) + rng.choice(["", " bhai", " sahab"]),
                 "country": op.get("country", ""), "job": op.get("job", ""), "city": rng.choice(CITIES),
                 "amount": _amount(rng, *op["fee"]), "ids": ids}
            text = _overseas(rng, v, lang, strong) if op["kind"] == "overseas_job" else _scam(rng, op, v, lang)
            official_kind = {"overseas_job": "overseas_job", "bank_otp": "bank", "bisp": "bisp"}.get(op["kind"], "wallet")
            if rng.random() < 0.3:
                text += " " + rng.choice(OFFICIAL[official_kind])
            rid = f"R-{len(reports) + 1:04d}"
            reports.append(_report(rid, op, text, lang, when, v, rng))
            truth[rid] = op["id"]

    # One-off reports: same kinds, fresh identifiers, no operation. Some use look-alike agency names.
    lookalikes = ["Star Manpower Sialkot", "Noor Travel and Tours", "Euro Study Consultants", "Doha Cargo Services"]
    for j in range(45):
        op = dict(rng.choice(OPERATIONS))
        op["id"] = None
        op["names"] = [rng.choice(lookalikes)] if op["kind"] == "overseas_job" and j % 3 == 0 else \
            [f"{rng.choice(['Pak', 'Prime', 'Royal', 'Falcon', 'Hira'])} {rng.choice(['Overseas', 'Manpower', 'Recruiters'])}"]
        op.pop("domain", None), op.pop("email", None), op.pop("license", None), op.pop("handle", None)
        ids = {"phone": fmt_phone(rng, phone(rng, used))}
        if rng.random() < 0.5:
            ids["wallet"] = fmt_phone(rng, phone(rng, used))
        if op["kind"] in ("overseas_job", "bank_otp", "task") and rng.random() < 0.4:
            ids["iban"] = fmt_iban(rng, iban(rng))
        v = {"agency": op["names"][0], "alias": rng.choice(FIRST), "country": op.get("country", ""), "job": op.get("job", ""),
             "city": rng.choice(CITIES), "amount": _amount(rng, *op["fee"]), "ids": ids}
        lang = rng.choice(["en", "roman", "ur"])
        text = _overseas(rng, v, lang, True) if op["kind"] == "overseas_job" else _scam(rng, op, v, lang)
        if rng.random() < 0.4:
            official_kind = {"overseas_job": "overseas_job", "bank_otp": "bank", "bisp": "bisp"}.get(op["kind"], "wallet")
            text += " " + rng.choice(OFFICIAL[official_kind])
        when = END - timedelta(days=rng.uniform(0, 170))
        rid = f"R-{len(reports) + 1:04d}"
        reports.append(_report(rid, op, text, lang, when, v, rng))
        truth[rid] = None

    # Shuffle the order reports arrive in, then renumber so ids say nothing about the operation.
    rng.shuffle(reports)
    reports.sort(key=lambda r: r["received_at"])
    renumbered, new_truth = [], {}
    for k, r in enumerate(reports, start=1):
        new_id = f"R-{k:04d}"
        new_truth[new_id] = truth[r["id"]]
        renumbered.append({**r, "id": new_id})
    return renumbered, new_truth


def _report(rid: str, op: dict, text: str, lang: str, when: datetime, v: dict, rng: random.Random) -> dict:
    source = rng.choice(SOURCES[op["kind"]])
    channel = {"pardes_guard": "web_form", "hoshiyar": rng.choice(["sms", "whatsapp", "call"]),
               "police_desk": "walk_in"}[source]
    return {
        "id": rid,
        "source": source,
        "channel": channel,
        "received_at": when.isoformat(timespec="minutes"),
        "language": lang,
        "reporter_city": v["city"],
        "destination_country": v["country"] or None,
        "amount_lost": v["amount"],
        "currency": "PKR",
        "kind": op["kind"],
        "text": text,
        "synthetic": True,
        # Identifiers the generator put into this text (for scoring extraction only; never stored).
        "_ids": [raw for raw in v["ids"].values() if raw and raw in text],
    }
