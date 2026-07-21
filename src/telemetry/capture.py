"""
Raw UDP packet capture and replay.

Real-session bugs are hard to reproduce: mock data never matches real packet
timing/content, and the console is not always available. `--record` dumps the
raw UDP stream of a live session to a file; `--replay <file>` plays it back by
sending the packets over real UDP to 127.0.0.1:<port>, so the app runs
completely unmodified (real socket, real parser). Captures double as
regression-test fixtures.

Capture file format (binary, little-endian):
  Header:   magic b"SRTC", uint8 version (=1),
            uint8 game_len, game bytes (utf-8, e.g. "f1_25"), uint16 port
  Records:  float64 t (seconds since capture start), uint32 length, raw bytes
"""

import logging
import os
import socket
import struct
import threading
import time

log = logging.getLogger("capture")

_MAGIC = b"SRTC"
_VERSION = 1
_FLUSH_EVERY = 100  # packets


class PacketRecorder:
    """Appends raw UDP packets with timestamps to a capture file. Thread-safe."""

    def __init__(self, path: str, game: str, port: int):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        game_b = game.encode("utf-8")
        self.path = path
        self._file = open(path, "wb")
        self._file.write(_MAGIC + struct.pack("<BB", _VERSION, len(game_b))
                         + game_b + struct.pack("<H", port))
        self._t0 = time.monotonic()
        self._count = 0
        self._lock = threading.Lock()
        log.info(f"Recording raw packets to {path}")

    def write(self, packet: bytes) -> None:
        t = time.monotonic() - self._t0
        with self._lock:
            if self._file.closed:
                return
            self._file.write(struct.pack("<dI", t, len(packet)))
            self._file.write(packet)
            self._count += 1
            if self._count % _FLUSH_EVERY == 0:
                self._file.flush()

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()
                log.info(f"Saved {self._count} packets to {self.path}")


def read_capture_header(path: str) -> tuple[str, int]:
    """Return (game, port) from a capture file's header."""
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != _MAGIC:
            raise ValueError(f"{path!r} is not a capture file (bad magic {magic!r})")
        version, game_len = struct.unpack("<BB", f.read(2))
        if version != _VERSION:
            raise ValueError(f"Unsupported capture version {version}")
        game = f.read(game_len).decode("utf-8")
        port = struct.unpack("<H", f.read(2))[0]
    return game, port


def iter_capture_packets(path: str):
    """Yield (t, packet_bytes) records from a capture file."""
    game, _ = read_capture_header(path)
    header_len = 4 + 2 + len(game.encode("utf-8")) + 2
    with open(path, "rb") as f:
        f.seek(header_len)
        while True:
            rec = f.read(12)
            if len(rec) < 12:
                return
            t, length = struct.unpack("<dI", rec)
            packet = f.read(length)
            if len(packet) < length:
                return  # truncated tail (e.g. app was killed mid-write)
            yield t, packet


class CaptureReplayer:
    """Sends a capture file's packets to 127.0.0.1:<port> at recorded timing."""

    def __init__(self, path: str, speed: float = 1.0, start_delay: float = 0.5):
        self._path = path
        self._speed = max(0.01, speed)
        self._start_delay = start_delay
        self.game, self.port = read_capture_header(path)
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _wait_for_listener(self, timeout: float = 15.0) -> None:
        """Block until something binds the target port (the app's UDP source).

        Probes by trying to bind the port ourselves: while the bind succeeds the
        port is still free, so the app isn't listening yet; once it fails the
        listener is up. Avoids losing the first seconds of the capture to
        pygame start-up time.
        """
        deadline = time.monotonic() + timeout
        while self._running and time.monotonic() < deadline:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.bind(("0.0.0.0", self.port))
            except OSError:
                probe.close()
                return
            probe.close()
            time.sleep(0.2)

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        time.sleep(self._start_delay)
        self._wait_for_listener()
        log.info(f"Sending {self._path} to 127.0.0.1:{self.port} "
              f"at {self._speed:g}x")
        t0 = time.monotonic()
        count = 0
        for t, packet in iter_capture_packets(self._path):
            if not self._running:
                break
            target = t / self._speed
            wait = target - (time.monotonic() - t0)
            if wait > 0:
                time.sleep(wait)
            sock.sendto(packet, ("127.0.0.1", self.port))
            count += 1
        sock.close()
        log.info(f"Finished ({count} packets sent)")
