"""Measure CaseLink on the synthetic dataset and write eval/results.md and eval/results.json.

    python -m eval.run_eval              # rules, suggestions, extraction (no API calls)
    python -m eval.run_eval --with-ai    # also asks the AI for a second opinion on every suggestion

The dataset and its answer key come from app/data/synthetic.py (seeded, so every run is the same).
The answer key is used only here, never by the linker.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.llm import build_model_chains, check_models, model_label  # noqa: E402
from app.ai.model_status import seconds_until_free  # noqa: E402
from app.config import Settings  # noqa: E402
from app.core.aio import run  # noqa: E402
from app.data.synthetic import generate  # noqa: E402
from app.extract.rules import extract  # noqa: E402
from app.intel.quality import extraction_scores, merged_with_suggestions, pairwise  # noqa: E402
from app.link.linker import Rep, link_all  # noqa: E402

HERE = Path(__file__).resolve().parent


def build_reps(reports):
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
    return reps


def suggestion_truth(s, truth) -> bool:
    ops = {truth[r] for g in s.groups for r in g}
    return len(ops) == 1 and None not in ops


async def ai_opinions(settings, suggestions, reports_by_id, pace: float) -> list[dict]:
    from app.ai.agents import adjudicate

    for change in await check_models(settings):
        print(f"Model check: {change}.", flush=True)
    models, _ = build_model_chains(settings)
    out = []
    for i, s in enumerate(suggestions):
        if i and pace:
            await asyncio.sleep(pace)
        wait = seconds_until_free(models)
        if wait:
            await asyncio.sleep(min(wait, 120) + 1)
        side = [sorted(g) for g in s.groups if g]
        if len(side) == 1:
            half = max(1, len(side[0]) // 2)
            side = [side[0][:half], side[0][half:]]

        def objs(ids):
            return [SimpleNamespace(id=x, text=reports_by_id[x]["text"], reporter_city=reports_by_id[x]["reporter_city"],
                                    received_at=datetime.fromisoformat(reports_by_id[x]["received_at"])) for x in ids]

        res = await adjudicate(models, settings.llm_timeout_seconds, objs(side[0]), objs(side[1]), s.reasons)
        out.append({"verdict": res.get("verdict"), "model": res.get("model")})
        print(f"  second opinion {i + 1}/{len(suggestions)}: {res.get('verdict')}", flush=True)
    return out


def fmt(x: float) -> str:
    return f"{x * 100:.1f}%"


async def main(args) -> None:
    started = time.time()
    reports, truth = generate()
    reps = build_reps(reports)
    settings = Settings()
    res = link_all(reps, settings.hub_share, settings.hub_min_reports, settings.name_min_length)
    rules = pairwise(res.components, truth)
    plus = pairwise(merged_with_suggestions(res, 0.5), truth)
    everything = pairwise(merged_with_suggestions(res, 0.0), truth)
    right = [suggestion_truth(s, truth) for s in res.suggestions]
    extraction = extraction_scores(reports)
    per_op = {}
    owner = {rid: i for i, c in enumerate(res.components) for rid in c}
    for op in sorted({v for v in truth.values() if v}):
        members = [r for r, v in truth.items() if v == op]
        per_op[op] = sorted(Counter(owner[m] for m in members).values(), reverse=True)

    ai = None
    if args.with_ai:
        keyed = Settings()
        if keyed.resolved_llm_provider == "none":
            sys.exit("--with-ai needs GROQ_API_KEY or GOOGLE_API_KEY in .env")
        by_id = {r["id"]: r for r in reports}
        opinions = await ai_opinions(keyed, res.suggestions, by_id, args.pace)
        agree = sum(1 for o, ok in zip(opinions, right, strict=True) if o["verdict"] == ("same" if ok else "different"))
        answered = sum(1 for o in opinions if o["verdict"] in ("same", "different"))
        accepted = [s for s, o in zip(res.suggestions, opinions, strict=True) if o["verdict"] == "same"]
        res_ai = SimpleNamespace(components=res.components, suggestions=accepted)
        ai = {"model": model_label(keyed), "answered": answered, "unsure_or_failed": len(opinions) - answered,
              "agrees_with_answer_key": agree, "suggestions": len(opinions),
              "accept_where_ai_says_same": pairwise(merged_with_suggestions(res_ai, 0.0), truth)}

    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": {"reports": len(reports), "operations": len(per_op), "one_off_reports": sum(v is None for v in truth.values())},
        "extraction": extraction,
        "rules_only": rules,
        "rules_plus_suggestions_0_5": plus,
        "rules_plus_all_suggestions": everything,
        "suggestions": {"total": len(right), "correct": sum(right), "wrong": len(right) - sum(right),
                        "by_kind": dict(Counter(s.kind for s in res.suggestions))},
        "groups_per_operation": per_op,
        "seconds": round(time.time() - started, 2),
    }
    if ai:
        summary["ai_second_opinion"] = ai
    (HERE / "results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    lines = ["# CaseLink evaluation", "",
             f"Synthetic dataset: {len(reports)} reports from {len(per_op)} operations plus {summary['dataset']['one_off_reports']} "
             "unrelated one-off reports. The data and its answer key are generated by `app/data/synthetic.py` with a fixed seed. "
             "I wrote the generator, so these numbers show the pipeline works as designed; they are not a benchmark on real cases.",
             "", "Pairwise scoring: precision is the share of report pairs put in one case that really belong to one operation; "
             "recall is the share of same-operation pairs that ended up together.", "",
             "| Set-up | Precision | Recall | F1 | Pairs put together |", "|---|---|---|---|---|"]
    for name, m in (("Rules only (automatic)", rules), ("Rules + suggestions scoring ≥ 0.5 accepted", plus),
                    ("Rules + every suggestion accepted", everything)):
        lines.append(f"| {name} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} | {m['pairs_predicted']} |")
    if ai:
        m = ai["accept_where_ai_says_same"]
        lines.append(f"| Rules + suggestions the AI called 'same' | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} | {m['pairs_predicted']} |")
    lines += ["", f"Suggestions: {len(right)} ({sum(right)} correct, {len(right) - sum(right)} wrong). "
              "The wrong ones are reports that share a common agency name such as \"Prime\" or \"Falcon\"; "
              "they are scored low and wait for a person.", ""]
    if ai:
        lines += [f"AI second opinion ({ai['model']}): answered {ai['answered']} of {ai['suggestions']}, "
                  f"agreed with the answer key on {ai['agrees_with_answer_key']}.", ""]
    lines += ["Extraction (identifiers the generator put into the text, written in many formats):", "",
              f"- precision {fmt(extraction['precision'])}, recall {fmt(extraction['recall'])} "
              f"({extraction['identifiers_found']} found, {extraction['identifiers_injected']} injected)"]
    for kind, v in sorted(extraction["by_kind"].items()):
        lines.append(f"- {kind}: {v['found']} of {v['injected']}")
    lines += ["", "Groups each operation was split into by the rules alone (one group is perfect; the rest are "
              "walk-in reports with no identifier, or phone numbers changed without a bridge):", ""]
    lines += [f"- {op}: {groups}" for op, groups in per_op.items()]
    (HERE / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Evaluate CaseLink on the synthetic dataset")
    p.add_argument("--with-ai", action="store_true", help="also ask the AI for a second opinion on each suggestion")
    p.add_argument("--pace", type=float, default=3.0, help="seconds between AI calls")
    run(main(p.parse_args()))
