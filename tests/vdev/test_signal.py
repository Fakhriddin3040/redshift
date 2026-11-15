import random

import pytest

from vigil.core.frame import Flag, FrameType, pack, unpack
from vigil.vdev.signal import (
    PROFILES,
    SCENARIOS,
    SLEEP_HR_DELAY_MIN,
    CrewSim,
    Fleet,
    make_scenario,
)

DAY0 = 1_794_700_800 // 60  # a UTC midnight, in minutes


def test_normal_day_never_reaches_a_hard_limit():
    for p in PROFILES:
        sim = CrewSim(p, seed=3)
        for minute in range(DAY0, DAY0 + 2 * 1440):
            s = sim.minute_sample(minute)
            assert s.flags & Flag.WORN
            if not s.flags & Flag.EXERCISE:
                assert (
                    43 <= s.hr <= 109
                )  # clamp [44, 108] plus minute noise; hard limits are 40 and 111
                assert 9.5 <= s.rr <= 20.4
            assert p.spo2 - 1.8 <= s.spo2 <= 100
            assert s.sqi >= 85


def test_sleep_heart_rate_steps_with_the_context_rule():
    p = PROFILES[0]
    sim = CrewSim(p, seed=1)
    quiet = [m for m in range(DAY0, DAY0 + 1440) if sim._sleep_minute(m) is not None]
    start = next(m for m in quiet if sim._sleep_minute(m) == 0)
    held = sim.minute_sample(start + SLEEP_HR_DELAY_MIN - 1)
    asleep = sim.minute_sample(start + SLEEP_HR_DELAY_MIN)
    assert held.act_mg <= 5 and asleep.act_mg <= 5
    assert held.hr > p.rest_hr - 4  # still the resting value for 14 quiet minutes
    assert asleep.hr < p.sleep_hr + 4  # sleep value from the 15th
    end = next(m for m in range(start, start + 1440) if sim._sleep_minute(m) is None)
    awake = sim.minute_sample(end)
    assert awake.act_mg >= 15 and awake.hr > p.rest_hr - 4


def test_hypoxia_is_staged_relative_to_the_person():
    p = PROFILES[2]  # SpO2 mean 98.0
    sim = CrewSim(p, seed=1)
    t0 = (DAY0 + 12 * 60) * 60
    scn = [make_scenario("hypoxia", p.crew, t0, random.Random(0))]
    stage = lambda minute: sim.minute_sample(t0 // 60 + minute, scn).spo2  # noqa: E731
    assert stage(2) == pytest.approx(p.spo2 - 2.5)
    assert stage(8) == pytest.approx(93.0)
    assert stage(13) == pytest.approx(88.0)
    assert stage(30) > p.spo2 - 1.9  # over


def test_sensor_off_sends_no_vitals_and_exercise_sets_the_flag():
    p = PROFILES[0]
    sim = CrewSim(p, seed=1)
    t0 = (DAY0 + 12 * 60) * 60
    off = sim.second_sample(
        t0 + 5, [make_scenario("sensor_off", 1, t0, random.Random(0))]
    )
    assert off.hr is None and off.spo2 is None and off.sqi == 0
    assert not off.flags & Flag.WORN
    ex = [make_scenario("exercise", 1, t0, random.Random(0))]
    peak = sim.second_sample(t0 + 240, ex)
    assert peak.flags & Flag.EXERCISE and peak.hr > 115 and peak.act_mg >= 100
    # The flag stays while heart rate is still coming down, and is gone later.
    assert sim.second_sample(t0 + 330, ex).flags & Flag.EXERCISE
    assert not sim.second_sample(t0 + 1500, ex).flags & Flag.EXERCISE


def test_unknown_scenario_and_crew_are_rejected():
    fleet = Fleet(seed=0)
    with pytest.raises(ValueError):
        fleet.add_scenario("nope", 1, 0)
    with pytest.raises(ValueError):
        fleet.add_scenario("hypoxia", 99, 0)
    assert set(SCENARIOS) >= {"hypoxia", "exercise", "sensor_off", "tachycardia_rest"}


def test_frames_survive_the_wire_and_cabin_is_shared():
    fleet = Fleet(seed=0)
    first = {p.crew: DAY0 for p in PROFILES}
    history = fleet.history_frames(DAY0, first)
    live = fleet.live_frames((DAY0 + 1) * 60)
    assert len(history) == len(live) == 7
    for f in history:
        g = unpack(pack(f))
        assert g.type == FrameType.MINUTE and g.history and g.worn
    for f in live:
        g = unpack(pack(f))
        assert g.type == FrameType.SECOND and not g.history and g.ts == (DAY0 + 1) * 60
    assert len({f.co2_ppm for f in live}) == 1  # one cabin for everyone
    assert 2000 < live[0].co2_ppm < 4000  # the RR-12 profile


def test_cabin_scenario_applies_to_everyone():
    fleet = Fleet(seed=0)
    vt = (DAY0 + 600) * 60
    fleet.add_scenario("hypercapnia", 3, vt)
    assert all(f.co2_ppm > 7000 for f in fleet.live_frames(vt + 5))
    assert fleet.active(vt + 5)[0].crew is None
