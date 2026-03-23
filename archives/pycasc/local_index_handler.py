from __future__ import annotations

from pathlib import Path

from .binary import BinaryReader
from .casc_game import CASCGame
from .types import IndexEntry, MD5Hash


class LocalIndexHandler:
    def __init__(self) -> None:
        self.local_index_data: dict[MD5Hash, list[IndexEntry]] = {}

    @property
    def count(self) -> int:
        return sum(len(entries) for entries in self.local_index_data.values())

    @classmethod
    def initialize(cls, config, progress=None) -> "LocalIndexHandler":
        handler = cls()
        idx_files = handler._get_idx_files(config)
        if not idx_files:
            raise FileNotFoundError("idx files missing!")

        for index, idx_path in enumerate(idx_files):
            handler._parse_index(idx_path)
            if progress is not None:
                progress(int((index + 1) / len(idx_files) * 100), 'Loading "local indexes"...')

        return handler

    def _parse_index(self, path: Path) -> None:
        with path.open("rb") as handle:
            reader = BinaryReader(handle)
            h2_len = reader.read_int32()
            reader.read_int32()
            reader.read_bytes(h2_len)

            pad_pos = (8 + h2_len + 0x0F) & 0xFFFFFFF0
            reader.seek(pad_pos)

            data_len = reader.read_int32()
            reader.read_int32()
            num_blocks = data_len // 18

            for _ in range(num_blocks):
                key_bytes = reader.read_bytes(9) + (b"\0" * 7)
                index_high = reader.read_byte()
                index_low = reader.read_uint32_be()
                index = (index_high << 2) | ((index_low & 0xC0000000) >> 30)
                offset = index_low & 0x3FFFFFFF
                size = reader.read_int32()
                entries = self.local_index_data.setdefault(key_bytes, [])
                candidate = IndexEntry(index=index, offset=offset, size=size)
                if candidate not in entries:
                    entries.append(candidate)

    def _get_idx_files(self, config) -> list[Path]:
        latest_idx: list[Path] = []
        data_folder = CASCGame.get_data_folder(config.game_type)
        if data_folder is None:
            return latest_idx

        data_path = Path(config.base_path) / data_folder / "data"
        for prefix in range(0x10):
            matches = sorted(data_path.glob(f"{prefix:02X}*.idx"))
            if matches:
                latest_idx.append(matches[-1])
        return latest_idx

    def get_index_infos(self, key: MD5Hash) -> list[IndexEntry]:
        masked_key = key[:9] + (b"\0" * 7)
        return list(self.local_index_data.get(masked_key, []))

    def get_index_info(self, key: MD5Hash) -> IndexEntry | None:
        entries = self.get_index_infos(key)
        return entries[0] if entries else None
