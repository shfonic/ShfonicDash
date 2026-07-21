"""Pure-Python Salsa20 stream cipher — used to decrypt GT7 telemetry.

GT7 encrypts every telemetry packet with Salsa20/20 (32-byte key, 8-byte
nonce). Implemented here in plain stdlib Python so the Pi needs no
third-party crypto package (pygame stays the project's only dependency).
Verified against a pycryptodome-generated known-answer vector in
tests/test_gt7.py.

Salsa20 is a stream cipher: encryption and decryption are the same XOR,
and the keystream is generated in independent 64-byte blocks, so `crypt`
can stop after only the blocks a caller actually needs — the GT7 source
decrypts 3 blocks per packet instead of all 5 (see gt7.py).

The double-round is fully unrolled with local variables; that makes this
~4x faster than a loop-over-indices version, which matters at 60
packets/s on the Pi 3 (measured cost is recorded in gt7.py).
"""
import struct

_M = 0xFFFFFFFF


def _block(k0, k1, k2, k3, k4, k5, k6, k7, n0, n1, c0, c1) -> bytes:
    """One 64-byte Salsa20/20 keystream block for key/nonce/counter words."""
    x0 = y0 = 0x61707865            # "expa"
    x1, x2, x3, x4 = y1, y2, y3, y4 = k0, k1, k2, k3
    x5 = y5 = 0x3320646E            # "nd 3"
    x6, x7, x8, x9 = y6, y7, y8, y9 = n0, n1, c0, c1
    x10 = y10 = 0x79622D32          # "2-by"
    x11, x12, x13, x14 = y11, y12, y13, y14 = k4, k5, k6, k7
    x15 = y15 = 0x6B206574          # "te k"

    for _ in range(10):
        # Column round
        t = (x0 + x12) & _M; x4 ^= ((t << 7) | (t >> 25)) & _M
        t = (x4 + x0) & _M; x8 ^= ((t << 9) | (t >> 23)) & _M
        t = (x8 + x4) & _M; x12 ^= ((t << 13) | (t >> 19)) & _M
        t = (x12 + x8) & _M; x0 ^= ((t << 18) | (t >> 14)) & _M

        t = (x5 + x1) & _M; x9 ^= ((t << 7) | (t >> 25)) & _M
        t = (x9 + x5) & _M; x13 ^= ((t << 9) | (t >> 23)) & _M
        t = (x13 + x9) & _M; x1 ^= ((t << 13) | (t >> 19)) & _M
        t = (x1 + x13) & _M; x5 ^= ((t << 18) | (t >> 14)) & _M

        t = (x10 + x6) & _M; x14 ^= ((t << 7) | (t >> 25)) & _M
        t = (x14 + x10) & _M; x2 ^= ((t << 9) | (t >> 23)) & _M
        t = (x2 + x14) & _M; x6 ^= ((t << 13) | (t >> 19)) & _M
        t = (x6 + x2) & _M; x10 ^= ((t << 18) | (t >> 14)) & _M

        t = (x15 + x11) & _M; x3 ^= ((t << 7) | (t >> 25)) & _M
        t = (x3 + x15) & _M; x7 ^= ((t << 9) | (t >> 23)) & _M
        t = (x7 + x3) & _M; x11 ^= ((t << 13) | (t >> 19)) & _M
        t = (x11 + x7) & _M; x15 ^= ((t << 18) | (t >> 14)) & _M

        # Row round
        t = (x0 + x3) & _M; x1 ^= ((t << 7) | (t >> 25)) & _M
        t = (x1 + x0) & _M; x2 ^= ((t << 9) | (t >> 23)) & _M
        t = (x2 + x1) & _M; x3 ^= ((t << 13) | (t >> 19)) & _M
        t = (x3 + x2) & _M; x0 ^= ((t << 18) | (t >> 14)) & _M

        t = (x5 + x4) & _M; x6 ^= ((t << 7) | (t >> 25)) & _M
        t = (x6 + x5) & _M; x7 ^= ((t << 9) | (t >> 23)) & _M
        t = (x7 + x6) & _M; x4 ^= ((t << 13) | (t >> 19)) & _M
        t = (x4 + x7) & _M; x5 ^= ((t << 18) | (t >> 14)) & _M

        t = (x10 + x9) & _M; x11 ^= ((t << 7) | (t >> 25)) & _M
        t = (x11 + x10) & _M; x8 ^= ((t << 9) | (t >> 23)) & _M
        t = (x8 + x11) & _M; x9 ^= ((t << 13) | (t >> 19)) & _M
        t = (x9 + x8) & _M; x10 ^= ((t << 18) | (t >> 14)) & _M

        t = (x15 + x14) & _M; x12 ^= ((t << 7) | (t >> 25)) & _M
        t = (x12 + x15) & _M; x13 ^= ((t << 9) | (t >> 23)) & _M
        t = (x13 + x12) & _M; x14 ^= ((t << 13) | (t >> 19)) & _M
        t = (x14 + x13) & _M; x15 ^= ((t << 18) | (t >> 14)) & _M

    return struct.pack(
        '<16I',
        (x0 + y0) & _M, (x1 + y1) & _M, (x2 + y2) & _M, (x3 + y3) & _M,
        (x4 + y4) & _M, (x5 + y5) & _M, (x6 + y6) & _M, (x7 + y7) & _M,
        (x8 + y8) & _M, (x9 + y9) & _M, (x10 + y10) & _M, (x11 + y11) & _M,
        (x12 + y12) & _M, (x13 + y13) & _M, (x14 + y14) & _M, (x15 + y15) & _M,
    )


def crypt(key: bytes, nonce: bytes, data: bytes, nbytes: int | None = None) -> bytes:
    """XOR `data` with the Salsa20/20 keystream (encrypt == decrypt).

    `nbytes` caps how many leading bytes are processed; the rest of
    `data` is not returned. Keystream starts at block counter 0.
    """
    if len(key) != 32:
        raise ValueError("Salsa20 key must be 32 bytes")
    if len(nonce) != 8:
        raise ValueError("Salsa20 nonce must be 8 bytes")
    n = len(data) if nbytes is None else min(nbytes, len(data))
    k = struct.unpack('<8I', key)
    n0, n1 = struct.unpack('<2I', nonce)

    out = bytearray()
    counter = 0
    while len(out) < n:
        ks = _block(*k, n0, n1, counter & _M, (counter >> 32) & _M)
        chunk = data[len(out):len(out) + 64]
        out += bytes(a ^ b for a, b in zip(chunk, ks))
        counter += 1
    return bytes(out[:n])
