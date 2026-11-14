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
