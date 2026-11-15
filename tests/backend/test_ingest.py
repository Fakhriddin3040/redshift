from vigil.backend import views
from vigil.backend.hub import CrewRuntime, Hub
from vigil.core.frame import Flag, Frame, pack


class FakeWriter:
    def __init__(self):
        self.minutes, self.alerts = [], []

    def minute(self, row):
        self.minutes.append(row)

    def alert(self, row):
        self.alerts.append(row)


def make_hub() -> tuple[Hub, FakeWriter]:
    writer = FakeWriter()
    hub = Hub(db=None, writer=writer)
    rt = CrewRuntime(id=1, name="A", role="FE", dev_id=11, share={})
    hub.crews, hub.by_dev = {1: rt}, {11: rt}
    return hub, writer


def frame(ts, seq=0, ftype=1, flags=Flag.WORN, **kw):
    v = dict(hr=60.0, spo2=97.0, rr=14.0, skin_t=33.5, act_mg=20, sqi=90)
    v.update(kw)
    return pack(Frame(type=ftype, dev_id=11, ts=ts, seq=seq, flags=flags, **v))


def test_rejections_are_counted():
    hub, _ = make_hub()
    hub.handle_frame(b"short")
    bad_crc = bytearray(frame(100))
    bad_crc[10] ^= 0xFF
    hub.handle_frame(bytes(bad_crc))
    hub.handle_frame(pack(Frame(type=1, dev_id=99, ts=100)))
    hub.handle_frame(frame(100))
    hub.handle_frame(frame(100, seq=1))
    assert (hub.bad_frames, hub.unknown_frames, hub.stale_frames) == (2, 1, 1)


def test_seq_gap_counts_losses_across_wrap():
    hub, _ = make_hub()
    hub.handle_frame(frame(100, seq=254))
    hub.handle_frame(frame(101, seq=1))
    assert hub.crews[1].dev.lost == 2


def test_second_frames_close_minutes():
    hub, writer = make_hub()
    for s in range(120):
        hub.handle_frame(frame(600 + s, seq=s))
    assert len(writer.minutes) == 1
    hub.handle_frame(frame(720, seq=120))
    assert len(writer.minutes) == 2


def test_minute_frame_flushes_open_seconds_first():
    hub, writer = make_hub()
    for s in range(30):
        hub.handle_frame(frame(600 + s, seq=s))
    hub.handle_frame(frame(720, seq=30, ftype=2, flags=Flag.WORN | Flag.HISTORY))
    assert len(writer.minutes) == 2
    assert hub.crews[1].recent[-1]["ts"] == 720


def test_history_frames_do_not_reach_live():
    hub, _ = make_hub()
    q = hub.subscribe(1)
    hub.handle_frame(frame(600, ftype=2, flags=Flag.WORN | Flag.HISTORY))
    assert q.empty()
    hub.handle_frame(frame(660, seq=1, ftype=2))
    msgs = [q.get_nowait() for _ in range(q.qsize())]
    assert [m["t"] for m in msgs] == ["alert", "tick"]
    assert msgs[0]["alert"]["key"] == "checkin:1970-01-01"


async def test_ack_closes_system_notice():
    hub, writer = make_hub()
    hub.handle_frame(frame(600, ftype=2))
    rt = hub.crews[1]
    notice = rt.notices["checkin:1970-01-01"]
    out = await hub.ack(notice.id)
    assert out["ack_ts"] == 600 and out["ts_end"] == 600
    assert "checkin:1970-01-01" not in rt.notices
    hub.handle_frame(frame(660, seq=1, ftype=2))
    assert not rt.notices


def ticks_of(q) -> list[dict]:
    return [m for m in (q.get_nowait() for _ in range(q.qsize())) if m["t"] == "tick"]


def test_live_values_follow_each_frame_not_the_last_minute():
    hub, _ = make_hub()
    rt, q = hub.crews[1], hub.subscribe(1)

    def send(ts: int, **kw) -> dict:
        hub.handle_frame(frame(ts, seq=ts & 0xFF, **kw))
        return ticks_of(q)[-1]

    # One whole minute with the wristband off closes as `off`.
    for s in range(61):
        tick = send(600 + s, flags=0, sqi=0, hr=None, spo2=None, rr=None, skin_t=None)
    assert rt.is_off and tick["v"]["hr"] is None and tick["worn"] is False

    # Put on: the next second is shown, though the minute state is still `off`.
    tick = send(661)
    assert rt.is_off and not rt.live_off
    assert tick["v"]["hr"] == 60.0 and tick["v"]["skin_t"] == 33.5 and tick["worn"]
    card = views.card(rt, "hr")
    assert card["value"] == 60.0
    assert card["state"] == "learning"  # shown, but no minute has judged it yet

    # Worn flag on but no usable signal: hidden again, at once.
    tick = send(662, sqi=10, amb_t=22.0)
    assert tick["v"]["hr"] is None and tick["v"]["skin_t"] is None
    assert tick["v"]["amb_t"] == 22.0  # cabin readings do not depend on the wrist
    card = views.card(rt, "hr")
    assert card["state"] == "no_data" and card["since_ts"] == 600


def test_taking_the_wristband_off_hides_vitals_before_the_minute_closes():
    hub, _ = make_hub()
    rt, q = hub.crews[1], hub.subscribe(1)
    for s in range(70):  # a full good minute and ten seconds of the next
        hub.handle_frame(frame(600 + s, seq=s))
    assert not rt.is_off and ticks_of(q)[-1]["v"]["hr"] == 60.0

    hub.handle_frame(frame(670, seq=70, flags=0))  # values still sent, flag off
    assert not rt.is_off and rt.live_off
    assert ticks_of(q)[-1]["v"]["hr"] is None
    card = views.card(rt, "hr")
    assert card["value"] is None and card["state"] == "no_data"
    assert card["since_ts"] == 670

    hub.handle_frame(frame(671, seq=71))
    assert ticks_of(q)[-1]["v"]["hr"] == 60.0
    assert views.card(rt, "hr")["state"] != "no_data"


def test_after_a_restart_the_last_stored_minute_decides():
    hub, _ = make_hub()
    rt = hub.crews[1]
    rt.off_since = 600  # restored from the database, no frame yet
    assert rt.dev.last_frame is None and rt.live_off
    rt.off_since = None
    assert not rt.live_off
