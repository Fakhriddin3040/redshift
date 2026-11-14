import struct
from dataclasses import dataclass, fields
from enum import IntEnum, IntFlag

FRAME = struct.Struct("<BBHIHHHhHHHBBBBHhH")
FRAME_SIZE = 32
VERSION = 1

U8_NA = 0xFF
U16_NA = 0xFFFF
I16_NA = 0x7FFF

assert FRAME.size == FRAME_SIZE


class FrameType(IntEnum):
    SECOND = 1
    MINUTE = 2


class Flag(IntFlag):
    WORN = 1 << 0
    CHARGING = 1 << 1
    ECG_CONTACT = 1 << 2
    MOTION_ARTIFACT = 1 << 3
    EXERCISE = 1 << 4
    HISTORY = 1 << 7


class FrameError(ValueError):
    pass


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


@dataclass(frozen=True, slots=True)
class Frame:
    type: int
    dev_id: int
    ts: int
    hr: float | None = None
    spo2: float | None = None
    rr: float | None = None
    skin_t: float | None = None
    co2_ppm: float | None = None
    press_hpa: float | None = None
    act_mg: float | None = None
    sqi: int = 0
    flags: int = 0
    batt: int | None = None
    seq: int = 0
    hrv: float | None = None
    amb_t: float | None = None

    @property
    def worn(self) -> bool:
        return bool(self.flags & Flag.WORN)

    @property
    def exercise(self) -> bool:
        return bool(self.flags & Flag.EXERCISE)

    @property
    def history(self) -> bool:
        return bool(self.flags & Flag.HISTORY)


MEASURED_FIELDS = tuple(
    f.name
    for f in fields(Frame)
    if f.name not in {"type", "dev_id", "ts", "sqi", "flags", "seq"}
)


def _dec(raw: int, na: int, scale: float) -> float | None:
    return None if raw == na else raw / scale


def _enc(value: float | None, na: int, scale: float) -> int:
    return na if value is None else round(value * scale)


def unpack(data: bytes) -> Frame:
    if len(data) != FRAME_SIZE:
        raise FrameError(f"length {len(data)}")
    (
        ver, ftype, dev_id, ts, hr, spo2, rr, skin_t, co2, press, act,
        sqi, flags, batt, seq, hrv, amb_t, crc,
    ) = FRAME.unpack(data)  # fmt: skip
    if ver != VERSION:
        raise FrameError(f"version {ver}")
    if crc16_ccitt_false(data[:30]) != crc:
        raise FrameError("crc")
    if ftype not in (FrameType.SECOND, FrameType.MINUTE):
        raise FrameError(f"type {ftype}")
    return Frame(
        type=ftype,
        dev_id=dev_id,
        ts=ts,
        hr=_dec(hr, U16_NA, 10),
        spo2=_dec(spo2, U16_NA, 10),
        rr=_dec(rr, U16_NA, 10),
        skin_t=_dec(skin_t, I16_NA, 100),
        co2_ppm=_dec(co2, U16_NA, 1),
        press_hpa=_dec(press, U16_NA, 10),
        act_mg=_dec(act, U16_NA, 1),
        sqi=sqi,
        flags=flags,
        batt=None if batt == U8_NA else batt,
        seq=seq,
        hrv=_dec(hrv, U16_NA, 1),
        amb_t=_dec(amb_t, I16_NA, 100),
    )


def pack(f: Frame) -> bytes:
    body = FRAME.pack(
        VERSION,
        f.type,
        f.dev_id,
        f.ts,
        _enc(f.hr, U16_NA, 10),
        _enc(f.spo2, U16_NA, 10),
        _enc(f.rr, U16_NA, 10),
        _enc(f.skin_t, I16_NA, 100),
        _enc(f.co2_ppm, U16_NA, 1),
        _enc(f.press_hpa, U16_NA, 10),
        _enc(f.act_mg, U16_NA, 1),
        f.sqi,
        f.flags,
        U8_NA if f.batt is None else f.batt,
        f.seq & 0xFF,
        _enc(f.hrv, U16_NA, 1),
        _enc(f.amb_t, I16_NA, 100),
        0,
    )
    return body[:30] + struct.pack("<H", crc16_ccitt_false(body[:30]))
