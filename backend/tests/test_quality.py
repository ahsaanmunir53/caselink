"""The numbers in the README come from these checks."""

from collections import defaultdict
from datetime import datetime

from app.config import Settings
from app.data.synthetic import generate
from app.extract.rules import extract
from app.intel.quality import extraction_scores, offline_report
from app.link.linker import Rep


def reps_from_synthetic():
    reports, truth = generate()
    reps = []
    for r in reports:
        ents, raw = defaultdict(set), {}
        for e in extract(r["text"]).entities:
            if not e.official:
                ents[e.kind].add(e.value)
                if e.kind == "agency":
                    raw.setdefault(e.value, e.raw)
        reps.append(Rep(r["id"], r["kind"], datetime.fromisoformat(r["received_at"]), r["text"], r["destination_country"],
                        r["amount_lost"], dict(ents), raw))
    return reps, truth


def test_generator_is_deterministic_and_hides_the_answer_key():
    a, ta = generate()
    b, tb = generate()
    assert a == b and ta == tb
    assert len(a) == 275 and sum(v is None for v in ta.values()) == 45
    assert all("OP-" not in r["text"] and "OP-" not in r["id"] for r in a)


def test_linking_quality_on_the_synthetic_set():
    reps, _ = reps_from_synthetic()
    out = offline_report(reps, Settings(_env_file=None))
    assert out["rules_only"]["precision"] == 1.0
    assert out["rules_only"]["recall"] >= 0.70
    assert out["rules_plus_suggestions"]["precision"] >= 0.99
    assert out["rules_plus_suggestions"]["f1"] >= 0.95
    assert out["suggestions"]["correct"] > out["suggestions"]["wrong"]


def test_extraction_finds_every_injected_identifier():
    reports, _ = generate()
    scores = extraction_scores(reports)
    assert scores["recall"] == 1.0 and scores["precision"] == 1.0
    assert scores["identifiers_injected"] > 400
