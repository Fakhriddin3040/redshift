"""LLM-1: dataset for fine-tuning the alert explainer (PLAN §11.4).
Writes chat-format JSONL: one {"messages": [system, user, assistant]} per line.

    python -m ml.llm_dataset                         # teacher = templates
    python -m ml.llm_dataset --teacher provider      # teacher = the LLM from LLM_* variables
    python -m ml.llm_dataset --out data/llm --seeds 8

Inputs are alert summaries produced by the simulator: every incident scenario x
severity x crew profile, captured each time the alert reaches a new level. The
target is the "why" sentence, written by the teacher. Every pair must pass the
same check the backend applies to a live answer (vigil/llm/explain.py); pairs
that fail are dropped. 90 % train, 10 % validation, split by a fixed seed.

A dataset written by a teacher model is AI-generated data: say so in docs/AI_USE.md.
"""

import argparse
import asyncio
import copy
import json
import random
import sys
from pathlib import Path

from ml.eval_scenarios import to_minute
from ml.paths import DATA
from vigil.backend.narrate import load_actions, template_text
from vigil.core.features import WINDOW_MIN, features
from vigil.core.pattern_model import PatternModel
from vigil.core.pipeline import CrewState
from vigil.llm import create_provider, explain, get_llm_settings
from vigil.llm.provider import LLMError
from vigil.vdev.signal import PROFILES, Cabin, CrewSim, make_scenario

START_MIN = 1_794_700_800 // 60
LEARN_DAYS = 10
SCENARIOS = ("hypoxia", "tachycardia_rest", "bradycardia", "fever_like",
             "hypercapnia", "depressurization")  # fmt: skip
START_OFFSETS_MIN = (9 * 60 + 30, 12 * 60, 15 * 60 + 20)  # awake, at rest
WATCH_MIN = 75
SPLIT_SEED, VALID_SHARE = 2026, 0.10


def summaries(seeds: int, actions: dict, model: PatternModel | None) -> list[dict]:
    """(summary, template why) for every level an incident reaches."""
    out = []
    for seed in range(seeds):
        for profile in PROFILES:
            sim, cabin, state = CrewSim(profile, seed), Cabin(seed), CrewState()
            learned_until = START_MIN + LEARN_DAYS * 1440
            window = []
            for minute in range(START_MIN, learned_until + max(START_OFFSETS_MIN)):
                res = state.on_minute(
                    to_minute(
                        minute * 60,
                        sim.minute_sample(minute),
                        cabin.sample(minute * 60),
                    )
                )
                window = [*window, res][-WINDOW_MIN:]
                offset = minute + 1 - learned_until
                if offset not in START_OFFSETS_MIN:
                    continue
                rng = random.Random(seed * 1009 + profile.crew * 31 + offset)
                for name in SCENARIOS:
                    severity = rng.randint(1, 3)
                    out += one_incident(
                        copy.deepcopy((sim, cabin, state, window)), profile.crew,
                        minute + 1, name, severity, rng, actions, model,
                    )  # fmt: skip
    return out


def one_incident(
    snapshot, crew, start_min, name, severity, rng, actions, model
) -> list[dict]:
    sim, cabin, state, window = snapshot
    scn = [make_scenario(name, crew, start_min * 60, rng, severity)]
    rows, peak = [], 0
    for minute in range(start_min, start_min + WATCH_MIN):
        res = state.on_minute(
            to_minute(minute * 60, sim.minute_sample(minute, scn),
                      cabin.sample(minute * 60 + 30, scn))
        )  # fmt: skip
        window = [*window, res][-WINDOW_MIN:]
        if res.level <= peak:
            continue
        peak, inc = res.level, res.incident
        if model is not None:  # name the pattern the way the backend does
            guess, p = model.predict(features(window))
            if guess != "normal" and p >= 0.5:
                inc.pattern, inc.p = guess, p
        facts, text = explain.summary(inc), template_text(inc, actions)
        if facts and text:
            rows.append({"summary": facts, "template_why": text["why"],
                         "scenario": name, "severity": severity})  # fmt: skip
    return rows


async def teach(rows: list[dict], teacher: str, concurrency: int) -> list[dict]:
    if teacher == "template":
        for r in rows:
            r["why"] = r["template_why"]
        return rows
    # A batch run is started by a person on purpose: the hourly cap of the live
    # application does not apply here.
    provider = create_provider(
        get_llm_settings().model_copy(update={"max_calls_per_hour": 0})
    )
    if provider is None:
        raise SystemExit(
            "--teacher provider needs LLM_BASE_URL and LLM_MODEL (and usually LLM_API_KEY)."
        )
    gate = asyncio.Semaphore(concurrency)

    async def ask(r: dict) -> None:
        async with gate:
            try:
                r["why"] = explain.clean(
                    await provider.chat(explain.messages(r["summary"]))
                )
            except LLMError as exc:
                r["error"] = str(exc)

    await asyncio.gather(*(ask(r) for r in rows))
    await provider.aclose()
    return rows


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--teacher", choices=("template", "provider"), default="template")
    ap.add_argument("--out", type=Path, default=DATA / "llm")
    ap.add_argument(
        "--seeds", type=int, default=6, help="generator seeds; more seeds = more pairs"
    )
    ap.add_argument(
        "--concurrency", type=int, default=4, help="parallel teacher requests"
    )
    ap.add_argument("--actions", default="docs/actions.yaml")
    ap.add_argument("--pattern-model", default="ml/models/pattern.json")
    args = ap.parse_args(argv)

    rows = summaries(
        args.seeds, load_actions(args.actions), PatternModel.load(args.pattern_model)
    )
    rows = asyncio.run(teach(rows, args.teacher, args.concurrency))

    kept, dropped = [], {"teacher error": 0, "failed the check": 0}
    for r in rows:
        if "why" not in r:
            dropped["teacher error"] += 1
        elif explain.problems(r["why"], r["summary"]):
            dropped["failed the check"] += 1
        else:
            kept.append({
                "messages": [*explain.messages(r["summary"]),
                             {"role": "assistant", "content": r["why"]}],
                "meta": {"scenario": r["scenario"], "severity": r["severity"],
                         "level": r["summary"]["level"], "teacher": args.teacher},
            })  # fmt: skip
    random.Random(SPLIT_SEED).shuffle(kept)
    n_valid = max(1, round(len(kept) * VALID_SHARE))
    args.out.mkdir(parents=True, exist_ok=True)
    for name, part in (("valid", kept[:n_valid]), ("train", kept[n_valid:])):
        with open(args.out / f"{name}.jsonl", "w") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in part)
    by = {}
    for x in kept:
        key = f"{x['meta']['scenario']}/{x['meta']['level']}"
        by[key] = by.get(key, 0) + 1
    print(f"{len(rows)} summaries, {len(kept)} pairs kept, dropped: {dropped}")
    print(
        f"train {len(kept) - n_valid}, valid {n_valid} -> {args.out}/train.jsonl, valid.jsonl"
    )
    print("by scenario/level:", dict(sorted(by.items())))
    return 0 if kept else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
