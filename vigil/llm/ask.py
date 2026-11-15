"""Ask Vigil: a crew member asks a question about their own record.

The model does not detect anything, does not diagnose and does not choose steps.
It gets a short record of what the system already knows about this one person
(current readings and their usual ranges, the last hour, alerts of the last 24
hours, sleep, check-in) and answers from it. As with alert explanations, the
answer is shown only if every number in it is in the record or in the question
and no alert pattern is named that the record does not contain; otherwise a fixed
sentence is shown instead.
"""

import json
import logging
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from vigil.backend import views
from vigil.backend.hub import CrewRuntime
from vigil.backend.narrate import METRIC, PATTERN_LABEL, _bound, _minutes
from vigil.backend.serialize import LEVEL_NAMES
from vigil.core import thresholds as th
from vigil.core.context import Ctx
from vigil.core.pipeline import Incident
from vigil.llm.config import LLMSettings
from vigil.llm.explain import _numbers, clean
from vigil.llm.provider import LLMError, LLMProvider

log = logging.getLogger("vigil.llm")

MAX_QUESTION_CHARS = 300
MIN_ANSWER_CHARS, MAX_ANSWER_CHARS = 10, 800
HISTORY_PAIRS = 3  # earlier question/answer pairs sent along with a new question
PAST_ALERTS = 5
PAST_WINDOW_S = 86400

# Sent with every question, followed by the record.
SYSTEM_PROMPT = (
    "You are Ask Vigil. You answer an astronaut's questions about their own "
    "health-monitoring record, which is given below as JSON. Answer only from the "
    "record. If the record does not contain the answer, say that it is not in the "
    "record. Do not diagnose and do not give medical advice; the only steps you may "
    "mention are the ones listed in an alert of the record. Do not say that a reading "
    "is abnormal unless the record says so. Use only numbers that appear in the "
    "record or in the question, exactly as written, and write counts as words. "
    "Answer in one to four plain English sentences: no lists, no headings, no quotes."
)

FALLBACK = {
    "rejected": "I could not give an answer that matches your record exactly, so I "
    "am not showing it. Your readings and alerts are on the Today page.",
    "unavailable": "The language model did not answer. Your readings and alerts are "
    "on the Today page.",
    "cap": "Ask Vigil has reached its hourly limit. Your readings and alerts are on "
    "the Today page.",
}

# lower-case name, unit, digits
READING = {m: (v[1], v[2], v[3]) for m, v in METRIC.items()} | {
    "amb_t": ("cabin air temperature", "°C", 1)
}
STATE_WORD = {
    "sleep": "asleep",
    "rest": "resting",
    "active": "exercising",
    "off": "wristband not worn",
}
LAST_HOUR = ("hr", "spo2", "rr", "skin_t", "ppco2")


def _val(value: float | None, m: str) -> str | None:
    if value is None:
        return None
    _, unit, digits = READING[m]
    return f"{value:.{digits}f} {unit}"


def _range(lo: float, hi: float, m: str) -> str:
    if m in METRIC:
        return f"{_bound(lo, m)}–{_bound(hi, m)} {READING[m][1]}"
    return f"{_val(lo, m)}–{_val(hi, m)}"


def _when(ts: int, now: int) -> str:
    """Clock time of an event; nothing in the record is older than a few days."""
    text = datetime.fromtimestamp(ts, UTC).strftime("%H:%M") + " GMT"
    days = now // 86400 - ts // 86400
    if days == 1:
        return "yesterday " + text
    return text if days <= 0 else f"{_days_word(days)} days ago, {text}"


def _days_word(n: int) -> str:
    words = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight")
    return words[n] if n < len(words) else "several"


def _reading(rt: CrewRuntime, m: str) -> dict[str, Any]:
    card = views.card(rt, m)
    item: dict[str, Any] = {
        "reading": READING[m][0],
        "value": _val(card["value"], m) or "no reading",
        "status": card["state"].replace("_", " "),
    }
    if card.get("usual"):
        item["usual_range"] = _range(*card["usual"], m)
    if m == "spo2":
        item["critical_at_or_below"] = _val(th.SPO2_CRITICAL_MAX, m)
    elif m == "ppco2":
        item["limit"] = _val(th.PPCO2_WATCH, m)
    return item


def _last_hour(rt: CrewRuntime) -> list[dict[str, Any]]:
    out = []
    for m in LAST_HOUR:
        values = [row[m] for row in rt.recent if row.get(m) is not None]
        if values:
            out.append({"reading": READING[m][0], "lowest": _val(min(values), m),
                        "highest": _val(max(values), m)})  # fmt: skip
    return out


def _alert(inc: Incident, now: int) -> dict[str, Any]:
    text = inc.text or {}
    end = inc.ts_end if inc.ts_end is not None else inc.ts_update
    item = {
        "status": "open" if inc.ts_end is None else "ended",
        "level": LEVEL_NAMES[inc.level] if inc.ts_end is None else None,
        "highest_level": LEVEL_NAMES[inc.peak_level],
        "pattern": PATTERN_LABEL.get(inc.pattern or ""),
        "started": _when(inc.ts_start, now),
        "duration": _minutes((end - inc.ts_start) // 60),
        "acknowledged": inc.ack_ts is not None,
        "what": text.get("what"),
        "why": text.get("why"),
        "steps": text.get("action") or None,
    }
    return {k: v for k, v in item.items() if v is not None}


def _sleep(rt: CrewRuntime, nights: list[dict[str, Any]], now: int) -> dict[str, Any]:
    asleep_now = views.current_ctx(rt) == Ctx.SLEEP
    # A night still in progress is not a recorded night yet (as on the Sleep page).
    done = [n for n in nights if not asleep_now or n is not nights[-1]][-7:]
    out: dict[str, Any] = {"asleep_now": asleep_now}
    if done:
        last = done[-1]
        out["last_night"] = {
            "fell_asleep": _when(last["onset_ts"], now),
            "woke": _when(last["wake_ts"], now),
            "asleep": _minutes(last["asleep_min"]),
        }
        if last["awake_min"]:
            out["last_night"]["awake_in_between"] = _minutes(last["awake_min"])
        out["mean_of_recorded_nights"] = _minutes(views.sleep_mean(done))
    else:
        out["last_night"] = "no night recorded yet"
    return out


def _wristband(rt: CrewRuntime) -> str:
    d = views.device_brief(rt)
    if d["link"] == "no_link":
        return "no link to the wristband"
    if d["worn"] is False:
        return "connected, not worn"
    parts = ["connected", "worn"]
    if d["signal"]:
        parts.append(f"signal {d['signal']}")
    if d["batt"] is not None:
        parts.append(f"battery {d['batt']} %")
    return ", ".join(parts)


def record(
    rt: CrewRuntime, nights: list[dict[str, Any]], past: list[Incident]
) -> dict[str, Any] | None:
    """What the model sees: one person's record, without a name or an id.
    `past` are this person's incidents of the last 24 hours, oldest first."""
    now = rt.now_ts
    if now is None:
        return None
    ctx = views.current_ctx(rt)
    base = views.baseline_json(rt, with_pct=False)
    filed = views.checkin_today(rt)
    open_inc = rt.state.incident
    alerts = [_alert(open_inc, now)] if open_inc is not None else []
    ended = [i for i in past if i.ts_end is not None and i.key == "incident"]
    alerts += [_alert(i, now) for i in reversed(ended[-PAST_ALERTS:])]
    return {
        "time_now": _when(now, now),
        "flight_day": views.flight_day(rt),
        "state_now": STATE_WORD.get(ctx.label) if ctx is not None else None,
        "overall_level": LEVEL_NAMES[rt.state.level],
        "personal_baseline": "learned"
        if base["state"] == "learned"
        else f"still learning, day {base['day']} of {base['of']}",
        "wristband": _wristband(rt),
        "readings_now": [_reading(rt, m) for m, _ in (*views.VITALS, *views.CABIN)],
        "last_hour": _last_hour(rt),
        "alerts_last_24_hours": alerts or "none",
        "sleep": _sleep(rt, nights, now),
        "checkin_today": f"filed at {_when(filed, now)}" if filed else "not filed",
    }


def _history(raw: Any) -> list[dict[str, str]]:
    """Earlier question/answer pairs from the client: only well-formed pairs,
    only the last few, each cut to the length a real one can have."""
    items = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("content"), str):
            continue
        role, content = item.get("role"), " ".join(item["content"].split())
        if role in ("user", "assistant") and content:
            limit = MAX_QUESTION_CHARS if role == "user" else MAX_ANSWER_CHARS
            items.append({"role": role, "content": content[:limit]})
    pairs = [
        (a, b)
        for a, b in zip(items, items[1:], strict=False)
        if a["role"] == "user" and b["role"] == "assistant"
    ]
    return [m for pair in pairs[-HISTORY_PAIRS:] for m in pair]


def messages(
    record_: dict[str, Any], question: str, history: Any = None
) -> list[dict[str, str]]:
    system = f"{SYSTEM_PROMPT}\n\nRecord:\n{json.dumps(record_, ensure_ascii=False)}"
    return [
        {"role": "system", "content": system},
        *_history(history),
        {"role": "user", "content": question},
    ]


def problems(reply: str, record_: dict[str, Any], question: str) -> list[str]:
    """Reasons to reject the model's answer; empty list = accepted."""
    text = clean(reply)
    known = json.dumps(record_, ensure_ascii=False) + " " + question
    found = []
    if not MIN_ANSWER_CHARS <= len(text) <= MAX_ANSWER_CHARS:
        found.append(
            f"length {len(text)} outside {MIN_ANSWER_CHARS}–{MAX_ANSWER_CHARS}"
        )
    extra = _numbers(text) - _numbers(known)
    if extra:
        found.append(f"numbers not in the record: {sorted(extra)}")
    lowered, known = text.lower(), known.lower()
    for label in PATTERN_LABEL.values():
        if label.lower() in lowered and label.lower() not in known:
            found.append(f"names a pattern that is not in the record: {label}")
    if text.startswith(("{", "[", "-", "*", "#")):
        found.append("not plain sentences")
    return found


class Asker:
    """Asks the model, checks the answer, and keeps Ask Vigil inside its own
    hourly cap. Always returns something that can be shown."""

    def __init__(self, llm: LLMProvider, max_per_hour: int, max_tokens: int) -> None:
        self.llm = llm
        self.max_per_hour = max_per_hour
        self.max_tokens = max_tokens
        self._calls: deque[float] = deque()  # start times of recent questions

    def _within_cap(self) -> bool:
        now = time.monotonic()
        while self._calls and now - self._calls[0] > 3600:
            self._calls.popleft()
        if len(self._calls) >= self.max_per_hour:
            return False
        self._calls.append(now)
        return True

    async def answer(
        self, record_: dict[str, Any], question: str, history: Any = None
    ) -> dict[str, Any]:
        if not self._within_cap():
            log.warning("ask not sent: %d questions in the last hour "
                        "(LLM_ASK_MAX_CALLS_PER_HOUR)", self.max_per_hour)  # fmt: skip
            return _fallback("cap")
        try:
            reply = await self.llm.chat(
                messages(record_, question, history), max_tokens=self.max_tokens
            )
        except LLMError:
            return _fallback("unavailable")  # logged by the provider
        except Exception:
            log.exception("ask: llm call failed unexpectedly")
            return _fallback("unavailable")
        bad = problems(reply, record_, question)
        if bad:
            log.warning("ask: answer rejected (%s)", "; ".join(bad))
            return _fallback("rejected")
        return {"answer": clean(reply), "src": "llm"}


def _fallback(reason: str) -> dict[str, Any]:
    return {"answer": FALLBACK[reason], "src": "none", "reason": reason}


def create_asker(llm: LLMProvider | None, settings: LLMSettings) -> Asker | None:
    """Ask Vigil for the configured provider, or None when it is switched off."""
    if llm is None or settings.ask_max_calls_per_hour <= 0:
        return None
    return Asker(llm, settings.ask_max_calls_per_hour, settings.ask_max_tokens)
