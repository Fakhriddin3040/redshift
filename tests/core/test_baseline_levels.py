import numpy as np

from vigil.core.baseline import LEARN_BIT, Baseline, Cell, robust_norm
from vigil.core.context import Ctx
from vigil.core.levels import Hysteresis, ZRun, hard_level
from vigil.core.minute import Minute
from vigil.core.pipeline import CrewState

DAY = 86400


def test_norm_example():
    norm = robust_norm("hr", np.array([56, 58, 57, 60, 55, 57, 59], dtype=float))
    assert norm.med == 57
    assert norm.sig == 3.0
    assert norm.z(66) == 3.0


def fill(cell: Cell, n: int, days: int) -> None:
    for i in range(n):
        cell.add((i % days) * DAY + i, 60.0)


def test_cell_not_ready_with_119_values():
    cell = Cell()
    fill(cell, 119, 3)
    cell.recompute("hr", 10 * DAY)
    assert not cell.ready


def test_cell_not_ready_with_two_days():
    cell = Cell()
    fill(cell, 500, 2)
    cell.recompute("hr", 10 * DAY)
    assert not cell.ready


def test_cell_ready():
    cell = Cell()
    fill(cell, 120, 3)
    cell.recompute("hr", 10 * DAY)
    assert cell.ready


def test_lookup_falls_back_to_typical_doubled():
    lk = Baseline().lookup("hr", Ctx.REST, 0)
    assert lk.learning
    assert (lk.norm.med, lk.norm.sig) == (60.0, 20.0)


def normal_minute(ts, **kw):
    base = dict(
        hr=60.0,
        spo2=97.0,
        rr=14.0,
        skin_t=33.5,
        co2_ppm=800.0,
        press_hpa=1013.0,
        act_mg=20.0,
        sqi=90.0,
        worn_frac=1.0,
        valid_s=60,
    )
    base.update(kw)
    return Minute(ts=ts, **base)


def learned_state(start: int = 10 * DAY) -> CrewState:
    """A crew member whose rest norm for every vital is learned around the normal values."""
    st = CrewState()
    rng = np.random.default_rng(1)
    for d in range(4):
        for h in range(24):
            for k in range(0, 60, 5):
                ts = start - (d + 1) * DAY + h * 3600 + k * 60
                for metric, mu in (
                    ("hr", 60),
                    ("spo2", 97),
                    ("rr", 14),
                    ("skin_t", 33.5),
                ):
                    st.baseline.add(metric, Ctx.REST, ts, mu + rng.normal(0, 0.5))
    st.baseline.recompute(start - 60)
    return st


def test_after_warmup_outlier_not_learned():
    st = learned_state()
    hr_norm = st.baseline.lookup("hr", Ctx.REST, 10 * DAY).norm
    assert not st.baseline.lookup("hr", Ctx.REST, 10 * DAY).learning
    res = st.on_minute(normal_minute(10 * DAY, hr=hr_norm.med + 3 * hr_norm.sig))
    assert res.ctx == Ctx.REST
    assert not res.learn_mask & LEARN_BIT["hr"]
    assert res.learn_mask & LEARN_BIT["spo2"]


def test_while_learning_everything_learned():
    res = CrewState().on_minute(normal_minute(0, hr=95.0))
    assert res.learn_mask & LEARN_BIT["hr"]


def test_watch_after_five_minutes_and_gap_resets():
    run = ZRun()
    assert [run.update(i * 60, 2.1) for i in range(4)] == [0, 0, 0, 0]
    assert run.update(4 * 60, 2.1) == 1
    run = ZRun()
    for i in range(4):
        run.update(i * 60, 2.1)
    assert run.update(6 * 60, 2.1) == 0


def test_alert_after_three_minutes():
    run = ZRun()
    assert [run.update(i * 60, 3.2) for i in range(3)] == [0, 0, 2]


def test_hysteresis():
    h = Hysteresis()
    assert h.update(3) == 3
    for _ in range(9):
        assert h.update(0) == 3
    assert h.update(0) == 2
    assert h.update(1) == 2
    assert h.update(3) == 3


def test_hard_thresholds():
    assert hard_level("spo2", 88, Ctx.REST) == 3
    assert hard_level("spo2", 93.0, Ctx.REST) == 2
    assert hard_level("spo2", 94, Ctx.REST) == 0
    assert hard_level("hr", 40, Ctx.REST) == 3
    assert hard_level("hr", 40, Ctx.SLEEP) == 2
    assert hard_level("hr", 140, Ctx.ACTIVE) == 0
    assert hard_level("rr", 26, Ctx.SLEEP) == 3


def test_spo2_88_one_minute_is_critical():
    st = learned_state()
    res = st.on_minute(normal_minute(10 * DAY, spo2=88.0))
    assert res.level == 3
    assert res.incident_event == "created"
    assert res.incident.primary == "spo2"
    assert res.incident.pattern == "hypoxia"


def test_sensor_off_does_not_alarm():
    st = learned_state()
    for i in range(30):
        res = st.on_minute(
            normal_minute(
                10 * DAY + i * 60, hr=None, spo2=None, worn_frac=0.0, sqi=0.0, valid_s=0
            )
        )
        assert res.ctx == Ctx.OFF
        assert res.level == 0
        assert st.incident is None


def test_exercise_hr_140_no_alarm():
    st = learned_state()
    for i in range(20):
        res = st.on_minute(
            normal_minute(10 * DAY + i * 60, hr=140.0, rr=24.0, act_mg=120.0)
        )
        assert res.ctx == Ctx.ACTIVE
        assert res.level == 0


def test_incident_closes_after_recovery_and_ack_cleared_on_escalation():
    st = learned_state()
    t = 10 * DAY
    st.on_minute(normal_minute(t, spo2=93.0))
    st.incident.ack_ts = t
    res = st.on_minute(normal_minute(t + 60, spo2=88.0))
    assert res.level == 3 and res.level_raised
    assert res.incident.ack_ts is None
    for i in range(2, 40):
        res = st.on_minute(normal_minute(t + i * 60))
        if res.incident_event == "closed":
            break
    assert res.incident_event == "closed"
    assert res.incident.ts_end is not None
    assert st.incident is None


def test_restore_rebuilds_norm():
    st = CrewState()
    minutes = []
    for d in range(8):
        for i in range(0, 1440, 2):
            ts = d * DAY + i * 60
            minutes.append(
                (normal_minute(ts), Ctx.REST, LEARN_BIT["hr"] | LEARN_BIT["spo2"])
            )
    st.restore(minutes)
    assert not st.baseline.lookup("hr", Ctx.REST, 7 * DAY).learning
    assert st.learned
    assert st.baseline_status().ready_pct == 100
