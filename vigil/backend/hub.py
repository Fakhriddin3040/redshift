import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from vigil.backend.db import Database
from vigil.backend.serialize import (
    alert_json,
    alert_tuple,
    minute_row,
    minute_row_tuple,
    r,
    record_to_incident,
    record_to_row,
    row_to_minute,
)
from vigil.backend.writer import Writer
from vigil.core import thresholds as th
from vigil.core.context import Ctx
from vigil.core.frame import MEASURED_FIELDS, Frame, FrameError, FrameType, unpack
from vigil.core.minute import Minute, MinuteAggregator, from_minute_frame, ppco2
from vigil.core.pipeline import CrewState, Incident

log = logging.getLogger("vigil.hub")

RECENT_MINUTES = 60
LIVE_TICK_BACKLOG = 256
ROW_FIELDS = (
    "hr",
    "spo2",
    "rr",
    "skin_t",
    "hrv",
    "co2_ppm",
    "press_hpa",
    "amb_t",
    "act_mg",
)


def day_str(day: int) -> str:
    return datetime.fromtimestamp(day * 86400, UTC).date().isoformat()


@dataclass
class DeviceStats:
    last_ts: int | None = None
    last_seq: int | None = None
    received: int = 0
    lost: int = 0
    last_wall: float | None = None
    last_frame: Frame | None = None
    seen: set[str] = field(default_factory=set)
    null_since: dict[str, int] = field(default_factory=dict)

    def observe(self, f: Frame) -> None:
        if self.last_seq is not None:
            self.lost += (f.seq - self.last_seq - 1) & 0xFF
        self.last_seq = f.seq
        self.last_ts = f.ts
        self.received += 1
        self.last_wall = time.monotonic()
        self.last_frame = f
        for name in MEASURED_FIELDS:
            if getattr(f, name) is None:
                if name in self.seen:
                    self.null_since.setdefault(name, f.ts)
            else:
                self.seen.add(name)
                self.null_since.pop(name, None)


@dataclass
class CrewRuntime:
    id: int
    name: str
    role: str
    dev_id: int
    share: dict[str, bool]
    state: CrewState = field(default_factory=CrewState)
    agg: MinuteAggregator = field(default_factory=MinuteAggregator)
    dev: DeviceStats = field(default_factory=DeviceStats)
    recent: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=RECENT_MINUTES)
    )
    first_day: int | None = None
    data_minutes: dict[int, int] = field(default_factory=dict)
    notices: dict[str, Incident] = field(default_factory=dict)
    notice_keys: set[str] = field(default_factory=set)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    baseline_seen: tuple[str, int] | None = None
    off_since: int | None = None

    def track_off(self, ctx: Ctx, ts: int) -> None:
        if ctx != Ctx.OFF:
            self.off_since = None
        elif self.off_since is None:
            self.off_since = ts

    @property
    def is_off(self) -> bool:
        return self.off_since is not None

    @property
    def now_ts(self) -> int | None:
        if self.dev.last_ts is not None:
            return self.dev.last_ts
        return self.state.last_ts

    @property
    def critical_acked(self) -> bool:
        inc = self.state.incident
        return inc is not None and inc.level == 3 and inc.ack_ts is not None

    @property
    def open_alerts(self) -> list[Incident]:
        inc = self.state.incident
        return ([inc] if inc else []) + sorted(
            self.notices.values(), key=lambda n: n.id or 0
        )

    def latest(self, field_name: str) -> float | None:
        """Most recent received value of a frame field (second or minute frame)."""
        f = self.dev.last_frame
        if f is not None:
            if field_name == "ppco2":
                return ppco2(f.co2_ppm, f.press_hpa)
            return getattr(f, field_name)
        if self.recent:
            return self.recent[-1].get(field_name)
        return None


class Hub:
    def __init__(self, db: Database, writer: Writer) -> None:
        self.db = db
        self.writer = writer
        self.crews: dict[int, CrewRuntime] = {}
        self.by_dev: dict[int, CrewRuntime] = {}
        self.bad_frames = 0
        self.unknown_frames = 0
        self.stale_frames = 0
        self._next_alert_id = 1
        self.paused = False

    async def load(self) -> None:
        subscribers = {cid: rt.subscribers for cid, rt in self.crews.items()}
        self.crews, self.by_dev = {}, {}
        for rec in await self.db.crews():
            rt = CrewRuntime(
                id=rec["id"],
                name=rec["name"],
                role=rec["role"],
                dev_id=rec["dev_id"],
                share=rec["share"],
            )
            rt.subscribers = subscribers.get(rt.id, set())
            self.crews[rt.id] = rt
            self.by_dev[rt.dev_id] = rt

        open_by_crew: dict[int, list[Incident]] = {}
        for rec in await self.db.open_alerts():
            crew_id, inc = record_to_incident(rec)
            open_by_crew.setdefault(crew_id, []).append(inc)
        self._next_alert_id = await self.db.max_alert_id() + 1

        for rt in self.crews.values():
            await self._restore(rt, open_by_crew.get(rt.id, []))

    async def _restore(self, rt: CrewRuntime, open_alerts: list[Incident]) -> None:
        rt.notice_keys = await self.db.alert_keys(rt.id)
        incident = None
        for inc in open_alerts:
            if inc.key == "incident":
                incident = inc
            else:
                rt.notices[inc.key] = inc

        last = await self.db.last_minute_ts(rt.id)
        if last is None:
            rt.state.restore([], incident)
            return
        rows = [
            record_to_row(rec)
            for rec in await self.db.minutes_since(rt.id, last - th.BASELINE_WINDOW_S)
        ]
        rt.state.restore(
            ((row_to_minute(r), Ctx(r["ctx"]), r["learn_mask"]) for r in rows), incident
        )
        rt.first_day = (await self.db.first_minute_ts(rt.id)) // 86400
        rt.dev.last_ts = last + 59
        rt.recent.extend(rows[-RECENT_MINUTES:])
        for row in rows:
            rt.dev.seen.update(f for f in ROW_FIELDS if row[f] is not None)
            rt.track_off(Ctx(row["ctx"]), row["ts"])
            if row["ctx"] != Ctx.OFF:
                day = row["ts"] // 86400
                rt.data_minutes[day] = rt.data_minutes.get(day, 0) + 1
        status = rt.state.baseline_status()
        rt.baseline_seen = (status.state, status.days)
        log.info("crew %s restored: %d minutes, baseline %s", rt.id, len(rows), status)

    async def reset(self) -> None:
        async with self.writer.lock:
            self.writer.clear()
            await self.db.wipe()
            self.bad_frames = self.unknown_frames = self.stale_frames = 0
            await self.load()

    # ---- ingest ----

    def handle_frame(self, data: bytes) -> None:
        if self.paused:
            return
        try:
            f = unpack(data)
        except FrameError:
            self.bad_frames += 1
            return
        rt = self.by_dev.get(f.dev_id)
        if rt is None:
            self.unknown_frames += 1
            return
        if rt.dev.last_ts is not None and f.ts <= rt.dev.last_ts:
            self.stale_frames += 1
            return
        rt.dev.observe(f)

        if f.type == FrameType.SECOND:
            closed = rt.agg.add(f)
            if closed is not None:
                self._on_minute(rt, closed, f.history)
        else:
            closed = rt.agg.close_before(f.ts - f.ts % 60)
            if closed is not None:
                self._on_minute(rt, closed, f.history)
            self._on_minute(rt, from_minute_frame(f), f.history)

        if not f.history:
            self._tick(rt, f)

    def _on_minute(self, rt: CrewRuntime, m: Minute, history: bool) -> None:
        res = rt.state.on_minute(m)
        rt.track_off(res.ctx, m.ts)
        row = minute_row(rt.id, res)
        rt.recent.append(row)
        self.writer.minute(minute_row_tuple(row))
        if rt.first_day is None:
            rt.first_day = m.ts // 86400
        day = m.ts // 86400
        if res.ctx != Ctx.OFF:
            rt.data_minutes[day] = rt.data_minutes.get(day, 0) + 1
            for old in [d for d in rt.data_minutes if d < day - 1]:
                del rt.data_minutes[old]

        if res.incident_event is not None:
            inc = res.incident
            if inc.id is None:
                inc.id = self._alloc_id()
            self.writer.alert(alert_tuple(rt.id, inc))
            if not history and (
                res.incident_event != "updated" or res.level != res.prev_level
            ):
                self._publish(rt, {"t": "alert", "alert": alert_json(rt.id, inc)})
        if not history and (res.level != res.prev_level or res.level_raised):
            self._publish_level(rt)

        if res.became_learned and "baseline_learned" not in rt.notice_keys:
            self._open_notice(rt, "baseline_learned", m.ts, history)

        status = rt.state.baseline_status()
        if (status.state, status.days) != rt.baseline_seen:
            rt.baseline_seen = (status.state, status.days)
            if not history:
                self._publish(
                    rt,
                    {
                        "t": "baseline",
                        "state": status.state,
                        "day": status.days,
                        "of": th.LEARNED_DAYS,
                    },
                )

        if not history:
            self._ensure_checkin_notice(rt, day, m.ts)

    def _ensure_checkin_notice(self, rt: CrewRuntime, day: int, ts: int) -> None:
        key = f"checkin:{day_str(day)}"
        if key in rt.notice_keys:
            return
        for old_key in [k for k in rt.notices if k.startswith("checkin:")]:
            self.close_notice(rt, old_key, ts)
        self._open_notice(rt, key, ts, history=False)

    def _open_notice(self, rt: CrewRuntime, key: str, ts: int, history: bool) -> None:
        notice = Incident(
            id=self._alloc_id(),
            key=key,
            source="system",
            ts_start=ts,
            ts_update=ts,
            level=0,
            peak_level=0,
            ctx=None,
        )
        rt.notices[key] = notice
        rt.notice_keys.add(key)
        self.writer.alert(alert_tuple(rt.id, notice))
        if not history:
            self._publish(rt, {"t": "alert", "alert": alert_json(rt.id, notice)})

    def close_notice(self, rt: CrewRuntime, key: str, ts: int) -> None:
        notice = rt.notices.pop(key, None)
        if notice is None:
            return
        notice.ts_end = notice.ts_update = ts
        self.writer.alert(alert_tuple(rt.id, notice))
        self._publish(rt, {"t": "alert", "alert": alert_json(rt.id, notice)})

    def _alloc_id(self) -> int:
        alert_id = self._next_alert_id
        self._next_alert_id += 1
        return alert_id

    # ---- ack ----

    def find_open(self, alert_id: int) -> tuple[CrewRuntime, Incident] | None:
        for rt in self.crews.values():
            for inc in rt.open_alerts:
                if inc.id == alert_id:
                    return rt, inc
        return None

    async def ack(self, alert_id: int) -> dict[str, Any] | None:
        found = self.find_open(alert_id)
        if found is not None:
            rt, inc = found
            if inc.ack_ts is None:
                inc.ack_ts = rt.now_ts
                if inc.source == "system":
                    self.close_notice(rt, inc.key, inc.ack_ts)
                else:
                    self.writer.alert(alert_tuple(rt.id, inc))
                    self._publish(rt, {"t": "alert", "alert": alert_json(rt.id, inc)})
                    self._publish_level(rt)
            return alert_json(rt.id, inc)

        rec = await self.db.alert(alert_id)
        if rec is None:
            return None
        rt = self.crews[rec["crew_id"]]
        rec = await self.db.ack_alert(
            alert_id, rt.now_ts or int(rec["ts_update"].timestamp())
        )
        crew_id, inc = record_to_incident(rec)
        return alert_json(crew_id, inc)

    # ---- live ----

    def subscribe(self, crew_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.crews[crew_id].subscribers.add(q)
        return q

    def unsubscribe(self, crew_id: int, q: asyncio.Queue) -> None:
        self.crews[crew_id].subscribers.discard(q)

    def _publish(self, rt: CrewRuntime, msg: dict[str, Any]) -> None:
        # A slow client loses ticks, never alert/level/baseline messages.
        for q in rt.subscribers:
            if msg["t"] != "tick" or q.qsize() < LIVE_TICK_BACKLOG:
                q.put_nowait(msg)

    def _publish_level(self, rt: CrewRuntime) -> None:
        self._publish(
            rt,
            {
                "t": "level",
                "level": rt.state.level,
                "critical_acked": rt.critical_acked,
            },
        )

    def _tick(self, rt: CrewRuntime, f: Frame) -> None:
        if not rt.subscribers:
            return
        last = rt.state.last
        off = rt.is_off
        self._publish(
            rt,
            {
                "t": "tick",
                "ts": f.ts,
                "ctx": last.ctx.label if last else None,
                "level": rt.state.level,
                "v": {
                    "hr": None if off else f.hr,
                    "spo2": None if off else f.spo2,
                    "rr": None if off else f.rr,
                    "skin_t": None if off else f.skin_t,
                    "ppco2": r(ppco2(f.co2_ppm, f.press_hpa)),
                    "press": f.press_hpa,
                    "amb_t": f.amb_t,
                },
                "sqi": f.sqi,
                "worn": f.worn,
            },
        )
