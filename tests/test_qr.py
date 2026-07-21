"""Tests for core.qr — the vendored pure-stdlib QR encoder.

Correctness is anchored on the canonical Thonky "HELLO WORLD" Reed-Solomon
known-answer vector and on structural invariants (size per version, the three
finder patterns, quiet-zone-free output, determinism). The encoder was also
verified during development to decode with OpenCV's QRCodeDetector for the
pairing-URL shape; that check needs a third-party decoder so it isn't part of
the committed suite.
"""
from core import qr


class TestReedSolomon:
    def test_thonky_hello_world_vector(self):
        # Data codewords for "HELLO WORLD" (alphanumeric, v1-M) and the EC
        # codewords the spec produces — the standard worked example.
        data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64,
                236, 17, 236, 17, 236, 17]
        expected = [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]
        assert qr._rs_encode(data, 10) == expected

    def test_generator_is_monic(self):
        # Leading coefficient of every generator polynomial is 1.
        for deg in (7, 10, 26):
            assert qr._rs_generator(deg)[0] == 1
            assert len(qr._rs_generator(deg)) == deg + 1


class TestEncode:
    URL = "http://192.168.1.30:8765/app?key=ABCD1234"

    def test_size_matches_version_formula(self):
        m = qr.encode(self.URL)
        n = len(m)
        assert all(len(row) == n for row in m)      # square
        assert (n - 17) % 4 == 0                     # n = 4*version + 17
        version = (n - 17) // 4
        assert 1 <= version <= 10

    def test_short_string_is_version_1(self):
        assert len(qr.encode("HI")) == 21            # v1 = 21x21

    def test_longer_string_grows_the_symbol(self):
        assert len(qr.encode("x" * 100)) > len(qr.encode("x" * 10))

    def test_deterministic(self):
        assert qr.encode(self.URL) == qr.encode(self.URL)

    def test_finder_patterns_present(self):
        m = qr.encode(self.URL)
        n = len(m)
        # 7x7 finder with a 3x3 dark core at all three corners.
        for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
            assert m[r0][c0] and m[r0 + 6][c0 + 6]           # outer corners dark
            assert m[r0 + 3][c0 + 3]                         # centre dark
            assert not m[r0 + 1][c0 + 1]                     # inner ring light

    def test_timing_pattern_alternates(self):
        m = qr.encode(self.URL)
        row6 = m[6][8:len(m) - 8]
        assert all(row6[i] == (i % 2 == 0) for i in range(len(row6)))

    def test_no_quiet_zone(self):
        # The matrix itself carries no border — at least one edge module is dark
        # (the finder patterns touch the corners).
        m = qr.encode(self.URL)
        assert m[0][0] is True

    def test_too_long_raises(self):
        import pytest
        with pytest.raises(ValueError):
            qr.encode("x" * 400)
