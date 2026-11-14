from vigil.core.context import ContextTracker, Ctx
from vigil.core.frame import Flag, Frame
from vigil.core.minute import Minute, MinuteAggregator, aggregate, ppco2


def second(ts, hr=60.0, sqi=90, worn=True, **kw):
    return Frame(
        type=1, dev_id=1, ts=ts, hr=hr, sqi=sqi, flags=Flag.WORN if worn else 0, **kw
    )


def test_minute_median():
    frames = [second(60 + i, hr=60 + i % 3) for i in range(60)]
    m = aggregate(60, frames)
    assert m.hr == 61
    assert m.valid_s == 60
    assert m.worn_frac == 1.0


def test_minute_too_few_valid_seconds_is_none():
    frames = [second(i, hr=70) for i in range(19)] + [
        second(19 + i, sqi=30) for i in range(41)
    ]
    m = aggregate(0, frames)
    assert m.hr is None
    assert m.valid_s == 19


def test_cabin_ignores_sqi():
    frames = [second(i, sqi=0, co2_ppm=800) for i in range(60)]
    m = aggregate(0, frames)
    assert m.hr is None
    assert m.co2_ppm == 800


def test_aggregator_closes_on_next_minute():
    agg = MinuteAggregator()
    assert all(agg.add(second(i)) is None for i in range(60))
    closed = agg.add(second(60))
    assert closed is not None and closed.ts == 0


def test_ppco2():
    assert round(ppco2(5000, 1013.25), 2) == 3.80
    assert round(ppco2(5000, None), 2) == 3.80


def minute(ts, act=20.0, hr=60.0, worn=1.0, sqi=90.0, exercise=False):
    return Minute(ts=ts, hr=hr, act_mg=act, worn_frac=worn, sqi=sqi, exercise=exercise)


def test_context_off():
    assert ContextTracker().classify(minute(0, worn=0.0)) == Ctx.OFF
    assert ContextTracker().classify(minute(0, sqi=10)) == Ctx.OFF


def test_context_active_with_cooldown():
    tr = ContextTracker()
    assert tr.classify(minute(0, act=80)) == Ctx.ACTIVE
    for i in range(1, 6):
        assert tr.classify(minute(i * 60)) == Ctx.ACTIVE
    assert tr.classify(minute(6 * 60)) == Ctx.REST


def test_context_exercise_flag():
    assert ContextTracker().classify(minute(0, act=5, exercise=True)) == Ctx.ACTIVE


def test_context_sleep_after_15_low_minutes():
    tr = ContextTracker()
    ctxs = [tr.classify(minute(i * 60, act=3, hr=55)) for i in range(16)]
    assert ctxs[13] == Ctx.REST
    assert ctxs[14] == Ctx.SLEEP


def test_context_sleep_needs_low_hr():
    tr = ContextTracker()
    ctxs = [
        tr.classify(minute(i * 60, act=3, hr=75), rest_hr_median=60) for i in range(16)
    ]
    assert ctxs[-1] == Ctx.REST


def test_context_sleep_null_hr_passes():
    tr = ContextTracker()
    ctxs = [tr.classify(minute(i * 60, act=3, hr=None)) for i in range(15)]
    assert ctxs[-1] == Ctx.SLEEP


def test_context_rest():
    assert ContextTracker().classify(minute(0, act=20)) == Ctx.REST
