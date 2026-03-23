from __future__ import annotations


class Jenkins96:
    def _rot(self, value: int, shift: int) -> int:
        return ((value << shift) | (value >> (32 - shift))) & 0xFFFFFFFF

    def compute_hash(self, value: str, fix: bool = True) -> int:
        if fix:
            value = value.replace("/", "\\").upper()

        data = bytearray(value.encode("ascii"))
        length = len(data)
        a = (0xDEADBEEF + length) & 0xFFFFFFFF
        b = a
        c = a

        if length == 0:
            return ((c << 32) | b) & 0xFFFFFFFFFFFFFFFF

        new_length = length + ((12 - length % 12) % 12)
        if new_length != length:
            data.extend(b"\0" * (new_length - length))
            length = new_length

        for offset in range(0, length - 12, 12):
            a = (a + int.from_bytes(data[offset : offset + 4], "little")) & 0xFFFFFFFF
            b = (b + int.from_bytes(data[offset + 4 : offset + 8], "little")) & 0xFFFFFFFF
            c = (c + int.from_bytes(data[offset + 8 : offset + 12], "little")) & 0xFFFFFFFF

            a = (a - c) & 0xFFFFFFFF
            a ^= self._rot(c, 4)
            c = (c + b) & 0xFFFFFFFF
            b = (b - a) & 0xFFFFFFFF
            b ^= self._rot(a, 6)
            a = (a + c) & 0xFFFFFFFF
            c = (c - b) & 0xFFFFFFFF
            c ^= self._rot(b, 8)
            b = (b + a) & 0xFFFFFFFF
            a = (a - c) & 0xFFFFFFFF
            a ^= self._rot(c, 16)
            c = (c + b) & 0xFFFFFFFF
            b = (b - a) & 0xFFFFFFFF
            b ^= self._rot(a, 19)
            a = (a + c) & 0xFFFFFFFF
            c = (c - b) & 0xFFFFFFFF
            c ^= self._rot(b, 4)
            b = (b + a) & 0xFFFFFFFF

        offset = length - 12
        a = (a + int.from_bytes(data[offset : offset + 4], "little")) & 0xFFFFFFFF
        b = (b + int.from_bytes(data[offset + 4 : offset + 8], "little")) & 0xFFFFFFFF
        c = (c + int.from_bytes(data[offset + 8 : offset + 12], "little")) & 0xFFFFFFFF

        c ^= b
        c = (c - self._rot(b, 14)) & 0xFFFFFFFF
        a ^= c
        a = (a - self._rot(c, 11)) & 0xFFFFFFFF
        b ^= a
        b = (b - self._rot(a, 25)) & 0xFFFFFFFF
        c ^= b
        c = (c - self._rot(b, 16)) & 0xFFFFFFFF
        a ^= c
        a = (a - self._rot(c, 4)) & 0xFFFFFFFF
        b ^= a
        b = (b - self._rot(a, 14)) & 0xFFFFFFFF
        c ^= b
        c = (c - self._rot(b, 24)) & 0xFFFFFFFF

        return ((c << 32) | b) & 0xFFFFFFFFFFFFFFFF
