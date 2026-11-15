"""LLM-4 / C10: check an LLM on the validation summaries. Writes ml/out/llm_eval.json.

    python -m ml.llm_eval                      # the LLM from LLM_* variables
    python -m ml.llm_eval --data data/llm/valid.jsonl --limit 100

For every validation summary the model is asked exactly as the backend asks it,
and the answer goes through the backend's own check. Reports the share of
accepted answers, why the others were rejected, and the response time.
Rule from PLAN (LLM-4): below 98 % accepted, the demo stays on templates.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

from ml.paths import DATA, OUT
from vigil.llm import create_provider, explain, get_llm_settings
from vigil.llm.provider import LLMError

THRESHOLD = 0.98


async def run(rows: list[dict], concurrency: int) -> list[dict]:
    # A batch run is started by a person on purpose: the hourly cap of the live
    # application does not apply here.
    provider = create_provider(
        get_llm_settings().model_copy(update={"max_calls_per_hour": 0})
    )
    if provider is None:
        raise SystemExit(
            "Set LLM_BASE_URL and LLM_MODEL (and usually LLM_API_KEY) first."
        )
    gate = asyncio.Semaphore(concurrency)

    async def ask(row: dict) -> dict:
        facts = json.loads(row["messages"][1]["content"])
        async with gate:
            started = time.monotonic()
            try:
                reply = await provider.chat(explain.messages(facts))
                bad = explain.problems(reply, facts)
            except LLMError as exc:
                reply, bad = None, [f"no answer: {exc}"]
            return {"seconds": time.monotonic() - started, "problems": bad,
                    "reply": reply and explain.clean(reply), "meta": row.get("meta", {})}  # fmt: skip

    results = await asyncio.gather(*(ask(r) for r in rows))
    print("spent:", provider.usage())
    await provider.aclose()
    return list(results)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", type=Path, default=DATA / "llm" / "valid.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="use only the first N rows")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args(argv)

    rows = [
        json.loads(line) for line in args.data.read_text().splitlines() if line.strip()
    ]
    rows = rows[: args.limit] if args.limit else rows
    results = asyncio.run(run(rows, args.concurrency))

    ok = [r for r in results if not r["problems"]]
    reasons: dict[str, int] = {}
    for r in results:
        for p in r["problems"]:
            key = p.split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
    times = sorted(r["seconds"] for r in results)
    share = len(ok) / len(results)
    report = {
        "rows": len(results), "accepted": len(ok), "accepted_share": round(share, 4),
        "threshold": THRESHOLD, "use_llm_in_demo": share >= THRESHOLD,
        "rejected_by_reason": reasons,
        "seconds_median": round(statistics.median(times), 2),
        "seconds_p95": round(times[int(0.95 * (len(times) - 1))], 2),
        "examples_rejected": [r for r in results if r["problems"]][:5],
    }  # fmt: skip
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "llm_eval.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "examples_rejected"}, indent=1
        )
    )
    print("Verdict:", "the LLM may be used" if report["use_llm_in_demo"]
          else f"below {THRESHOLD:.0%}: keep the templates")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
