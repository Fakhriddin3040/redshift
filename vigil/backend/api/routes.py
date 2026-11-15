import asyncio
import contextlib
from typing import Any

import httpx
from litestar import Request, Response, get, post, websocket
from litestar.connection import WebSocket
from litestar.exceptions import (
    NotFoundException,
    ValidationException,
    WebSocketDisconnect,
)
from litestar.params import Parameter

from vigil.backend import views
from vigil.backend.db import METRIC_COLUMNS
from vigil.backend.hub import CrewRuntime, Hub
from vigil.backend.serialize import alert_json, record_to_incident


def crew_or_404(hub: Hub, crew_id: int) -> CrewRuntime:
    rt = hub.crews.get(crew_id)
    if rt is None:
        raise NotFoundException(f"crew {crew_id} not found")
    return rt


@get("/health")
async def health(hub: Hub) -> dict[str, Any]:
    return {
        "ok": True,
        "bad_frames": hub.bad_frames,
        "unknown_frames": hub.unknown_frames,
        "stale_frames": hub.stale_frames,
        "write_queue": hub.writer.pending,
    }


@websocket("/ingest")
async def ingest(socket: WebSocket, hub: Hub) -> None:
    await socket.accept()
    async for data in socket.iter_data(mode="binary"):
        hub.handle_frame(data)


@websocket("/live")
async def live(socket: WebSocket, hub: Hub, crew: int = 1) -> None:
    if crew not in hub.crews:
        await socket.close(code=4404, reason="unknown crew")
        return
    await socket.accept()
    queue = hub.subscribe(crew)

    async def drain_client() -> None:
        async for _ in socket.iter_data():
            pass

    reader = asyncio.create_task(drain_client())
    try:
        while not reader.done():
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {getter, reader}, return_when=asyncio.FIRST_COMPLETED
            )
            if getter not in done:
                getter.cancel()
                break
            await socket.send_json(getter.result())
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(crew, queue)
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader


@get("/crew")
async def crew_list(hub: Hub) -> list[dict[str, Any]]:
    return [views.crew_item(rt, await hub.nights(rt.id)) for rt in hub.crews.values()]


@get("/crew/{crew_id:int}/today")
async def crew_today(hub: Hub, crew_id: int) -> dict[str, Any]:
    rt = crew_or_404(hub, crew_id)
    return views.today(rt, await hub.nights(rt.id), hub.radiation)


@get("/crew/{crew_id:int}/sleep")
async def crew_sleep(hub: Hub, crew_id: int) -> dict[str, Any]:
    rt = crew_or_404(hub, crew_id)
    return views.sleep(rt, await hub.nights(rt.id))


@post("/crew/{crew_id:int}/checkin", status_code=200)
async def crew_checkin(hub: Hub, crew_id: int, data: dict[str, Any]) -> dict[str, Any]:
    rt = crew_or_404(hub, crew_id)
    if rt.now_ts is None:
        raise ValidationException("no data for this crew member yet")
    try:
        body = {
            "sleep": _scale(data, "sleep"),
            "mood": _scale(data, "mood"),
            "energy": _scale(data, "energy"),
            "symptoms": [str(s)[:40] for s in data.get("symptoms") or []][:12],
            "note": str(data.get("note") or "")[:2000],
        }
    except (TypeError, ValueError) as exc:
        raise ValidationException(str(exc)) from exc
    return await hub.file_checkin(rt, body)


def _scale(data: dict[str, Any], key: str) -> int:
    value = int(data[key]) if data.get(key) is not None else None
    if value is None or not 1 <= value <= 5:
        raise ValueError(f"{key} must be a number from 1 to 5")
    return value


@get("/radiation")
async def radiation(hub: Hub) -> dict[str, Any]:
    return views.radiation(hub.radiation)


@get("/crew/{crew_id:int}/metric/{m:str}")
async def crew_metric(
    hub: Hub,
    crew_id: int,
    m: str,
    range_key: str = Parameter(query="range", default="1h"),
) -> dict[str, Any]:
    rt = crew_or_404(hub, crew_id)
    if m not in METRIC_COLUMNS:
        raise NotFoundException(f"unknown metric {m}")
    if range_key not in views.RANGES:
        raise ValidationException(f"range must be one of {', '.join(views.RANGES)}")
    if rt.now_ts is None:
        raise NotFoundException("no data for this crew member yet")

    start, end, step = views.metric_window(rt.now_ts, range_key)
    rows = await hub.db.metric_points(crew_id, m, start, end + step - 1)
    events = {}
    for rec in await hub.db.incidents_between(crew_id, start, end + step - 1):
        events[rec["id"]] = alert_json(*record_to_incident(rec))
    inc = rt.state.incident
    if inc is not None and inc.id is not None:
        events[inc.id] = alert_json(rt.id, inc)
    event_list = [
        views.event_json(a)
        for a in sorted(events.values(), key=lambda a: a["ts_start"])
    ]
    return views.metric(rt, m, range_key, rows, event_list)


@get("/crew/{crew_id:int}/alerts")
async def crew_alerts(
    hub: Hub, crew_id: int, open_only: int = Parameter(query="open", default=0)
) -> list[dict[str, Any]]:
    rt = crew_or_404(hub, crew_id)
    live_alerts = {a.id: alert_json(rt.id, a) for a in rt.open_alerts}
    if open_only:
        return list(live_alerts.values())
    out = []
    for rec in await hub.db.alerts(crew_id):
        out.append(
            live_alerts.pop(rec["id"], None) or alert_json(*record_to_incident(rec))
        )
    return list(live_alerts.values()) + out


@post("/alerts/{alert_id:int}/ack", status_code=200)
async def ack_alert(hub: Hub, alert_id: int) -> dict[str, Any]:
    alert = await hub.ack(alert_id)
    if alert is None:
        raise NotFoundException(f"alert {alert_id} not found")
    return alert


async def _forward(request: Request, method: str, path: str) -> Response:
    client: httpx.AsyncClient = request.app.state.vdev
    try:
        resp = await client.request(
            method,
            path,
            content=await request.body() if method == "POST" else None,
            headers={
                "content-type": request.headers.get("content-type", "application/json")
            },
        )
    except httpx.HTTPError as exc:
        return Response({"detail": f"vdev unavailable: {exc}"}, status_code=503)
    return Response(
        resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


@get("/sim/state")
async def sim_state(request: Request) -> Response:
    return await _forward(request, "GET", "/state")


@post("/sim/scenario")
async def sim_scenario(request: Request) -> Response:
    return await _forward(request, "POST", "/scenario")


@post("/sim/speed")
async def sim_speed(request: Request) -> Response:
    return await _forward(request, "POST", "/speed")


@post("/sim/reset")
async def sim_reset(request: Request, hub: Hub) -> Response:
    # Frames are dropped until the wipe is done: otherwise the old stream would set
    # last_ts and the replayed history from vdev would all be rejected as stale.
    hub.paused = True
    try:
        response = await _forward(request, "POST", "/reset")
        await hub.reset()
    finally:
        hub.paused = False
    return response


ROUTES = [
    health,
    ingest,
    live,
    crew_list,
    crew_today,
    crew_sleep,
    crew_checkin,
    radiation,
    crew_metric,
    crew_alerts,
    ack_alert,
    sim_state,
    sim_scenario,
    sim_speed,
    sim_reset,
]
