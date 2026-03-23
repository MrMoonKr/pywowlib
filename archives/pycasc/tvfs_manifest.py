from __future__ import annotations

import io
from dataclasses import dataclass

from .binary import BinaryReader


TVFS_MAGIC = b"TVFS"
PATH_SEPARATOR_PRE = 0x01
PATH_SEPARATOR_POST = 0x02
IS_NODE_VALUE = 0x04


def _read_variable_size_int(reader: BinaryReader, data_size: int) -> int:
    if data_size > 0xFFFFFF:
        return reader.read_uint32_be()
    if data_size > 0xFFFF:
        data = reader.read_bytes(3)
        return (data[0] << 16) | (data[1] << 8) | data[2]
    if data_size > 0xFF:
        return reader.read_uint16_be()
    if data_size > 0:
        return reader.read_byte()
    return 0


def _peek_byte(reader: BinaryReader) -> int:
    pos = reader.tell()
    value = reader.read_byte()
    reader.seek(pos)
    return value


@dataclass(frozen=True)
class TVFSHeader:
    magic: bytes
    version: int
    header_size: int
    ekey_size: int
    patch_key_size: int
    flags: int
    path_table_offset: int
    path_table_size: int
    vfs_table_offset: int
    vfs_table_size: int
    cft_table_offset: int
    cft_table_size: int
    max_depth: int
    espec_table_offset: int = 0
    espec_table_size: int = 0
    raw_header: bytes = b""

    @property
    def include_ckey(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def write_support(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def patch_support(self) -> bool:
        return bool(self.flags & 0x04)

    @property
    def lowercase_paths(self) -> bool:
        return bool(self.flags & 0x08)


@dataclass(frozen=True)
class TVFSCFTEntry:
    encoding_key: bytes
    encoded_size: int
    content_size: int
    content_key: bytes | None

    @property
    def full_encoding_key(self) -> bytes:
        if len(self.encoding_key) >= 16:
            return self.encoding_key[:16]
        return self.encoding_key + (b"\0" * (16 - len(self.encoding_key)))


@dataclass(frozen=True)
class TVFSFileSpan:
    offset: int
    size: int
    cft_entry: TVFSCFTEntry

    @property
    def full_encoding_key(self) -> bytes:
        return self.cft_entry.full_encoding_key


@dataclass(frozen=True)
class TVFSFileEntry:
    path: str
    entry_type: str
    spans: tuple[TVFSFileSpan, ...] = ()
    inline_data: bytes | None = None
    target_path: str | None = None


@dataclass(frozen=True)
class _PathTableNode:
    name: str
    flags: int
    value: int | None


class TVFSManifest:
    def __init__(
        self,
        header: TVFSHeader,
        data: bytes,
        entries: dict[str, TVFSFileEntry],
        lookup_entries: dict[str, TVFSFileEntry],
    ) -> None:
        self.header = header
        self.data = data
        self.entries = entries
        self._lookup_entries = lookup_entries

    @classmethod
    def from_bytes(cls, data: bytes) -> "TVFSManifest":
        reader = BinaryReader(io.BytesIO(data))
        header = cls._parse_header(reader, data)

        path_reader = BinaryReader(
            io.BytesIO(data[header.path_table_offset : header.path_table_offset + header.path_table_size])
        )
        vfs_reader = BinaryReader(
            io.BytesIO(data[header.vfs_table_offset : header.vfs_table_offset + header.vfs_table_size])
        )
        cft_reader = BinaryReader(
            io.BytesIO(data[header.cft_table_offset : header.cft_table_offset + header.cft_table_size])
        )

        entries: dict[str, TVFSFileEntry] = {}
        lookup_entries: dict[str, TVFSFileEntry] = {}
        cft_cache: dict[int, TVFSCFTEntry] = {}

        manifest = cls(header, data, entries, lookup_entries)
        manifest._parse_path_table(path_reader, vfs_reader, cft_reader, cft_cache, path_reader.length(), "")
        return manifest

    @classmethod
    def from_stream(cls, stream) -> "TVFSManifest":
        return cls.from_bytes(stream.read())

    @staticmethod
    def _parse_header(reader: BinaryReader, data: bytes) -> TVFSHeader:
        magic = reader.read_bytes(4)
        if magic != TVFS_MAGIC:
            raise ValueError(f"Invalid TVFS magic: {magic!r}")

        version = reader.read_byte()
        header_size = reader.read_byte()
        ekey_size = reader.read_byte()
        patch_key_size = reader.read_byte()
        flags = reader.read_uint32_be()
        path_table_offset = reader.read_uint32_be()
        path_table_size = reader.read_uint32_be()
        vfs_table_offset = reader.read_uint32_be()
        vfs_table_size = reader.read_uint32_be()
        cft_table_offset = reader.read_uint32_be()
        cft_table_size = reader.read_uint32_be()
        max_depth = reader.read_uint16_be()

        espec_table_offset = 0
        espec_table_size = 0
        if header_size >= 46:
            espec_table_offset = reader.read_uint32_be()
            espec_table_size = reader.read_uint32_be()

        if header_size <= 38 or header_size > len(data):
            raise ValueError(f"Invalid TVFS header size: {header_size}")

        return TVFSHeader(
            magic=magic,
            version=version,
            header_size=header_size,
            ekey_size=ekey_size,
            patch_key_size=patch_key_size,
            flags=flags,
            path_table_offset=path_table_offset,
            path_table_size=path_table_size,
            vfs_table_offset=vfs_table_offset,
            vfs_table_size=vfs_table_size,
            cft_table_offset=cft_table_offset,
            cft_table_size=cft_table_size,
            max_depth=max_depth,
            espec_table_offset=espec_table_offset,
            espec_table_size=espec_table_size,
            raw_header=data[:header_size],
        )

    def _parse_path_table(
        self,
        path_reader: BinaryReader,
        vfs_reader: BinaryReader,
        cft_reader: BinaryReader,
        cft_cache: dict[int, TVFSCFTEntry],
        end: int,
        builder: str,
    ) -> None:
        current_size = len(builder)

        while path_reader.tell() < end:
            node = self._parse_path_node(path_reader)

            if node.flags & PATH_SEPARATOR_PRE:
                builder += "\\"
            builder += node.name
            if node.flags & PATH_SEPARATOR_POST:
                builder += "\\"

            if node.flags & IS_NODE_VALUE:
                assert node.value is not None
                if node.value & 0x80000000:
                    folder_size = node.value & 0x7FFFFFFF
                    folder_start = path_reader.tell()
                    folder_end = folder_start + folder_size - 4
                    self._parse_path_table(path_reader, vfs_reader, cft_reader, cft_cache, folder_end, builder)
                else:
                    self._add_entry(builder, node.value, vfs_reader, cft_reader, cft_cache)
                builder = builder[:current_size]

    def _parse_path_node(self, path_reader: BinaryReader) -> _PathTableNode:
        flags = 0
        name = ""
        value = None

        buf = _peek_byte(path_reader)
        if buf == 0:
            flags |= PATH_SEPARATOR_PRE
            path_reader.skip(1)
            buf = _peek_byte(path_reader)

        if buf < 0x7F and buf != 0xFF:
            path_reader.skip(1)
            name = path_reader.read_bytes(buf).decode("utf-8")
            buf = _peek_byte(path_reader)

        if buf == 0:
            flags |= PATH_SEPARATOR_POST
            path_reader.skip(1)
            buf = _peek_byte(path_reader)

        if buf == 0xFF:
            path_reader.skip(1)
            value = path_reader.read_int32_be()
            flags |= IS_NODE_VALUE
        else:
            flags |= PATH_SEPARATOR_POST

        return _PathTableNode(name=name, flags=flags, value=value)

    def _add_entry(
        self,
        path: str,
        vfs_info_pos: int,
        vfs_reader: BinaryReader,
        cft_reader: BinaryReader,
        cft_cache: dict[int, TVFSCFTEntry],
    ) -> None:
        vfs_reader.seek(vfs_info_pos)
        span_count = vfs_reader.read_byte()

        if span_count == 0xFF:
            entry = TVFSFileEntry(path=path, entry_type="deleted")
        elif span_count == 0xFE:
            inline_size = vfs_reader.read_byte()
            entry = TVFSFileEntry(
                path=path,
                entry_type="inline",
                inline_data=vfs_reader.read_bytes(inline_size + 1),
            )
        elif span_count == 0xFD:
            components: list[str] = []
            while True:
                length = int.from_bytes(vfs_reader.read_bytes(1), "big", signed=True)
                if length == -1:
                    break
                if length < 0:
                    raise ValueError(f"Invalid TVFS link component length: {length}")
                components.append(vfs_reader.read_bytes(length).decode("utf-8"))
            entry = TVFSFileEntry(
                path=path,
                entry_type="link",
                target_path="\\".join(components),
            )
        else:
            spans: list[TVFSFileSpan] = []
            for _ in range(span_count):
                offset = vfs_reader.read_uint32_be()
                size = vfs_reader.read_uint32_be()
                cft_offset = _read_variable_size_int(vfs_reader, self.header.cft_table_size)
                cft_entry = self._read_cft_entry(cft_reader, cft_cache, cft_offset)
                spans.append(TVFSFileSpan(offset=offset, size=size, cft_entry=cft_entry))

            entry = TVFSFileEntry(
                path=path,
                entry_type="file",
                spans=tuple(spans),
            )

        self.entries[path] = entry
        for alias in self._aliases_for_path(path):
            self._lookup_entries.setdefault(alias, entry)

    def _read_cft_entry(
        self,
        cft_reader: BinaryReader,
        cft_cache: dict[int, TVFSCFTEntry],
        cft_offset: int,
    ) -> TVFSCFTEntry:
        cached = cft_cache.get(cft_offset)
        if cached is not None:
            return cached

        cft_reader.seek(cft_offset)
        encoding_key = cft_reader.read_bytes(self.header.ekey_size)
        encoded_size = cft_reader.read_uint32_be()

        if self.header.write_support:
            _ = _read_variable_size_int(cft_reader, self.header.espec_table_size)

        content_size = cft_reader.read_uint32_be()
        content_key = cft_reader.read_bytes(16) if self.header.include_ckey else None

        if self.header.patch_support:
            patch_record_count = cft_reader.read_byte()
            patch_record_size = self.header.ekey_size + 4 + self.header.patch_key_size + 4 + 1
            cft_reader.skip(patch_record_count * patch_record_size)

        entry = TVFSCFTEntry(
            encoding_key=encoding_key,
            encoded_size=encoded_size,
            content_size=content_size,
            content_key=content_key,
        )
        cft_cache[cft_offset] = entry
        return entry

    def _aliases_for_path(self, path: str) -> list[str]:
        normalized = path.replace("/", "\\")
        aliases = [normalized]

        if normalized.startswith(".root\\"):
            aliases.append(normalized[6:])

        if self.header.lowercase_paths:
            aliases.extend(alias.lower() for alias in list(aliases))

        deduped: list[str] = []
        seen: set[str] = set()
        for alias in aliases:
            if alias not in seen:
                deduped.append(alias)
                seen.add(alias)
        return deduped

    def get_entry(self, path: str) -> TVFSFileEntry | None:
        normalized = path.replace("/", "\\")
        candidates = [normalized]
        if self.header.lowercase_paths:
            candidates.append(normalized.lower())

        for candidate in candidates:
            entry = self._lookup_entries.get(candidate)
            if entry is not None:
                return entry
        return None
