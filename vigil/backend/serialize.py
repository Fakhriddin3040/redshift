"""Conversions between core objects, database rows and API JSON."""

from typing import Any

import asyncpg

from vigil.backend.db import AGG_COLUMNS, to_dt, to_ts
from vigil.core.context import Ctx
from vigil.core.minute import Minute
from vigil.core.pipeline import Incident, IncidentMetric, MinuteResult

LEVEL_NAMES = ("usual", "watch", "alert", "critical")
Z_METRICS = ("hr", "spo2", "rr", "skin_t")


def r(x: float | None, n: int = 2) -> float | None:
    return None if x is None else round(x, n)


def minute_row(crew_id: int, res: MinuteResult) -> dict[str, Any]:
    m = res.minute
    row: dict[str, Any] = {
        "crew_id": crew_id,
        "ts": m.ts,
        "hr": m.hr,
        "spo2": m.spo2,
        "rr": m.rr,
        "skin_t": m.skin_t,
        "hrv": m.hrv,
        "co2_ppm": m.co2_ppm,
        "press_hpa": m.press_hpa,
        "amb_t": m.amb_t,
        "ppco2": m.ppco2,
        "act_mg": m.act_mg,
        "sqi": m.sqi,
        "worn_frac": m.worn_frac,
        "valid_s": m.valid_s,
        "ctx": int(res.ctx),
        "level": res.level,
        "learn_mask": res.learn_mask,
    }
    for metric in Z_METRICS:
        ev = res.evals[metric]
        usual = ev.usual
        row[f"z_{metric}"] = ev.z
        row[f"lo_{metric}"] = usual[0] if usual else None
        row[f"hi_{metric}"] = usual[1] if usual else None
    return row


def minute_row_tuple(row: dict[str, Any]) -> tuple:
    return tuple(to_dt(row[c]) if c == "ts" else row[c] for c in AGG_COLUMNS)


def record_to_row(rec: asyncpg.Record) -> dict[str, Any]:
    row = dict(rec)
    row["ts"] = to_ts(rec["ts"])
    return row


def row_to_minute(row: dict[str, Any]) -> Minute:
    return Minute(
        ts=row["ts"],
        hr=row["hr"],
        spo2=row["spo2"],
        rr=row["rr"],
        skin_t=row["skin_t"],
        hrv=row["hrv"],
        co2_ppm=row["co2_ppm"],
        press_hpa=row["press_hpa"],
        amb_t=row["amb_t"],
        act_mg=row["act_mg"],
        sqi=row["sqi"],
        worn_frac=row["worn_frac"] or 0.0,
        valid_s=row["valid_s"],
        summary=row["valid_s"] is None,
    )


def metric_json(im: IncidentMetric) -> dict[str, Any]:
    return {
        "m": im.m,
        "value": r(im.value),
        "usual": [r(im.usual[0]), r(im.usual[1])] if im.usual else None,
        "z": r(im.z),
        "slope_per_min": r(im.slope_per_min, 3),
        "since_min": im.since_min,
        "trend": im.trend,
    }


def alert_tuple(crew_id: int, inc: Incident) -> tuple:
    return (
        inc.id,
        crew_id,
        inc.key,
        inc.source,
        to_dt(inc.ts_start),
        to_dt(inc.ts_update),
        to_dt(inc.ts_end),
        inc.level,
        inc.peak_level,
        inc.pattern,
        inc.p,
        None if inc.ctx is None else int(inc.ctx),
        [metric_json(im) for im in inc.metrics.values()],
        inc.text,
        inc.text_src,
        to_dt(inc.ack_ts),
    )


def record_to_incident(rec: asyncpg.Record) -> tuple[int, Incident]:
    ts_update = to_ts(rec["ts_update"])
    inc = Incident(
        id=rec["id"],
        key=rec["key"],
        source=rec["source"],
        ts_start=to_ts(rec["ts_start"]),
        ts_update=ts_update,
        ts_end=to_ts(rec["ts_end"]),
        level=rec["level"],
        peak_level=rec["peak_level"],
        pattern=rec["pattern"],
        p=rec["p"],
        ctx=None if rec["ctx"] is None else Ctx(rec["ctx"]),
        text=rec["text"],
        text_src=rec["text_src"],
        ack_ts=to_ts(rec["ack_ts"]),
    )
    for m in rec["metrics"] or []:
        inc.metrics[m["m"]] = IncidentMetric(
            m=m["m"],
            first_ts=ts_update - m["since_min"] * 60,
            value=m["value"],
            usual=tuple(m["usual"]) if m["usual"] else None,
            z=m["z"],
            slope_per_min=m.get("slope_per_min"),
            since_min=m["since_min"],
            trend=m["trend"],
        )
    return rec["crew_id"], inc


def alert_json(crew_id: int, inc: Incident) -> dict[str, Any]:
    end = inc.ts_end if inc.ts_end is not None else inc.ts_update
    return {
        "id": inc.id,
        "crew": crew_id,
        "key": inc.key,
        "source": inc.source,
        "level": inc.level,
        "peak_level": inc.peak_level,
        "ts_start": inc.ts_start,
        "ts_end": inc.ts_end,
        "since_min": (end - inc.ts_start) // 60,
        "pattern": inc.pattern,
        "p": r(inc.p),
        "ctx": None if inc.ctx is None else inc.ctx.label,
        "primary": inc.primary,
        "metrics": [
            {k: v for k, v in metric_json(im).items() if k != "slope_per_min"}
            for im in inc.metrics.values()
        ],
        "text": inc.text,
        "text_src": inc.text_src,
        "ack_ts": inc.ack_ts,
    }
