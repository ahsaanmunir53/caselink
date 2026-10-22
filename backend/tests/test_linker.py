from datetime import UTC, datetime

from app.link.linker import Rep, common_identifiers, key_identifiers, link_all, pair

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def rep(rid, text="", **entities):
    agency_raw = entities.pop("agency_raw", {})
    return Rep(rid, "overseas_job", NOW, text, None, 1000, {k: set(v) for k, v in entities.items()}, agency_raw)


def test_shared_identifiers_link_and_others_do_not():
    reps = [rep("R-1", phone=["+923001111111"]), rep("R-2", phone=["+923001111111"], iban=["PK1"]),
            rep("R-3", iban=["PK1"]), rep("R-4", phone=["+923009999999"])]
    res = link_all(reps)
    assert res.components[0] == frozenset({"R-1", "R-2", "R-3"})
    assert frozenset({"R-4"}) in res.components


def test_a_number_in_many_reports_is_common_and_links_nothing():
    reps = [rep(f"R-{i}", phone=["+923000000000"]) for i in range(20)] + [rep("R-x", phone=["+923001234567"])]
    assert ("phone", "+923000000000") in common_identifiers(reps, 0.08, 12)
    assert all(len(c) == 1 for c in link_all(reps).components)


def test_rejected_pairs_are_never_linked_again():
    reps = [rep("R-1", phone=["+923001111111"]), rep("R-2", phone=["+923001111111"])]
    assert len(link_all(reps).components) == 1
    assert len(link_all(reps, rejected={pair("R-1", "R-2")}).components) == 2


def test_names_only_suggest_and_common_names_score_low():
    reps = [rep("R-1", "Al Noor Overseas took money", agency=["alnoor"], phone=["+923001111111"]),
            rep("R-2", "AlNoor Manpower", agency=["alnoor"], phone=["+923001111111"]),
            rep("R-3", "Walk-in: Al Noor Overseas office took cash", agency=["alnoor"]),
            rep("R-4", "Prime Overseas", agency=["prime"]), rep("R-5", "Prime Manpower", agency=["prime"])]
    res = link_all(reps)
    assert frozenset({"R-1", "R-2"}) in res.components  # the name alone never merges
    kinds = {(s.kind, s.reasons[0]["detail"]): s.score for s in res.suggestions}
    assert kinds[("attach", "agency:alnoor")] == 0.8
    assert kinds[("new_case", "agency:prime")] == 0.35


def test_abbreviation_and_name_list():
    reps = [rep("R-1", "Kuala Lumpur Manpower Services", agency=["kualalumpur"], agency_raw={"kualalumpur": "Kuala Lumpur Manpower Services"},
                phone=["+923001111111"]),
            rep("R-2", "KL Manpower", agency=["kl"], agency_raw={"kl": "KL Manpower"}),
            rep("R-3", "Doha Link Recruiting", agency=["dohalink"]), rep("R-4", "DohaLink Recruitment", agency=["dohalink"]),
            rep("R-5", "complaint against Doha Link, cash taken")]
    res = link_all(reps)
    assert "dohalink" in res.name_list.get("R-5", [])
    details = {r["detail"] for s in res.suggestions for r in s.reasons}
    assert "agency:kl=kualalumpur" in details


def test_bridge_identifier():
    reps = {r.id: r for r in [rep("R-1", phone=["A"]), rep("R-2", phone=["A", "B"]), rep("R-3", phone=["B"]), rep("R-4", phone=["B"])]}
    keys = {k["value"]: k for k in key_identifiers(set(reps), reps, set())}
    assert keys["A"]["bridge"] and keys["B"]["bridge"]
    reps["R-3"].entities["iban"] = {"X"}
    reps["R-1"].entities["iban"] = {"X"}
    keys = {k["value"]: k for k in key_identifiers(set(reps), reps, set())}
    assert not keys["A"]["bridge"]
