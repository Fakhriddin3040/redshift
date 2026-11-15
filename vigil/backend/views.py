import time
from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any

from vigil.backend.hub import CrewRuntime
from vigil.backend.serialize import LEVEL_NAMES, alert_json, r
from vigil.core import thresholds as th
from vigil.core.context import Ctx
from vigil.core.levels import hard_level

LINK_TIMEOUT_S = 10
VITALS = (("hr", "bpm"), ("spo2", "%"), ("rr", "br/min"), ("skin_t", "°C"))
CABIN = (("ppco2", "mmHg"), ("press", "hPa"), ("amb_t", "°C"))
UNITS = dict(VITALS + CABIN)
FRAME_FIELD = {
    "hr": "hr",
    "spo2": "spo2",
    "rr": "rr",
    "skin_t": "skin_t",
    "ppco2": "co2_ppm",
    "press": "press_hpa",
    "amb_t": "amb_t",
}
ROW_FIELD = {**FRAME_FIELD, "ppco2": "ppco2"}
CARD_LIMIT = {"spo2": th.SPO2_CRITICAL_MAX, "ppco2": th.PPCO2_WATCH}
METRIC_LIMITS = {
    "hr": [
        {"value": th.HR_CRITICAL_MIN, "kind": "critical_above"},
        {"value": th.HR_LOW_MAX, "kind": "critical_below"},
    ],
    "spo2": [{"value": th.SPO2_CRITICAL_MAX, "kind": "critical_below"}],
    "rr": [
        {"value": th.RR_CRITICAL_HIGH_MIN, "kind": "critical_above"},
        {"value": th.RR_CRITICAL_LOW_MAX, "kind": "critical_below"},
    ],
    "ppco2": [{"value": th.PPCO2_WATCH, "kind": "watch_above"}],
}
RANGES = {"1h": (3600, 60), "24h": (86400, 60), "7d": (7 * 86400, 600)}
TOPIC = {"ppco2": "co2", "press": "pressure"}
SPARK_MINUTES = 60


def signal(sqi: float | None) -> str | None:
    if sqi is None:
        return None
    if sqi >= 70:
        return "good"
    return "fair" if sqi >= 40 else "poor"


def current_value(rt: CrewRuntime, m: str) -> float | None:
    if rt.live_off and m in dict(VITALS):
        return None
    return rt.latest("ppco2" if m == "ppco2" else FRAME_FIELD[m])


def current_ctx(rt: CrewRuntime) -> Ctx | None:
    if rt.state.last is not None:
        return rt.state.last.ctx
    return Ctx(rt.recent[-1]["ctx"]) if rt.recent else None


def usual_band(rt: CrewRuntime, m: str) -> tuple[list[float] | None, bool]:
    if m not in dict(VITALS) or rt.now_ts is None:
        return None, False
    ctx = current_ctx(rt)
    if ctx in (None, Ctx.OFF):
        ctx = Ctx.REST
    lookup = rt.state.baseline.lookup(m, ctx, rt.now_ts)
    if lookup.learning or lookup.norm is None:
        return None, True
    digits = 2 if m == "skin_t" else 1
    return [r(lookup.norm.lo, digits), r(lookup.norm.hi, digits)], False


def card_state(rt: CrewRuntime, m: str) -> tuple[str, dict[str, Any]]:
    """State of one card, by the precedence of §11.2."""
    extra: dict[str, Any] = {}
    field = FRAME_FIELD[m]
    if field not in rt.dev.seen:
        return "not_measured", extra
    if current_value(rt, m) is None:
        since = [rt.dev.null_since.get(field)]
        if m in dict(VITALS):
            since += [rt.off_since, rt.dev.no_signal_since]
        extra["since_ts"] = min((s for s in since if s is not None), default=None)
        return "no_data", extra

    last = rt.state.last
    if m in ("ppco2", "press"):
        level = 0
        if last is not None:
            level = last.env.ppco2_level if m == "ppco2" else last.env.press_level
        return LEVEL_NAMES[level], extra
    if m == "amb_t":
        return "usual", extra
    if rt.is_off:
        # The wristband gives a reading again, but the last minute was still `off`:
        # no minute has judged this value yet. "learning" is the state that shows
        # the number without a verdict; the next closed minute replaces it.
        return "learning", extra

    ev = last.evals.get(m) if last else None
    if ev is not None:
        hard = ev.hard
    else:
        ctx = current_ctx(rt)
        hard = hard_level(m, rt.recent[-1].get(m), ctx) if rt.recent and ctx else 0
    if hard:
        return LEVEL_NAMES[hard], extra
    if m in ("hr", "rr") and current_ctx(rt) == Ctx.ACTIVE:
        return "exercising", extra
    _, learning = usual_band(rt, m)
    if learning:
        return "learning", extra
    if ev is not None and ev.z_level:
        return LEVEL_NAMES[ev.z_level], extra
    return "usual", extra


def spark(rt: CrewRuntime, m: str) -> list[float | None]:
    if rt.now_ts is None:
        return []
    end = rt.now_ts - rt.now_ts % 60
    by_ts = {row["ts"]: row.get(ROW_FIELD[m]) for row in rt.recent}
    return [r(by_ts.get(end - i * 60)) for i in range(SPARK_MINUTES - 1, -1, -1)]


def card(rt: CrewRuntime, m: str) -> dict[str, Any]:
    state, extra = card_state(rt, m)
    value = current_value(rt, m)
    out: dict[str, Any] = {
        "m": m,
        "value": r(value),
        "unit": UNITS[m],
        "state": state,
        **extra,
    }
    if m in dict(VITALS):
        usual, learning = usual_band(rt, m)
        out |= {"learning": learning, "usual": usual}
    out["limit"] = CARD_LIMIT.get(m)
    out["spark"] = spark(rt, m)
    if m in dict(VITALS):
        out["band"] = out["usual"]
    return out


def baseline_json(rt: CrewRuntime, with_pct: bool = True) -> dict[str, Any]:
    status = rt.state.baseline_status()
    out = {"state": status.state, "day": status.days, "of": th.LEARNED_DAYS}
    if with_pct:
        out["ready_pct"] = status.ready_pct
    return out


def device_brief(rt: CrewRuntime) -> dict[str, Any]:
    f = rt.dev.last_frame
    connected = (
        rt.dev.last_wall is not None
        and time.monotonic() - rt.dev.last_wall <= LINK_TIMEOUT_S
    )
    return {
        "link": "connected" if connected else "no_link",
        "worn": f.worn if f else None,
        "signal": signal(f.sqi) if f else None,
        "batt": f.batt if f else None,
    }


def flight_day(rt: CrewRuntime) -> int | None:
    if rt.first_day is None or rt.now_ts is None:
        return None
    return rt.now_ts // 86400 - rt.first_day + 1


RADIATION_SOURCE = "NASA OSDR Environmental Data App"
RADIATION_DAYS = 14


def radiation(days: list[dict[str, Any]]) -> dict[str, Any]:
    """Real ISS dose, measured in 2019. Never presented as today's value."""
    last = days[-RADIATION_DAYS:]
    totals = [d["total"] for d in last]
    span = f", RR-12, {days[0]['day']} to {days[-1]['day']}" if days else ""
    return {
        "unit": "mGy/day",
        "source": RADIATION_SOURCE + span,
        "measured_from": days[0]["day"] if days else None,
        "measured_to": days[-1]["day"] if days else None,
        "days": last,
        "last_24h": r(totals[-1], 3) if totals else None,
        "mean_14d": r(sum(totals) / len(totals), 3) if totals else None,
        "total_14d": r(sum(totals), 3) if totals else None,
    }


def sleep(rt: CrewRuntime, nights: list[dict[str, Any]]) -> dict[str, Any]:
    if not rt.share.get("sleep", True):
        return {"shared": False, "nights": [], "mean_7n_min": None, "asleep_now": False}
    asleep_now = current_ctx(rt) == Ctx.SLEEP
    # A night still in progress is not a recorded night yet.
    done = [n for n in nights if not asleep_now or n is not nights[-1]][-7:]
    return {
        "shared": True,
        "now_ts": rt.now_ts,
        "asleep_now": asleep_now,
        "nights": done,
        "mean_7n_min": sleep_mean(done),
    }


def sleep_mean(nights: list[dict[str, Any]]) -> int | None:
    last = nights[-7:]
    return round(sum(n["asleep_min"] for n in last) / len(last)) if last else None


def checkin_today(rt: CrewRuntime) -> int | None:
    if rt.now_ts is None:
        return None
    day = datetime.fromtimestamp(rt.now_ts, UTC).date().isoformat()
    return rt.checkins.get(day)


def today(
    rt: CrewRuntime,
    nights: list[dict[str, Any]] | None = None,
    radiation_days: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ctx = current_ctx(rt)
    last_night = nights[-1] if nights and rt.share.get("sleep", True) else None
    last_dose = radiation_days[-1] if radiation_days else None
    return {
        "now_ts": rt.now_ts,
        "flight_day": flight_day(rt),
        "level": rt.state.level,
        "critical_acked": rt.critical_acked,
        "ctx": ctx.label if ctx is not None else None,
        "baseline": baseline_json(rt),
        "device": device_brief(rt),
        "vitals": [card(rt, m) for m, _ in VITALS],
        "cabin": [card(rt, m) for m, _ in CABIN],
        "record": {
            "checkin": checkin_today(rt) and {"filed_ts": checkin_today(rt)},
            "sleep": last_night,
            "radiation": last_dose and {**last_dose, "unit": "mGy/day"},
            "report": None,
        },
        "notices": [alert_json(rt.id, n) for n in rt.open_alerts],
    }


def data_today_pct(rt: CrewRuntime) -> int | None:
    if rt.now_ts is None:
        return None
    day = rt.now_ts // 86400
    minutes = rt.data_minutes.get(day)
    if not minutes:
        return None
    elapsed = (rt.now_ts - day * 86400) // 60 + 1
    return min(100, round(100 * minutes / elapsed))


def crew_item(
    rt: CrewRuntime, nights: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    pct = data_today_pct(rt)
    inc = rt.state.incident
    topic = TOPIC.get(inc.primary, inc.primary) if inc and inc.primary else None
    return {
        "id": rt.id,
        "now_ts": rt.now_ts,
        "name": rt.name,
        "role": rt.role,
        "level": rt.state.level if pct is not None else None,
        "topic": topic,
        "baseline": baseline_json(rt, with_pct=False),
        "checkin_ts": checkin_today(rt)
        if rt.share.get("checkin", True)
        else "not_shared",
        "sleep_7n_mean_min": sleep_mean(nights or [])
        if rt.share.get("sleep", True)
        else "not_shared",
        "data_today_pct": pct,
    }


def metric_window(now_ts: int, range_key: str) -> tuple[int, int, int]:
    span, step = RANGES[range_key]
    end = now_ts - now_ts % step
    return end - span + step, end, step


def metric(
    rt: CrewRuntime,
    m: str,
    range_key: str,
    rows: list[tuple[int, Any, Any, Any, int]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    now_ts = rt.now_ts
    start, end, step = metric_window(now_ts, range_key)
    by_ts = {row[0]: row for row in rows}
    field = ROW_FIELD[m]
    lo_key, hi_key = (f"lo_{m}", f"hi_{m}") if m in dict(VITALS) else (None, None)
    for row in rt.recent:
        if start <= row["ts"] <= end + step:
            by_ts[row["ts"]] = (
                row["ts"],
                row.get(field),
                row.get(lo_key) if lo_key else None,
                row.get(hi_key) if hi_key else None,
                row["ctx"],
            )

    points = []
    for ts in range(start, end + 1, step):
        if step == 60:
            row = by_ts.get(ts)
            points.append(
                [ts, r(row[1]), r(row[2]), r(row[3]), row[4]]
                if row
                else [ts, None, None, None, 0]
            )
            continue
        chunk = [by_ts[t] for t in range(ts, ts + step, 60) if t in by_ts]
        points.append(
            [ts, *(_med([c[i] for c in chunk]) for i in (1, 2, 3)), _mode_ctx(chunk)]
        )

    usual, _ = usual_band(rt, m)
    value = current_value(rt, m)
    ctx = current_ctx(rt)
    f = rt.dev.last_frame
    return {
        "m": m,
        "unit": UNITS[m],
        "range": range_key,
        "step_s": step,
        "now_ts": now_ts,
        "now": {
            "value": r(value),
            "usual": usual,
            "diff": _diff(value, usual),
            "ctx": ctx.label if ctx is not None else None,
            "signal": signal(f.sqi) if f else None,
            "state": card_state(rt, m)[0],
        },
        "points": points,
        "limits": METRIC_LIMITS.get(m, []),
        "events": events,
    }


def _med(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return r(median(vals)) if vals else None


def _mode_ctx(chunk: list[tuple]) -> int:
    ctxs = [c[4] for c in chunk if c[1] is not None]
    return Counter(ctxs).most_common(1)[0][0] if ctxs else 0


def _diff(value: float | None, usual: list[float] | None) -> float | None:
    if value is None or usual is None:
        return None
    lo, hi = usual
    if value < lo:
        return r(value - lo)
    if value > hi:
        return r(value - hi)
    return 0.0


def event_json(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": alert["id"],
        "ts_start": alert["ts_start"],
        "ts_end": alert["ts_end"],
        "level": alert["peak_level"],
        "pattern": alert["pattern"],
        "ack": alert["ack_ts"] is not None,
    }
