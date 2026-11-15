"""Virtual device: one WebSocket to the backend ingest + four HTTP routes that the
backend forwards from /api/v1/sim/* (docs/TASKS.md §2).

    uvicorn vigil.vdev.app:app --host 0.0.0.0 --port 8100

Order on the wire: history (type-2 minute frames, HISTORY flag) and then live
(type-1 second frames), always on the same connection and always in time order.
"""

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from litestar import Litestar, Request, Response, get, post
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from vigil.core.frame import pack
from vigil.vdev.signal import PROFILES, SCENARIOS, Fleet

log = logging.getLogger("vigil.vdev")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

INGEST_URL = os.environ.get("VDEV_INGEST_URL", "ws://localhost:8000/api/v1/ingest")
BACKEND_URL = os.environ.get("VDEV_BACKEND_URL", "http://localhost:8000/api/v1")
SEED = int(os.environ.get("VDEV_SEED", "0"))
SPEEDS = (1, 10, 60)
MAX_BURST_S = 120  # virtual seconds sent in one go before yielding to the event loop


class Runner:
    def __init__(self) -> None:
        self.speed = 1
        self.mode = "starting"
        self.vt: int | None = None
        self.fleet = Fleet(SEED)
        self.task: asyncio.Task | None = None
        self.booting = False
        self._anchor: tuple[float, int] | None = None  # (monotonic, vt)
        self.http = httpx.AsyncClient(base_url=BACKEND_URL, timeout=30.0)

    # ---- life cycle ----

    def start(self) -> None:
        self.task = asyncio.create_task(self._guard(self._boot()))

    async def stop(self) -> None:
        await self._cancel()
        await self.http.aclose()

    async def _cancel(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def _guard(self, coro) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("stream stopped by an error; restarting in 3 s")
            await asyncio.sleep(3)
            self.task = asyncio.create_task(self._guard(self._boot()))

    async def _boot(self) -> None:
        """Start-up: Postgres may hold data from an earlier run with a later clock,
        which would make every new frame stale. So ask the backend to wipe first."""
        self.mode = "starting"
        self.booting = True
        try:
            while True:
                try:
                    resp = await self.http.post("/sim/reset", json={})
                    if resp.status_code < 500:
                        break
                    log.info("backend reset answered %s, retrying", resp.status_code)
                except httpx.HTTPError as exc:
                    log.info("backend not ready (%s), retrying", exc)
                await asyncio.sleep(1)
        finally:
            self.booting = False
        await self._stream()

    async def reset(self) -> None:
        """Called by the backend from inside its own /sim/reset. Stop sending now;
        restart only after the backend has finished wiping its database."""
        if self.booting:
            return  # our own start-up call: _boot continues when it returns
        await self._cancel()
        self.mode = "resetting"
        self.task = asyncio.create_task(self._guard(self._after_reset()))

    async def _after_reset(self) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            try:
                crew = (await self.http.get("/crew")).json()
                if all(c.get("now_ts") is None for c in crew):
                    break
            except httpx.HTTPError, ValueError:
                pass
        await asyncio.sleep(1)  # covers a reset pressed on an already empty database
        await self._stream()

    # ---- streaming ----

    async def _stream(self) -> None:
        self.fleet = Fleet(SEED)
        self.vt = None
        while True:
            try:
                async with connect(INGEST_URL, max_size=None) as ws:
                    if self.vt is None:
                        await self._history(ws)
                    await self._live(ws)
            except (OSError, WebSocketException) as exc:
                log.warning("ingest connection lost: %s", exc)
                await asyncio.sleep(1)
                if self.mode != "live":
                    # History was cut short: the backend holds half of it. Start over.
                    await self._boot()
                    return

    async def _history(self, ws: ClientConnection) -> None:
        self.mode = "backfill"
        vt0 = int(time.time()) // 60 * 60
        end_min = vt0 // 60
        first = {p.crew: end_min - p.history_days * 1440 for p in PROFILES}
        started = time.monotonic()
        sent = 0
        for minute in range(min(first.values()), end_min):
            for frame in self.fleet.history_frames(minute, first):
                await ws.send(pack(frame))
                sent += 1
            self.vt = minute * 60
            if minute % 30 == 0:
                await asyncio.sleep(0)  # let the HTTP routes answer
        self.vt = vt0
        log.info("history sent: %d frames in %.1f s", sent, time.monotonic() - started)

    async def _live(self, ws: ClientConnection) -> None:
        self.mode = "live"
        self._anchor = (time.monotonic(), self.vt)
        while True:
            wall0, vt_anchor = self._anchor
            target = vt_anchor + int((time.monotonic() - wall0) * self.speed)
            if (
                target - self.vt > MAX_BURST_S * 5
            ):  # fell far behind: do not try to catch up
                self._anchor = (time.monotonic(), self.vt)
                target = self.vt + MAX_BURST_S
            burst_end = min(target, self.vt + MAX_BURST_S)
            while self.vt < burst_end:
                for frame in self.fleet.live_frames(self.vt):
                    await ws.send(pack(frame))
                self.vt += 1
                if self.vt % 60 == 0:
                    self.fleet.prune(self.vt)
            await asyncio.sleep(0 if self.vt < target else min(0.05, 0.5 / self.speed))

    # ---- controls ----

    def set_speed(self, speed: int) -> None:
        self.speed = speed
        if self.vt is not None:
            self._anchor = (time.monotonic(), self.vt)

    def state(self) -> dict[str, Any]:
        vt = self.vt
        return {
            "scenarios": list(SCENARIOS),
            "speed": self.speed,
            "mode": self.mode,
            "virtual_ts": vt,
            "active": [
                {
                    "crew": s.crew,
                    "name": s.name,
                    "severity": s.severity,
                    "elapsed_s": vt - s.t0,
                    "duration_s": s.duration_s,
                }
                for s in (self.fleet.active(vt) if vt is not None else [])
            ],
        }


runner = Runner()


def _error(detail: str) -> Response:
    return Response({"detail": detail}, status_code=400)


@get("/state", sync_to_thread=False)
def get_state() -> dict[str, Any]:
    return runner.state()


@post("/scenario", status_code=200)
async def post_scenario(request: Request) -> Response:
    body = await request.json() or {}
    name = body.get("name") or body.get("scenario")
    if runner.mode != "live" or runner.vt is None:
        return _error(f"not streaming live yet (mode: {runner.mode})")
    try:
        scenario = runner.fleet.add_scenario(
            str(name),
            int(body.get("crew", 1)),
            runner.vt,
            int(body["severity"]) if body.get("severity") else None,
            int(body["duration"]) if body.get("duration") else None,
        )
    except (ValueError, TypeError) as exc:
        return _error(str(exc))
    log.info("scenario %s", scenario)
    return Response({"ok": True, **runner.state()}, status_code=200)


@post("/speed", status_code=200)
async def post_speed(request: Request) -> Response:
    body = await request.json() or {}
    try:
        speed = int(body.get("speed"))
    except ValueError, TypeError:
        return _error("speed must be a number")
    if speed not in SPEEDS:
        return _error(f"speed must be one of {SPEEDS}")
    runner.set_speed(speed)
    return Response({"ok": True, **runner.state()}, status_code=200)


@post("/reset", status_code=200)
async def post_reset() -> dict[str, Any]:
    await runner.reset()
    return {"ok": True, "mode": runner.mode}


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncIterator[None]:
    runner.start()
    try:
        yield
    finally:
        await runner.stop()


app = Litestar(
    route_handlers=[get_state, post_scenario, post_speed, post_reset],
    lifespan=[lifespan],
)
