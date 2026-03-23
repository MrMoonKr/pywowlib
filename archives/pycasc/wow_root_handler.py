from __future__ import annotations

from dataclasses import dataclass

from .binary import BinaryReader
from .root_handler_base import RootHandlerBase
from .types import ContentFlags, LocaleFlags, RootEntry, ensure_md5


NO_NAME_HASH_FLAG = 0x10000000
TACT_MAGIC = b"TSFM"


@dataclass(frozen=True)
class WowRootHeader:
    use_old_record_format: bool
    version: int
    total_file_count: int
    named_file_count: int
    allow_non_named_files: bool


class WowRootHandler(RootHandlerBase):
    def __init__(self, stream, progress=None) -> None:
        super().__init__()
        self.root_data: dict[int, list[RootEntry]] = {}
        self.file_data_store_reverse: dict[int, int] = {}
        self.header = self._parse_header(stream)
        reader = BinaryReader(stream)
        total_length = reader.length()
        stream.seek(reader.tell())

        if progress is not None:
            progress(0, 'Loading "root"...')

        while True:
            try:
                self._parse_block(reader)
            except EOFError:
                break

            if progress is not None and total_length:
                progress(int(reader.tell() / total_length * 100), 'Loading "root"...')

    def _parse_header(self, stream) -> WowRootHeader:
        reader = BinaryReader(stream)
        magic = reader.read_bytes(4)
        if magic != TACT_MAGIC:
            reader.seek(-4, 1)
            return WowRootHeader(
                use_old_record_format=True,
                version=0,
                total_file_count=0,
                named_file_count=0,
                allow_non_named_files=True,
            )

        header_size = reader.read_uint32()
        version = 0
        if header_size == 0x18:
            version = reader.read_uint32()
            total_file_count = reader.read_uint32()
        else:
            total_file_count = header_size
            header_size = 0

        named_file_count = reader.read_uint32()
        if header_size == 0x18:
            reader.skip(4)

        return WowRootHeader(
            use_old_record_format=False,
            version=version,
            total_file_count=total_file_count,
            named_file_count=named_file_count,
            allow_non_named_files=total_file_count != named_file_count,
        )

    def _parse_block(self, reader: BinaryReader) -> None:
        num_records = reader.read_uint32()
        if self.header.version == 2:
            locale_flags = LocaleFlags(reader.read_uint32())
            v1 = reader.read_uint32()
            v2 = reader.read_uint32()
            v3 = reader.read_byte()
            content_flags = ContentFlags(v1 | v2 | (v3 << 17))
        else:
            content_flags = ContentFlags(reader.read_uint32())
            locale_flags = LocaleFlags(reader.read_uint32())

        if num_records == 0:
            return

        has_name_hashes = self.header.use_old_record_format or not (
            self.header.allow_non_named_files and (int(content_flags) & NO_NAME_HASH_FLAG)
        )

        file_ids: list[int] = []
        file_id = 0
        for index in range(num_records):
            delta = reader.read_int32()
            if index == 0:
                if delta < 0:
                    raise RuntimeError("FileIdDeltaOverflow")
                file_id = delta
            else:
                file_id = file_id + 1 + delta
                if file_id < 0:
                    raise RuntimeError("FileIdDeltaOverflow")
            file_ids.append(file_id)

        if self.header.use_old_record_format:
            for file_id in file_ids:
                md5 = ensure_md5(reader.read_bytes(16))
                self.root_data.setdefault(file_id, []).append(
                    RootEntry(md5=md5, content_flags=content_flags, locale_flags=locale_flags)
                )
                self.file_data_store_reverse[reader.read_uint64()] = file_id
            return

        for file_id in file_ids:
            md5 = ensure_md5(reader.read_bytes(16))
            self.root_data.setdefault(file_id, []).append(
                RootEntry(md5=md5, content_flags=content_flags, locale_flags=locale_flags)
            )

        if has_name_hashes:
            for file_id in file_ids:
                self.file_data_store_reverse.setdefault(reader.read_uint64(), file_id)

    def hash_name(self, name: str) -> int:
        return self.hasher.compute_hash(name)

    def get_all_entries(self, file_data_id: int) -> list[RootEntry]:
        return list(self.root_data.get(file_data_id, []))

    def get_file_data_ids(self) -> set[int]:
        return set(self.root_data)

    def has_file_data_id(self, file_data_id: int) -> bool:
        return file_data_id in self.root_data

    def get_entries(self, file_data_id: int) -> list[RootEntry]:
        root_infos = self.get_all_entries(file_data_id)
        if not root_infos:
            return []

        locale_matches = [entry for entry in root_infos if entry.locale_flags == LocaleFlags.All or (entry.locale_flags & self.locale)]
        if len(locale_matches) > 1:
            content_matches = [entry for entry in locale_matches if entry.content_flags == self.content]
            if content_matches:
                locale_matches = content_matches
        return locale_matches

    def get_file_data_id_by_hash(self, name_hash: int) -> int:
        return self.file_data_store_reverse.get(name_hash, 0)

    def get_file_data_id_by_name(self, name: str) -> int:
        return self.get_file_data_id_by_hash(self.hash_name(name))
