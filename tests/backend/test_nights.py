from vigil.backend.hub import group_nights


def test_nights_are_split_by_long_gaps_and_short_runs_dropped():
    night1 = [1000 * 60 + i * 60 for i in range(400)]
    nap = [night1[-1] + 6 * 3600 + i * 60 for i in range(40)]
    # second night with a 20-minute awakening in the middle
    start2 = night1[-1] + 16 * 3600
    night2 = [start2 + i * 60 for i in range(200)] + [
        start2 + (220 + i) * 60 for i in range(200)
    ]
    nights = group_nights(night1 + nap + night2)
    assert [n["asleep_min"] for n in nights] == [400, 400]
    assert nights[0]["awake_min"] == 0
    assert nights[1]["awake_min"] == 20
    assert nights[1]["wake_ts"] == night2[-1] + 60
