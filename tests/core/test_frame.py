import pytest

from vigil.core.frame import (
    Flag,
    Frame,
    FrameError,
    FrameType,
    crc16_ccitt_false,
    pack,
    unpack,
)


def test_crc_check_value():
    assert crc16_ccitt_false(b"123456789") == 0x29B1


@pytest.mark.parametrize("ftype", [FrameType.SECOND, FrameType.MINUTE])
def test_round_trip(ftype):
    f = Frame(
        type=ftype,
        dev_id=3,
        ts=1794650645,
        hr=62.5,
        spo2=97.1,
        rr=14.2,
        skin_t=33.57,
        co2_ppm=812,
        press_hpa=1013.2,
        act_mg=15,
        sqi=92,
        flags=Flag.WORN | Flag.EXERCISE,
        batt=86,
        seq=255,
        hrv=41,
        amb_t=-1.25,
    )
    data = pack(f)
    assert len(data) == 32
    assert unpack(data) == f


def test_missing_values_become_none():
    f = Frame(type=FrameType.SECOND, dev_id=1, ts=100)
    back = unpack(pack(f))
    for name in (
        "hr",
        "spo2",
        "rr",
        "skin_t",
        "co2_ppm",
        "press_hpa",
        "act_mg",
        "batt",
        "hrv",
        "amb_t",
    ):
        assert getattr(back, name) is None


def test_bad_crc_rejected():
    data = bytearray(pack(Frame(type=1, dev_id=1, ts=100, hr=60)))
    data[8] ^= 0x01
    with pytest.raises(FrameError):
        unpack(bytes(data))


def test_bad_length_and_version_rejected():
    data = pack(Frame(type=1, dev_id=1, ts=100))
    with pytest.raises(FrameError):
        unpack(data[:31])
    with pytest.raises(FrameError):
        unpack(b"\x02" + data[1:])
