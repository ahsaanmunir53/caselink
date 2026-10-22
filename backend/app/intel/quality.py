"""How well linking works, measured against the synthetic data's answer key.

Pairwise scoring: every pair of reports from the same operation should end up together (recall),
and every pair put together should really be from one operation (precision). Measured for:

* rules only            what the linker does automatically (strong identifiers)
* rules + suggestions   if analysts accepted every suggestion scoring 0.5 or more
* current cases         the cases as they stand now, after people's decisions

Extraction is scored too: of the identifiers the generator put into the reports, how many the
rules found (recall), and how many found identifiers were really there (precision).
"""

import itertools
from collections import defaultdict

from app.data.synthetic import generate
from app.extract.rules import extract
from app.link.linker import link_all


def _pairs(groups) -> set[tuple[str, str]]:
    out = set()
    for g in groups:
        out.update(itertools.combinations(sorted(g), 2))
    return out


def pairwise(predicted_groups, truth: dict[str, str | None]) -> dict:
    groups = defaultdict(set)
    for rid, op in truth.items():
        if op:
            groups[op].add(rid)
    true_pairs = _pairs(groups.values())
    pred = _pairs([set(g) & set(truth) for g in predicted_groups])
    tp = len(pred & true_pairs)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(true_pairs) if true_pairs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
            "pairs_predicted": len(pred), "pairs_true": len(true_pairs), "pairs_correct": tp}


def merged_with_suggestions(result, threshold: float = 0.5) -> list[set]:
    groups = [set(c) for c in result.components]
    owner = {rid: i for i, g in enumerate(groups) for rid in g}
    parent = list(range(len(groups)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s in result.suggestions:
        if s.score < threshold:
            continue
        members = [owner[r] for g in s.groups for r in g]
        for m in members[1:]:
            a, b = find(members[0]), find(m)
            if a != b:
                parent[b] = a
    merged = defaultdict(set)
    for i, g in enumerate(groups):
        merged[find(i)] |= g
    return list(merged.values())


def extraction_scores(reports: list[dict]) -> dict:
    found_total = injected_total = correct = 0
    by_kind: dict[str, dict] = defaultdict(lambda: {"injected": 0, "found": 0})
    for r in reports:
        injected = set()
        for raw in r.get("_ids", []):
            injected |= {(e.kind, e.value) for e in extract(raw).entities if e.kind != "agency"}
        found = {(e.kind, e.value) for e in extract(r["text"]).entities if e.kind != "agency" and not e.official}
        injected_total += len(injected)
        found_total += len(found)
        correct += len(found & injected)
        for kind, _ in injected:
            by_kind[kind]["injected"] += 1
        for kind, _ in found & injected:
            by_kind[kind]["found"] += 1
    return {"precision": round(correct / found_total, 4) if found_total else 0.0,
            "recall": round(correct / injected_total, 4) if injected_total else 0.0,
            "identifiers_injected": injected_total, "identifiers_found": found_total,
            "by_kind": {k: {**v, "recall": round(v["found"] / v["injected"], 4) if v["injected"] else 0.0} for k, v in by_kind.items()}}


def offline_report(reps: list, settings) -> dict:
    """Scores for the linker on the given reports against the synthetic answer key."""
    reports, truth = generate()
    ids = {r.id for r in reps}
    truth = {k: v for k, v in truth.items() if k in ids}
    result = link_all(reps, settings.hub_share, settings.hub_min_reports, settings.name_min_length)
    pending = [s for s in result.suggestions]
    right = sum(1 for s in pending if len({truth.get(r) for g in s.groups for r in g}) == 1
                and next(iter({truth.get(r) for g in s.groups for r in g})) is not None)
    return {
        "dataset": {"reports": len(truth), "operations": len({v for v in truth.values() if v}),
                    "one_off_reports": sum(v is None for v in truth.values())},
        "rules_only": pairwise(result.components, truth),
        "rules_plus_suggestions": pairwise(merged_with_suggestions(result, 0.5), truth),
        "suggestions": {"total": len(pending), "correct": right, "wrong": len(pending) - right},
        "extraction": extraction_scores(reports),
    }
