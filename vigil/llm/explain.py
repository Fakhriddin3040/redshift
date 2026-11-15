"""Alert explanation: what the model is asked, and how its answer is checked.

The model does not detect anything and does not choose actions. It gets a short
summary of an alert that the rules have already raised and writes the "why"
sentence. The answer is used only if every number in it is in the summary;
otherwise the template text stays. The same summary, prompt and check are used
by the backend, by the dataset builder and by the evaluation script.
"""

import json
import re
from typing import Any

from vigil.backend.narrate import (
    CTX_WORD,
    METRIC,
    PATTERN_LABEL,
    _bound,
    _direction,
    _num,
)
from vigil.backend.serialize import LEVEL_NAMES
from vigil.core.pipeline import Incident

MAX_WHY_CHARS = 420
MIN_WHY_CHARS = 20
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

# Kept short on purpose: it is sent with every request.
SYSTEM_PROMPT = (
    "You explain a health-monitoring alert to an astronaut. The user message is a JSON "
    "summary of an alert already raised by fixed rules. In one or two plain English "
    "sentences say why it was raised: which reading is out of range, how it compares "
    "with the usual range, and what the other readings are doing. Use only numbers "
    "from the summary, exactly as written. No advice, no diagnosis, no lists, no quotes."
)


def _value(value: float | None, m: str) -> str | None:
    return None if value is None else f"{_num(value, m)} {METRIC[m][2]}"


def summary(inc: Incident) -> dict[str, Any] | None:
    """What the model sees. No names, no ids, no timestamps: only the alert itself."""
    primary = inc.primary
    if inc.key != "incident" or primary not in METRIC:
        return None
    metrics = []
    for im in inc.metrics.values():
        if im.m not in METRIC:
            continue
        item: dict[str, Any] = {
            "reading": METRIC[im.m][1],
            "value": _value(im.value, im.m),
            "trend": im.trend,
        }
        if im.usual:
            item["usual_range"] = (
                f"{_bound(im.usual[0], im.m)}–{_bound(im.usual[1], im.m)} {METRIC[im.m][2]}"
            )
        if im.m == primary:
            item["direction"] = _direction(im)
            item["minutes"] = max(1, im.since_min)
        metrics.append(item)
    ctx = inc.ctx.label if inc.ctx is not None else None
    return {
        "level": LEVEL_NAMES[inc.level],
        "pattern": PATTERN_LABEL.get(inc.pattern or ""),
        "judged_against": "fixed safety limit"
        if inc.source in ("hard", "env")
        else "the person's own usual range",
        "state": CTX_WORD.get(ctx),
        "readings": metrics,
    }


def messages(summary_: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(summary_, ensure_ascii=False)},
    ]


def _numbers(text: str) -> set[float]:
    return {float(n.replace(",", ".")) for n in NUMBER.findall(text)}


def clean(reply: str) -> str:
    text = " ".join(reply.split())
    text = re.sub(r"^(why|explanation)\s*:\s*", "", text, flags=re.IGNORECASE)
    return text.strip().strip('"“”').strip()


def problems(reply: str, summary_: dict[str, Any]) -> list[str]:
    """Reasons to reject the model's answer; empty list = accepted."""
    text = clean(reply)
    found = []
    if not MIN_WHY_CHARS <= len(text) <= MAX_WHY_CHARS:
        found.append(f"length {len(text)} outside {MIN_WHY_CHARS}–{MAX_WHY_CHARS}")
    extra = _numbers(text) - _numbers(json.dumps(summary_, ensure_ascii=False))
    if extra:
        found.append(f"numbers not in the summary: {sorted(extra)}")
    lowered = text.lower()
    own = summary_.get("pattern")
    for label in PATTERN_LABEL.values():
        if label != own and label.lower() in lowered:
            found.append(f"names another pattern: {label}")
    if text.startswith(("{", "[", "-", "*", "#")):
        found.append("not plain sentences")
    return found
