"""Minimal, dependency-free QR Code encoder (byte mode).

Vendored pure-stdlib QR generator — no `qrcode`/`segno`/C extension — mirroring
the `src/telemetry/salsa20.py` precedent (keep the Pi's dependency set to pygame
alone). It exists to turn the web-companion pairing URL
(`http://<lan-ip>:8765/app?key=<token>`) into a scannable code on the DATA tab.

Scope is deliberately small: byte (8-bit) mode, error-correction level M,
automatic version selection over versions 1–10 (a LAN URL is ~40–60 bytes; v10-M
holds 271). That covers everything this app needs and nothing it doesn't.

`encode(text)` returns a square list-of-lists of booleans (True = dark module),
*without* a quiet zone — the caller adds margin when rendering. The matrix is a
pure data structure so it can be drawn to a pygame surface, an SVG, or asserted
against in tests without any rendering dependency.

Implements ISO/IEC 18004: GF(256) Reed-Solomon, the block/interleave layout,
the eight data masks with the standard penalty scoring, and BCH-coded format and
version information.
"""

# ── Galois field GF(256) with primitive polynomial 0x11d ────────────────────
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11d
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list:
    """Reed-Solomon generator polynomial (index 0 = highest-degree term,
    leading coefficient 1) — the product of (x - alpha^i) for i in 0..degree-1."""
    g = [1]
    for i in range(degree):
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= c                      # g * x
            ng[j + 1] ^= _gf_mul(c, _EXP[i])  # g * alpha^i
        g = ng
    return g


def _rs_encode(data: list, ec_len: int) -> list:
    """EC codewords for a block of data codewords (polynomial long division of
    the message by the generator; the remainder is the EC codeword sequence)."""
    gen = _rs_generator(ec_len)             # gen[0] == 1
    msg = list(data) + [0] * ec_len
    for i in range(len(data)):
        coef = msg[i]
        if coef:
            for j in range(1, len(gen)):
                msg[i + j] ^= _gf_mul(gen[j], coef)
    return msg[len(data):]


# ── Error-correction characteristics (ISO/IEC 18004, level M, v1–10) ────────
# Per version: (ec_codewords_per_block, [(block_count, data_cw_per_block), ...])
_EC_M = {
    1:  (10, [(1, 16)]),
    2:  (16, [(1, 28)]),
    3:  (26, [(1, 44)]),
    4:  (18, [(2, 32)]),
    5:  (24, [(2, 43)]),
    6:  (16, [(4, 27)]),
    7:  (18, [(4, 31)]),
    8:  (22, [(2, 38), (2, 39)]),
    9:  (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}

# Alignment-pattern centre coordinates per version (empty for v1).
_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

_EC_LEVEL_BITS = 0b00        # level M format indicator


def _total_data_codewords(version: int) -> int:
    _, blocks = _EC_M[version]
    return sum(count * cw for count, cw in blocks)


def _char_count_bits(version: int) -> int:
    return 8 if version <= 9 else 16      # byte mode


def _choose_version(nbytes: int) -> int:
    for v in range(1, 11):
        overhead = 4 + _char_count_bits(v)          # mode + length indicators
        capacity_bits = _total_data_codewords(v) * 8
        if overhead + nbytes * 8 <= capacity_bits:
            return v
    raise ValueError("data too long for a version-10 byte-mode QR "
                     f"({nbytes} bytes)")


# ── data bitstream ──────────────────────────────────────────────────────────

def _build_codewords(data: bytes, version: int) -> list:
    ccb = _char_count_bits(version)
    bits = []

    def _push(value: int, length: int):
        for i in range(length - 1, -1, -1):
            bits.append((value >> i) & 1)

    _push(0b0100, 4)                # byte mode indicator
    _push(len(data), ccb)           # character count
    for byte in data:
        _push(byte, 8)

    capacity = _total_data_codewords(version) * 8
    _push(0, min(4, capacity - len(bits)))      # terminator (up to 4 zero bits)
    while len(bits) % 8:                        # pad to a byte boundary
        bits.append(0)

    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]                           # standard pad bytes, alternating
    i = 0
    while len(codewords) < _total_data_codewords(version):
        codewords.append(pad[i % 2])
        i += 1
    return codewords


def _interleave(codewords: list, version: int) -> list:
    ec_len, block_spec = _EC_M[version]
    blocks = []
    pos = 0
    for count, data_cw in block_spec:
        for _ in range(count):
            data = codewords[pos:pos + data_cw]
            pos += data_cw
            blocks.append((data, _rs_encode(data, ec_len)))

    result = []
    max_data = max(len(d) for d, _ in blocks)
    for i in range(max_data):                    # interleave data codewords
        for d, _ in blocks:
            if i < len(d):
                result.append(d[i])
    for i in range(ec_len):                      # interleave EC codewords
        for _, e in blocks:
            result.append(e[i])
    return result


# ── matrix construction ─────────────────────────────────────────────────────

def _new_matrix(size: int):
    # module value (0/1) and a "reserved/function" mask
    modules = [[0] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]
    return modules, reserved


def _place_finder(modules, reserved, size, r, c):
    for dr in range(-1, 8):
        for dc in range(-1, 8):
            rr, cc = r + dr, c + dc
            if not (0 <= rr < size and 0 <= cc < size):
                continue
            reserved[rr][cc] = True
            in_ring = (0 <= dr <= 6 and 0 <= dc <= 6)
            if in_ring:
                edge = dr in (0, 6) or dc in (0, 6)
                core = 2 <= dr <= 4 and 2 <= dc <= 4
                modules[rr][cc] = 1 if (edge or core) else 0
            else:
                modules[rr][cc] = 0          # separator


def _place_alignment(modules, reserved, size, version):
    centres = _ALIGN[version]
    for r in centres:
        for c in centres:
            # skip the three finder corners
            if (r <= 8 and c <= 8) or (r <= 8 and c >= size - 9) \
                    or (r >= size - 9 and c <= 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    rr, cc = r + dr, c + dc
                    reserved[rr][cc] = True
                    ring = max(abs(dr), abs(dc))
                    modules[rr][cc] = 1 if ring != 1 else 0


def _place_timing(modules, reserved, size):
    for i in range(8, size - 8):
        val = 1 if i % 2 == 0 else 0
        if not reserved[6][i]:
            modules[6][i] = val
            reserved[6][i] = True
        if not reserved[i][6]:
            modules[i][6] = val
            reserved[i][6] = True


def _reserve_format(reserved, size, version):
    for i in range(9):                    # around top-left finder
        reserved[8][i] = True
        reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True
    reserved[size - 8][8] = True          # always-dark module
    if version >= 7:
        for i in range(6):
            for j in range(3):
                reserved[size - 11 + j][i] = True
                reserved[i][size - 11 + j] = True


def _place_data(modules, reserved, size, bitstream):
    idx = 0
    up = True
    col = size - 1
    while col > 0:
        if col == 6:                      # skip the vertical timing column
            col -= 1
        rows = range(size - 1, -1, -1) if up else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                bit = bitstream[idx] if idx < len(bitstream) else 0
                modules[row][c] = bit
                idx += 1
        up = not up
        col -= 2


_MASKS = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def _bch_format(fmt5: int) -> int:
    """15-bit BCH-coded format information (generator 0x537, XOR 0x5412)."""
    d = fmt5 << 10
    g = 0x537
    for i in range(4, -1, -1):
        if d & (1 << (i + 10)):
            d ^= g << i
    return ((fmt5 << 10) | d) ^ 0x5412


def _bch_version(version: int) -> int:
    """18-bit BCH-coded version information (generator 0x1f25)."""
    d = version << 12
    g = 0x1f25
    for i in range(5, -1, -1):
        if d & (1 << (i + 12)):
            d ^= g << i
    return (version << 12) | d


def _apply_format(modules, size, mask_index):
    fmt = _bch_format((_EC_LEVEL_BITS << 3) | mask_index)
    bits = [(fmt >> i) & 1 for i in range(14, -1, -1)]
    # copy 1 (around top-left finder)
    coords1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
               (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    for bit, (r, c) in zip(bits, coords1):
        modules[r][c] = bit
    # copy 2 (split along the other two finders)
    coords2 = [(size - 1, 8), (size - 2, 8), (size - 3, 8), (size - 4, 8),
               (size - 5, 8), (size - 6, 8), (size - 7, 8),
               (8, size - 8), (8, size - 7), (8, size - 6), (8, size - 5),
               (8, size - 4), (8, size - 3), (8, size - 2), (8, size - 1)]
    for bit, (r, c) in zip(bits, coords2):
        modules[r][c] = bit
    modules[size - 8][8] = 1              # always-dark module


def _apply_version(modules, size, version):
    if version < 7:
        return
    v = _bch_version(version)
    bits = [(v >> i) & 1 for i in range(17, -1, -1)]
    # 18 bits placed in two 6x3 blocks, least-significant bit first
    k = 0
    for i in range(6):
        for j in range(3):
            bit = bits[17 - k]
            modules[size - 11 + j][i] = bit
            modules[i][size - 11 + j] = bit
            k += 1


def _penalty(modules, size) -> int:
    score = 0
    # Rule 1: runs of five or more same-colour modules in a row/column
    for line in (modules, [list(col) for col in zip(*modules)]):
        for row in line:
            run = 1
            for i in range(1, size):
                if row[i] == row[i - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run = 1
            if run >= 5:
                score += 3 + (run - 5)
    # Rule 2: 2x2 same-colour blocks
    for r in range(size - 1):
        for c in range(size - 1):
            v = modules[r][c]
            if v == modules[r][c + 1] == modules[r + 1][c] == modules[r + 1][c + 1]:
                score += 3
    # Rule 3: finder-like 1:1:3:1:1 patterns (with 4-module quiet run)
    pat1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pat2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for line in (modules, [list(col) for col in zip(*modules)]):
        for row in line:
            for i in range(size - 10):
                seg = row[i:i + 11]
                if seg == pat1 or seg == pat2:
                    score += 40
    # Rule 4: dark-module proportion deviation from 50%
    dark = sum(sum(row) for row in modules)
    ratio = dark * 100 // (size * size)
    score += (abs(ratio - 50) // 5) * 10
    return score


def encode(text: str) -> list:
    """Encode `text` as a QR matrix — a square list of bool rows, no quiet zone.

    True is a dark module. Uses byte mode, EC level M, and the smallest version
    (1–10) that fits, choosing the mask with the lowest penalty score.
    """
    data = text.encode("utf-8")
    version = _choose_version(len(data))
    size = version * 4 + 17

    codewords = _build_codewords(data, version)
    bitstream_bytes = _interleave(codewords, version)
    bitstream = [(b >> i) & 1 for b in bitstream_bytes for i in range(7, -1, -1)]

    # Remainder bits (versions 2–6 need 7, 7–13 need 0; v1 needs 0).
    remainder = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7,
                 7: 0, 8: 0, 9: 0, 10: 0}[version]
    bitstream += [0] * remainder

    base_mod, reserved = _new_matrix(size)
    _place_finder(base_mod, reserved, size, 0, 0)
    _place_finder(base_mod, reserved, size, 0, size - 7)
    _place_finder(base_mod, reserved, size, size - 7, 0)
    _place_alignment(base_mod, reserved, size, version)
    _place_timing(base_mod, reserved, size)
    _reserve_format(reserved, size, version)
    _place_data(base_mod, reserved, size, bitstream)

    best = None
    for mask_index, mask_fn in enumerate(_MASKS):
        modules = [row[:] for row in base_mod]
        for r in range(size):
            for c in range(size):
                if not reserved[r][c] and mask_fn(r, c):
                    modules[r][c] ^= 1
        _apply_format(modules, size, mask_index)
        _apply_version(modules, size, version)
        score = _penalty(modules, size)
        if best is None or score < best[0]:
            best = (score, modules)

    return [[bool(v) for v in row] for row in best[1]]
