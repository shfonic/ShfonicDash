"""Gran Turismo 7 telemetry source (PlayStation).

GT7 is not a passive broadcaster like every other supported game: the
console only streams telemetry to a client that keeps sending heartbeat
packets ('A') to UDP port 33739 on the console. Replies arrive on port
33740 as 296-byte packets encrypted with Salsa20 (see salsa20.py); the
8-byte nonce is derived from a plaintext IV dword inside each packet.

Console discovery: by default the heartbeat is broadcast to the local
network (255.255.255.255) and the source locks onto whichever address
answers, so no IP needs to be configured. A fixed console IP can be set
with --gt7-ip or "gt7_ip" in config.json.

Protocol references: github.com/Bornhall/gt7telemetry and
github.com/Nenkai/PDTools (SimulatorInterfaceClient).

**UNTESTED IN-HOUSE** — built from the community-documented packet
layout only (no GT7 setup available; see ROADMAP.md Phase 10). If you
run this against a real console, please record a capture with --record
and share it. Do not claim this parser verified until a real capture
has been replayed against it.

Field notes vs other games:
- No current-lap time in the packet — estimated from the 60 Hz packet
  counter since the last lap-line crossing.
- No sector times, no participants, no gaps, no pit/flag state.
- position/total_cars are only meaningful pre-race (grid/quali slot).
- best/last lap are -1 ms when not set.
"""
import logging
import socket
import struct
import threading

from telemetry.base import TelemetrySource, TelemetryData
from telemetry import salsa20

log = logging.getLogger("gt7")

_RECV_PORT = 33740          # console → us (telemetry)
_SEND_PORT = 33739          # us → console (heartbeat)
_PACKET_SIZE = 0x128        # 296 bytes ('A' heartbeat packet format)
_HEARTBEAT = b'A'
_HEARTBEAT_EVERY = 100      # packets between heartbeats (~1.6 s at 60 Hz)

_KEY = b'Simulator Interface Packet GT7 ver 0.0'[:32]
_IV_XOR = 0xDEADBEAF        # sic — not DEADBEEF
_MAGIC = 0x47375330         # 'G7S0' little-endian at offset 0 after decryption

# Everything the per-frame parse needs sits below offset 0x94 → the first
# three 64-byte Salsa20 blocks. Only the car code (0x124) lives beyond, and
# it can't change mid-stint, so the full packet is decrypted once a second.
_PARTIAL_LEN = 0x98
_CAR_CODE_EVERY = 60

# SimulatorFlags bits (Nenkai/PDTools)
_FLAG_ON_TRACK = 1 << 0
_FLAG_PAUSED = 1 << 1
_FLAG_LOADING = 1 << 2
_FLAG_IN_GEAR = 1 << 3


def _gear_str(gear_nibble: int, in_gear: bool) -> str:
    # Current gear 0 is both reverse and neutral in GT7; the InGear flag
    # separates them (engaged → R, disengaged → N).
    if gear_nibble == 0:
        return 'R' if in_gear else 'N'
    return str(gear_nibble)


class GT7Telemetry(TelemetrySource):
    """Gran Turismo 7 SimulatorInterface UDP source (active heartbeat)."""

    def __init__(self, console_ip: str | None = None, port: int = _RECV_PORT,
                 record_path: str | None = None):
        self._port = port
        self._record_path = record_path
        self._recorder = None
        self._fixed_ip = console_ip
        self._console_addr = (console_ip or '255.255.255.255', _SEND_PORT)
        self._locked = console_ip is not None
        self._lock = threading.Lock()
        self._data = TelemetryData()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._pkt_since_hb = 0
        self._car_code = 0
        self._car_code_countdown = 0
        self._last_lap_number = 0
        self._lap_ticks = 0          # 60 Hz packets since the last lap line

    def connect(self) -> None:
        if self._record_path:
            from telemetry.capture import PacketRecorder
            self._recorder = PacketRecorder(self._record_path, game="gt7", port=self._port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.bind(('', self._port))
        self._sock.settimeout(1.0)
        self._running = True
        self._send_heartbeat()
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()
        target = self._fixed_ip or "broadcast (auto-discover)"
        log.info(f"Listening on UDP port {self._port}, heartbeat → {target}:{_SEND_PORT}")
        log.warning("GT7 support is BETA and untested against a real console — "
                    "please record this session with --record and share the capture")

    def read(self) -> TelemetryData:
        with self._lock:
            return self._data

    def disconnect(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._recorder:
            self._recorder.close()
            self._recorder = None
        log.info("Disconnected")

    def _send_heartbeat(self) -> None:
        try:
            self._sock.sendto(_HEARTBEAT, self._console_addr)
        except OSError as e:
            log.debug(f"Heartbeat send failed: {e}")
        self._pkt_since_hb = 0

    def _recv_loop(self) -> None:
        while self._running:
            try:
                raw, addr = self._sock.recvfrom(1024)
            except socket.timeout:
                # No stream (yet) — keep knocking so the console starts
                # sending, and recovers if it was restarted.
                self._send_heartbeat()
                continue
            except OSError:
                break
            if self._recorder:
                self._recorder.write(raw)
            if not self._locked:
                # First reply wins: heartbeats go to the console that
                # answered the broadcast (or to localhost during --replay).
                self._console_addr = (addr[0], _SEND_PORT)
                self._locked = True
                log.info(f"Console found at {addr[0]}")
            self._pkt_since_hb += 1
            if self._pkt_since_hb >= _HEARTBEAT_EVERY:
                self._send_heartbeat()
            if len(raw) < _PACKET_SIZE:
                continue
            try:
                parsed = self._parse(raw)
                with self._lock:
                    if parsed is not None:
                        self._data = parsed
                    elif self._data.game_paused is False:
                        self._data = TelemetryData(**{**self._data.__dict__, "game_paused": True})
            except Exception:
                pass

    def _decrypt(self, raw: bytes, nbytes: int) -> bytes | None:
        iv1 = struct.unpack_from('<I', raw, 0x40)[0]
        nonce = struct.pack('<II', iv1 ^ _IV_XOR, iv1)
        dec = salsa20.crypt(_KEY, nonce, raw, nbytes)
        if struct.unpack_from('<i', dec, 0)[0] != _MAGIC:
            return None
        return dec

    def _parse(self, raw: bytes) -> TelemetryData | None:
        # Full decrypt only when the cached car code is due a refresh.
        if self._car_code_countdown <= 0:
            dec = self._decrypt(raw, _PACKET_SIZE)
            if dec is not None:
                new_code = struct.unpack_from('<i', dec, 0x124)[0]
                if new_code != self._car_code:
                    self._car_code = new_code
                    log.info(f"car_code={new_code}")
                self._car_code_countdown = _CAR_CODE_EVERY
        else:
            dec = self._decrypt(raw, _PARTIAL_LEN)
        if dec is None:
            return None
        self._car_code_countdown -= 1

        rpm = struct.unpack_from('<f', dec, 0x3C)[0]
        fuel, fuel_cap, speed_ms = struct.unpack_from('<3f', dec, 0x44)
        t_fl, t_fr, t_rl, t_rr = struct.unpack_from('<4f', dec, 0x60)
        lap_number, total_laps = struct.unpack_from('<2h', dec, 0x74)
        best_ms, last_ms = struct.unpack_from('<2i', dec, 0x78)
        position, total_cars = struct.unpack_from('<2h', dec, 0x84)
        alert_min, alert_max = struct.unpack_from('<2H', dec, 0x88)
        flags = struct.unpack_from('<H', dec, 0x8E)[0]
        gear_byte, throttle, brake = struct.unpack_from('<3B', dec, 0x90)

        if not flags & _FLAG_ON_TRACK or flags & (_FLAG_PAUSED | _FLAG_LOADING):
            return None

        # No current-lap time in the packet: count 60 Hz frames since the
        # lap counter last changed (paused/menu frames never get here).
        if lap_number != self._last_lap_number:
            self._last_lap_number = lap_number
            self._lap_ticks = 0
        elif lap_number > 0:
            self._lap_ticks += 1

        return TelemetryData(
            gear=_gear_str(gear_byte & 0x0F, bool(flags & _FLAG_IN_GEAR)),
            speed=round(speed_ms * 3.6, 1),
            rpm=int(rpm),
            max_rpm=int(alert_max) if alert_max > 0 else 8000,
            throttle=round(throttle / 255.0, 3),
            brake=round(brake / 255.0, 3),
            lap_time=round(self._lap_ticks / 60.0, 3) if lap_number > 0 else 0.0,
            last_lap=round(last_ms / 1000.0, 3) if last_ms > 0 else 0.0,
            best_lap=round(best_ms / 1000.0, 3) if best_ms > 0 else 0.0,
            lap_number=max(int(lap_number), 0),
            total_laps=max(int(total_laps), 0),
            position=int(position) if position > 0 else 0,
            total_cars=int(total_cars) if total_cars > 0 else 0,
            tyre_temp=(round(t_fl, 1), round(t_fr, 1), round(t_rl, 1), round(t_rr, 1)),
            fuel_remaining=round(fuel, 1),
            fuel_capacity=round(fuel_cap, 1),
            fuel_per_lap=0.0,
            session_type='race' if total_laps > 0 else 'practice',
            game='gt7',
            car_class='gt7',
            car_name=f"Car {self._car_code}" if self._car_code else "",
            car_ordinal=self._car_code,
        )
