"""GT7 telemetry source tests — Salsa20 decryption and packet parsing.

No real GT7 captures exist yet (see ROADMAP.md Phase 10), so the parser
is exercised with synthetic packets built to the community-documented
layout and encrypted with the same Salsa20 scheme the console uses.
"""
import struct

import pytest

from telemetry import salsa20
from telemetry.gt7 import (GT7Telemetry, _FLAG_IN_GEAR, _FLAG_LOADING,
                           _FLAG_ON_TRACK, _FLAG_PAUSED, _IV_XOR, _KEY,
                           _MAGIC, _PACKET_SIZE)

# Known-answer vector generated with pycryptodome 3.x Salsa20 (the
# reference implementation), key = GT7 key, nonce = 00..07,
# plaintext = bytes(range(256)) + bytes(40).
_KAT_NONCE = bytes(range(8))
_KAT_PLAINTEXT = bytes(range(256)) + bytes(40)
_KAT_CIPHERTEXT = bytes.fromhex(
    "c007fb7d619a7c8bba43fe51aac11d017447514167355d07021162a13a69460e"
    "31b172b58133efa0948d1d01a79aeeacc75193cd84a1b9610b0b3e7150ada491"
    "8b03b3cd44b667dc22917084933f0c7d5b70ebd7506a5ab28886853df7737112"
    "f50b350a394508c5282307ffebb867dda7985d7bdd13ffcc54645659ca8b70fc"
    "784305d8c9fc5f822cb774a5b1a7c55184c53da75620415f90af23dcd11e906b"
    "3cc2d3274f511ba6a7cf4d7ddbda640276389b2720622067b3a99fad6ac78bcc"
    "bc4b9bac724419c6cd766412b4119925bd947d8d2fe3c82998dc2e472cca4b68"
    "94a7886a8be5d6661b1f2ecef11d76bd690cb53c797d429b448df54f1f010397"
    "b017194387973190b96a71b6bec2ad860ae06148c3622efbcf77932e5b4be945"
    "e88cc3b48c8ea83a"
)


def make_packet(rpm=6500.0, speed_ms=50.0, fuel=40.0, fuel_cap=65.0,
                tyres=(60.0, 61.0, 62.0, 63.0),
                lap=2, total_laps=5, best_ms=95_000, last_ms=96_500,
                position=3, total_cars=16, alert_min=7000, alert_max=8000,
                flags=_FLAG_ON_TRACK | _FLAG_IN_GEAR, gear=3, suggested=15,
                throttle=128, brake=0, car_code=1234,
                iv1=0x12345678) -> bytes:
    """Build an encrypted GT7 packet the way the console would send it."""
    pt = bytearray(_PACKET_SIZE)
    struct.pack_into('<i', pt, 0x00, _MAGIC)
    struct.pack_into('<f', pt, 0x3C, rpm)
    struct.pack_into('<3f', pt, 0x44, fuel, fuel_cap, speed_ms)
    struct.pack_into('<4f', pt, 0x60, *tyres)
    struct.pack_into('<2h', pt, 0x74, lap, total_laps)
    struct.pack_into('<2i', pt, 0x78, best_ms, last_ms)
    struct.pack_into('<2h', pt, 0x84, position, total_cars)
    struct.pack_into('<2H', pt, 0x88, alert_min, alert_max)
    struct.pack_into('<H', pt, 0x8E, flags)
    pt[0x90] = ((suggested & 0x0F) << 4) | (gear & 0x0F)
    pt[0x91] = throttle
    pt[0x92] = brake
    struct.pack_into('<i', pt, 0x124, car_code)

    nonce = struct.pack('<II', iv1 ^ _IV_XOR, iv1)
    ct = bytearray(salsa20.crypt(_KEY, nonce, bytes(pt)))
    # The console stores the IV seed in plaintext at 0x40 over the ciphertext
    struct.pack_into('<I', ct, 0x40, iv1)
    return bytes(ct)


# ---------------------------------------------------------------- salsa20

def test_salsa20_known_answer():
    assert salsa20.crypt(_KEY, _KAT_NONCE, _KAT_PLAINTEXT) == _KAT_CIPHERTEXT


def test_salsa20_decrypt_is_inverse():
    assert salsa20.crypt(_KEY, _KAT_NONCE, _KAT_CIPHERTEXT) == _KAT_PLAINTEXT


def test_salsa20_partial_matches_full_prefix():
    full = salsa20.crypt(_KEY, _KAT_NONCE, _KAT_PLAINTEXT)
    assert salsa20.crypt(_KEY, _KAT_NONCE, _KAT_PLAINTEXT, 0x98) == full[:0x98]


def test_salsa20_rejects_bad_key_and_nonce():
    with pytest.raises(ValueError):
        salsa20.crypt(b'short', _KAT_NONCE, b'data')
    with pytest.raises(ValueError):
        salsa20.crypt(_KEY, b'short', b'data')


# ------------------------------------------------------------------ parse

def _source() -> GT7Telemetry:
    return GT7Telemetry(console_ip="192.168.1.10")


def test_parse_basic_fields():
    data = _source()._parse(make_packet())
    assert data is not None
    assert data.gear == '3'
    assert data.speed == 180.0            # 50 m/s
    assert data.rpm == 6500
    assert data.max_rpm == 8000
    assert data.throttle == round(128 / 255.0, 3)
    assert data.brake == 0.0
    assert data.lap_number == 2
    assert data.total_laps == 5
    assert data.best_lap == 95.0
    assert data.last_lap == 96.5
    assert data.position == 3
    assert data.total_cars == 16
    assert data.tyre_temp == (60.0, 61.0, 62.0, 63.0)
    assert data.fuel_remaining == 40.0
    assert data.fuel_capacity == 65.0
    assert data.session_type == 'race'
    assert data.game == 'gt7'
    assert data.car_class == 'gt7'
    assert data.car_ordinal == 1234


def test_parse_gear_reverse_vs_neutral():
    src = _source()
    in_gear = src._parse(make_packet(gear=0, flags=_FLAG_ON_TRACK | _FLAG_IN_GEAR))
    coasting = src._parse(make_packet(gear=0, flags=_FLAG_ON_TRACK))
    assert in_gear.gear == 'R'
    assert coasting.gear == 'N'


def test_parse_paused_loading_or_off_track_returns_none():
    src = _source()
    assert src._parse(make_packet(flags=_FLAG_ON_TRACK | _FLAG_PAUSED)) is None
    assert src._parse(make_packet(flags=_FLAG_ON_TRACK | _FLAG_LOADING)) is None
    assert src._parse(make_packet(flags=0)) is None


def test_parse_bad_magic_returns_none():
    raw = bytearray(make_packet())
    raw[0] ^= 0xFF
    assert _source()._parse(bytes(raw)) is None


def test_parse_unset_lap_time_sentinels():
    data = _source()._parse(make_packet(best_ms=-1, last_ms=-1, lap=0))
    assert data.best_lap == 0.0
    assert data.last_lap == 0.0
    assert data.lap_number == 0
    assert data.lap_time == 0.0


def test_parse_no_race_laps_means_practice():
    data = _source()._parse(make_packet(total_laps=0))
    assert data.session_type == 'practice'


def test_lap_time_estimated_from_packet_count():
    src = _source()
    src._parse(make_packet(lap=1))          # lap counter change resets ticks
    for _ in range(59):
        data = src._parse(make_packet(lap=1))
    assert data.lap_time == round(59 / 60.0, 3)
    data = src._parse(make_packet(lap=2))   # crossing the line resets again
    assert data.lap_time == 0.0


def test_car_code_cached_between_partial_decrypts():
    src = _source()
    first = src._parse(make_packet(car_code=571))
    assert first.car_ordinal == 571
    # subsequent packets only decrypt the first blocks; the code is cached
    later = src._parse(make_packet(car_code=571))
    assert later.car_ordinal == 571
    assert later.car_name == "Car 571"
