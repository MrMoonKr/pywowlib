from __future__ import annotations


MASK32 = 0xFFFFFFFF


def _rot(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (32 - shift))) & MASK32


def _mix(a: int, b: int, c: int) -> tuple[int, int, int]:
    a = (a - c) & MASK32
    a ^= _rot(c, 4)
    c = (c + b) & MASK32
    b = (b - a) & MASK32
    b ^= _rot(a, 6)
    a = (a + c) & MASK32
    c = (c - b) & MASK32
    c ^= _rot(b, 8)
    b = (b + a) & MASK32
    a = (a - c) & MASK32
    a ^= _rot(c, 16)
    c = (c + b) & MASK32
    b = (b - a) & MASK32
    b ^= _rot(a, 19)
    a = (a + c) & MASK32
    c = (c - b) & MASK32
    c ^= _rot(b, 4)
    b = (b + a) & MASK32
    return a, b, c


def _final(a: int, b: int, c: int) -> tuple[int, int, int]:
    c ^= b
    c = (c - _rot(b, 14)) & MASK32
    a ^= c
    a = (a - _rot(c, 11)) & MASK32
    b ^= a
    b = (b - _rot(a, 25)) & MASK32
    c ^= b
    c = (c - _rot(b, 16)) & MASK32
    a ^= c
    a = (a - _rot(c, 4)) & MASK32
    b ^= a
    b = (b - _rot(a, 14)) & MASK32
    c ^= b
    c = (c - _rot(b, 24)) & MASK32
    return a, b, c


def hashlittle2(data: bytes, pc: int = 0, pb: int = 0) -> tuple[int, int]:
    length = len(data)
    a = b = c = (0xDEADBEEF + length + pc) & MASK32
    c = (c + pb) & MASK32

    offset = 0
    remaining = length
    while remaining > 12:
        a = (a + int.from_bytes(data[offset : offset + 4], "little")) & MASK32
        b = (b + int.from_bytes(data[offset + 4 : offset + 8], "little")) & MASK32
        c = (c + int.from_bytes(data[offset + 8 : offset + 12], "little")) & MASK32
        a, b, c = _mix(a, b, c)
        offset += 12
        remaining -= 12

    tail = data[offset:]
    if remaining >= 12:
        c = (c + (tail[11] << 24)) & MASK32
    if remaining >= 11:
        c = (c + (tail[10] << 16)) & MASK32
    if remaining >= 10:
        c = (c + (tail[9] << 8)) & MASK32
    if remaining >= 9:
        c = (c + tail[8]) & MASK32
    if remaining >= 8:
        b = (b + (tail[7] << 24)) & MASK32
    if remaining >= 7:
        b = (b + (tail[6] << 16)) & MASK32
    if remaining >= 6:
        b = (b + (tail[5] << 8)) & MASK32
    if remaining >= 5:
        b = (b + tail[4]) & MASK32
    if remaining >= 4:
        a = (a + (tail[3] << 24)) & MASK32
    if remaining >= 3:
        a = (a + (tail[2] << 16)) & MASK32
    if remaining >= 2:
        a = (a + (tail[1] << 8)) & MASK32
    if remaining >= 1:
        a = (a + tail[0]) & MASK32
    if remaining == 0:
        return c, b

    a, b, c = _final(a, b, c)
    return c, b


def hashpath(path: str) -> int:
    normalized = path.upper().replace("/", "\\").encode("ascii")
    pc, pb = hashlittle2(normalized, 0, 0)
    return ((pc & MASK32) << 32) | (pb & MASK32)
