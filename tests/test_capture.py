import socket
import time

import pytest

from telemetry.capture import (CaptureReplayer, PacketRecorder,
                               iter_capture_packets, read_capture_header)


def test_record_and_read_back_round_trip(tmp_path):
    path = str(tmp_path / "session.srtc")
    rec = PacketRecorder(path, game="f1_25", port=20777)
    rec.write(b"\x01\x02\x03")
    rec.write(b"packet-two")
    rec.close()

    assert read_capture_header(path) == ("f1_25", 20777)
    packets = list(iter_capture_packets(path))
    assert [p for _, p in packets] == [b"\x01\x02\x03", b"packet-two"]
    times = [t for t, _ in packets]
    assert times == sorted(times)
    assert all(t >= 0 for t in times)


def test_write_after_close_is_ignored(tmp_path):
    path = str(tmp_path / "session.srtc")
    rec = PacketRecorder(path, game="fm", port=5606)
    rec.write(b"kept")
    rec.close()
    rec.write(b"dropped")
    assert [p for _, p in iter_capture_packets(path)] == [b"kept"]


def test_truncated_tail_is_skipped(tmp_path):
    path = str(tmp_path / "session.srtc")
    rec = PacketRecorder(path, game="fh6", port=5301)
    rec.write(b"complete")
    rec.close()
    with open(path, "ab") as f:
        f.write(b"\x00\x01")   # partial record, as if killed mid-write

    assert [p for _, p in iter_capture_packets(path)] == [b"complete"]


def test_bad_magic_rejected(tmp_path):
    path = tmp_path / "not_a_capture.srtc"
    path.write_bytes(b"nope")
    with pytest.raises(ValueError):
        read_capture_header(str(path))


def test_replayer_sends_packets_over_udp(tmp_path):
    # Receiver on an ephemeral port; capture written against that port
    recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv.bind(("127.0.0.1", 0))
    recv.settimeout(5.0)
    port = recv.getsockname()[1]

    path = str(tmp_path / "session.srtc")
    rec = PacketRecorder(path, game="f1_25", port=port)
    rec.write(b"first")
    rec.write(b"second")
    rec.close()

    replayer = CaptureReplayer(path, speed=100.0, start_delay=0.0)
    assert replayer.game == "f1_25"
    replayer.start()

    received = [recv.recvfrom(65535)[0] for _ in range(2)]
    recv.close()
    replayer.stop()
    assert received == [b"first", b"second"]
