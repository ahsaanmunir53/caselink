"""Link reports into cases. Pure functions over in-memory data, so they are easy to test and evaluate.

Two kinds of evidence, treated differently:

* Strong: two reports share a phone number, IBAN, website, email, licence number or handle that is
  not official and not common. Rules link these automatically; the groups they form become
  *proposed* cases that a person reviews.
* Weak: the same agency name (after removing words like "Overseas" and "Manpower"), an abbreviation
  of it ("KL" for "Kuala Lumpur"), or a near-miss spelling. Many unrelated agencies share names, so
  these only become *suggestions* that wait for a person (and, if an AI model is configured, a second
  opinion from it). Nothing weak is ever merged automatically.

Pairs a person rejected are remembered and never proposed again.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

STRONG_KINDS = ("phone", "iban", "domain", "email", "license", "handle")
# Agency names so common in Pakistan that sharing one says little.
COMMON_NAMES = {"prime", "royal", "falcon", "star", "pak", "al", "global", "super", "new", "united", "national", "hira",
                "pearl", "golden", "green", "city", "asia", "world", "sky", "eagle", "shaheen", "crescent", "noor",
                "madina", "makkah", "zamzam", "best", "smart", "first", "metro", "classic", "unique"}
KIND_LABEL = {"phone": "phone number", "iban": "IBAN", "domain": "website", "email": "email", "license": "licence number",
              "handle": "handle", "agency": "agency name"}


@dataclass
class Rep:
    id: str
    kind: str
    received_at: datetime
    text: str
    destination: str | None = None
    amount: int | None = None
    entities: dict[str, set[str]] = field(default_factory=dict)  # kind -> normalised values (non-official)
    agency_raw: dict[str, str] = field(default_factory=dict)  # core -> a raw spelling


@dataclass
class Edge:
    a: str
    b: str
    kind: str  # identifier | name | abbreviation | spelling
    strength: str  # strong | weak
    detail: str  # e.g. "iban:PK36..." or "agency:alnoor"
    score: float = 1.0


@dataclass
class Suggestion:
    kind: str  # attach | merge | new_case
    groups: tuple[frozenset, frozenset]
    reasons: list[dict]
    score: float


@dataclass
class LinkResult:
    edges: list[Edge]
    components: list[frozenset]
    suggestions: list[Suggestion]
    common: set[tuple[str, str]]
    name_list: dict[str, list[str]]  # report id -> agency cores found by the name list


def pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


# --------------------------------------------------------------------------- name list

def _compact(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def apply_name_list(reps: list[Rep], min_length: int = 5) -> dict[str, list[str]]:
    """Agency names written without a tell-tale word ("Doha Link" instead of "Doha Link Recruiting")
    are found by looking for names already seen in two or more other reports."""
    seen: dict[str, int] = defaultdict(int)
    for r in reps:
        for core in r.entities.get("agency", set()):
            seen[core] += 1
    known = [c for c, n in seen.items() if n >= 2 and len(c) >= min_length]
    added: dict[str, list[str]] = {}
    for r in reps:
        compact = _compact(r.text)
        have = r.entities.setdefault("agency", set())
        for core in known:
            if core not in have and core in compact:
                # "alnoor" inside "alnooroverseas" counts; "noor" inside "alnoor" does not (cores are >= 5 letters
                # and must be absent from the report's own names).
                have.add(core)
                added.setdefault(r.id, []).append(core)
    return added


# --------------------------------------------------------------------------- common identifiers

def common_identifiers(reps: list[Rep], share: float, minimum: int) -> set[tuple[str, str]]:
    """Identifiers in so many reports that they say nothing about who is behind them."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for r in reps:
        for kind in STRONG_KINDS:
            for v in r.entities.get(kind, set()):
                counts[(kind, v)] += 1
    limit = max(minimum, int(share * len(reps)))
    return {key for key, n in counts.items() if n > limit}


# --------------------------------------------------------------------------- edges

def strong_edges(reps: list[Rep], common: set[tuple[str, str]], rejected: set[tuple[str, str]]) -> list[Edge]:
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in reps:
        for kind in STRONG_KINDS:
            for v in r.entities.get(kind, set()):
                if (kind, v) not in common:
                    index[(kind, v)].append(r.id)
    edges = []
    for (kind, value), ids in index.items():
        ids = sorted(set(ids))
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if pair(a, b) not in rejected:
                    edges.append(Edge(a, b, "identifier", "strong", f"{kind}:{value}", 1.0))
    return edges


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _initials(raw: str) -> str:
    from app.extract.rules import _GENERIC

    words = [w for w in "".join(ch if ch.isalnum() else " " for ch in raw.lower()).split() if w not in _GENERIC]
    return "".join(w[0] for w in words) if len(words) >= 2 else ""


def weak_edges(reps: list[Rep], rejected: set[tuple[str, str]], min_length: int = 5) -> list[Edge]:
    by_core: dict[str, list[str]] = defaultdict(list)
    raw_by_core: dict[str, str] = {}
    for r in reps:
        for core in r.entities.get("agency", set()):
            by_core[core].append(r.id)
            if core in r.agency_raw:
                raw_by_core.setdefault(core, r.agency_raw[core])
    edges: list[Edge] = []

    def connect(ids_a: list[str], ids_b: list[str], kind: str, detail: str, score: float) -> None:
        for a in ids_a:
            for b in ids_b:
                if a != b and pair(a, b) not in rejected:
                    edges.append(Edge(*pair(a, b), kind, "weak", detail, score))

    cores = sorted(by_core)
    for core in cores:
        ids = sorted(set(by_core[core]))
        if (len(core) >= min_length or core in COMMON_NAMES) and len(ids) > 1:
            score = 0.35 if core in COMMON_NAMES else 0.8
            kind = "common_name" if core in COMMON_NAMES else "name"
            for i, a in enumerate(ids):
                connect([a], ids[i + 1:], kind, f"agency:{core}", score)
    for i, c1 in enumerate(cores):
        for c2 in cores[i + 1:]:
            # Abbreviation: "kl" and "Kuala Lumpur"
            for short, long in ((c1, c2), (c2, c1)):
                if 2 <= len(short) <= 4 and _initials(raw_by_core.get(long, "")) == short:
                    connect(by_core[short], by_core[long], "abbreviation", f"agency:{short}={long}", 0.6)
            # One letter different in a long name: "alnoor" / "alnur"
            if min(len(c1), len(c2)) >= 6 and _distance(c1, c2) == 1:
                connect(by_core[c1], by_core[c2], "spelling", f"agency:{c1}~{c2}", 0.5)
    return edges


# --------------------------------------------------------------------------- grouping

def components(ids: list[str], edges: list[Edge]) -> list[frozenset]:
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        if e.a in parent and e.b in parent:
            ra, rb = find(e.a), find(e.b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    groups: dict[str, set[str]] = defaultdict(set)
    for i in ids:
        groups[find(i)].add(i)
    return sorted((frozenset(g) for g in groups.values()), key=lambda g: (-len(g), min(g)))


def make_suggestions(comps: list[frozenset], weak: list[Edge]) -> list[Suggestion]:
    owner = {rid: comp for comp in comps for rid in comp}
    grouped: dict[tuple[frozenset, frozenset], list[Edge]] = defaultdict(list)
    loose: dict[str, list[Edge]] = defaultdict(list)  # weak links between reports that are in no case yet
    for e in weak:
        ca, cb = owner.get(e.a), owner.get(e.b)
        if ca is None or cb is None or ca == cb:
            continue
        if len(ca) == 1 and len(cb) == 1:
            loose[e.detail].append(e)
            continue
        key = (ca, cb) if min(ca) < min(cb) else (cb, ca)
        grouped[key].append(e)
    out = []
    # Loose reports sharing a name become one "new case?" suggestion per name, not one per pair.
    for detail, edges in loose.items():
        members = frozenset(r for e in edges for r in (e.a, e.b))
        kind, score = edges[0].kind, edges[0].score
        out.append(Suggestion("new_case", (members, frozenset()), [
            {"kind": kind, "detail": detail, "score": score, "pairs": sorted({pair(e.a, e.b) for e in edges})[:5]}], score))
    for (ca, cb), edges in grouped.items():
        details = sorted({(e.kind, e.detail, e.score) for e in edges}, key=lambda x: -x[2])
        score = min(0.95, details[0][2] + 0.05 * (len(details) - 1))
        reasons = [{"kind": k, "detail": d, "score": s,
                    "pairs": sorted({pair(e.a, e.b) for e in edges if e.detail == d})[:5]} for k, d, s in details[:5]]
        if len(ca) > 1 and len(cb) > 1:
            kind = "merge"
        elif len(ca) > 1 or len(cb) > 1:
            kind = "attach"
        else:
            kind = "new_case"
        out.append(Suggestion(kind, (ca, cb), reasons, round(score, 3)))
    return sorted(out, key=lambda s: (-s.score, -max(len(s.groups[0]), len(s.groups[1]))))


def link_all(reps: list[Rep], share: float = 0.08, minimum: int = 12, min_length: int = 5,
             rejected: set[tuple[str, str]] | None = None) -> LinkResult:
    rejected = rejected or set()
    name_list = apply_name_list(reps, min_length)
    common = common_identifiers(reps, share, minimum)
    strong = strong_edges(reps, common, rejected)
    weak = weak_edges(reps, rejected, min_length)
    comps = components([r.id for r in reps], strong)
    return LinkResult(strong + weak, comps, make_suggestions(comps, weak), common, name_list)


# --------------------------------------------------------------------------- network analysis

def key_identifiers(member_ids: set[str], reps: dict[str, Rep], common: set[tuple[str, str]]) -> list[dict]:
    """Identifiers in a case, ranked by how many reports they connect, with 'bridge' marking the ones
    whose removal would split the case (the number or account that ties two phases together)."""
    holders: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rid in member_ids:
        r = reps[rid]
        for kind in STRONG_KINDS:
            for v in r.entities.get(kind, set()):
                if (kind, v) not in common:
                    holders[(kind, v)].add(rid)
    shared = {k: v for k, v in holders.items() if len(v) > 1}

    def pieces(without: tuple[str, str] | None) -> int:
        edges = [Edge(a, b, "identifier", "strong", f"{k[0]}:{k[1]}")
                 for k, ids in shared.items() if k != without for a in ids for b in ids if a < b]
        return len(components(sorted(member_ids), edges))

    base = pieces(None)
    out = []
    for (kind, value), ids in sorted(shared.items(), key=lambda kv: -len(kv[1])):
        out.append({"kind": kind, "value": value, "reports": len(ids),
                    "bridge": pieces((kind, value)) > base})
    return out
