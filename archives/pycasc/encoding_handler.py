from __future__ import annotations

from .binary import BinaryReader
from .types import EncodingEntry, MD5Hash, ensure_md5


class EncodingHandler:
    CHUNK_SIZE = 4096

    def __init__(self, stream, progress=None) -> None:
        self.encoding_data: dict[MD5Hash, EncodingEntry] = {}
        reader = BinaryReader(stream)

        if progress is not None:
            progress(0, 'Loading "encoding"...')

        reader.skip(2)
        reader.read_byte()
        reader.read_byte()
        reader.read_byte()
        reader.read_uint16()
        reader.read_uint16()
        num_entries_a = reader.read_int32_be()
        num_entries_b = reader.read_int32_be()
        reader.read_byte()
        string_block_size = reader.read_int32_be()

        reader.skip(string_block_size)
        reader.skip(num_entries_a * 32)

        chunk_start = reader.tell()
        for index in range(num_entries_a):
            while True:
                keys_count = reader.read_uint16()
                if keys_count == 0:
                    break

                file_size = reader.read_int32_be()
                md5 = ensure_md5(reader.read_bytes(16))
                first_key = None
                for key_index in range(keys_count):
                    key = ensure_md5(reader.read_bytes(16))
                    if key_index == 0:
                        first_key = key

                self.encoding_data[md5] = EncodingEntry(key=first_key, size=file_size)

            remaining = self.CHUNK_SIZE - ((reader.tell() - chunk_start) % self.CHUNK_SIZE)
            if remaining > 0:
                reader.seek(remaining, 1)

            if progress is not None and num_entries_a:
                progress(int((index + 1) / num_entries_a * 100), 'Loading "encoding"...')

        reader.skip(num_entries_b * 32)
        chunk_start_2 = reader.tell()
        for _ in range(num_entries_b):
            reader.read_bytes(16)
            reader.read_int32_be()
            reader.read_byte()
            reader.read_int32_be()

            remaining = self.CHUNK_SIZE - ((reader.tell() - chunk_start_2) % self.CHUNK_SIZE)
            if remaining > 0:
                reader.seek(remaining, 1)

    @property
    def count(self) -> int:
        return len(self.encoding_data)

    def get_entry(self, md5: MD5Hash) -> EncodingEntry | None:
        return self.encoding_data.get(md5)
