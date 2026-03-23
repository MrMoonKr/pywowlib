from __future__ import annotations

import io
import struct
from typing import BinaryIO


class BinaryReader:
    def __init__(self, stream: BinaryIO):
        self.stream = stream

    def tell(self) -> int:
        return self.stream.tell()

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self.stream.seek(offset, whence)

    def length(self) -> int:
        current = self.tell()
        self.seek(0, io.SEEK_END)
        size = self.tell()
        self.seek(current, io.SEEK_SET)
        return size

    def skip(self, count: int) -> None:
        self.seek(count, io.SEEK_CUR)

    def read_bytes(self, count: int) -> bytes:
        data = self.stream.read(count)
        if len(data) != count:
            raise EOFError(f"Expected {count} bytes, got {len(data)}")
        return data

    def read_byte(self) -> int:
        return self.read_bytes(1)[0]

    def read_uint16(self) -> int:
        return struct.unpack("<H", self.read_bytes(2))[0]

    def read_uint16_be(self) -> int:
        return struct.unpack(">H", self.read_bytes(2))[0]

    def read_int32(self) -> int:
        return struct.unpack("<i", self.read_bytes(4))[0]

    def read_uint32(self) -> int:
        return struct.unpack("<I", self.read_bytes(4))[0]

    def read_uint64(self) -> int:
        return struct.unpack("<Q", self.read_bytes(8))[0]

    def read_int32_be(self) -> int:
        return struct.unpack(">i", self.read_bytes(4))[0]

    def read_uint32_be(self) -> int:
        return struct.unpack(">I", self.read_bytes(4))[0]
