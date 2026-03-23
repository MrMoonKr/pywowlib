from __future__ import annotations

import io
from pathlib import Path
from urllib.request import Request, urlopen

from .binary import BinaryReader
from .casc_game import CASCGame
from .types import IndexEntry, MD5Hash, ensure_md5, is_zeroed_md5


class CDNIndexHandler:
    USER_AGENT = "pycasc"

    def __init__(self, config) -> None:
        self.config = config
        self.cdn_index_data: dict[MD5Hash, IndexEntry] = {}

    @property
    def count(self) -> int:
        return len(self.cdn_index_data)

    @classmethod
    def initialize(cls, config, progress=None) -> "CDNIndexHandler":
        handler = cls(config)
        handler.load(progress)
        return handler

    def load(self, progress=None) -> None:
        if self.cdn_index_data:
            return

        archives = self.config.archives
        for index, archive in enumerate(archives):
            self._open_index_file(archive, index)
            if progress is not None and archives:
                progress(int((index + 1) / len(archives) * 100), 'Loading "CDN indexes"...')

    def _open_index_file(self, archive: str, archive_index: int) -> None:
        data_folder = CASCGame.get_data_folder(self.config.game_type)
        if data_folder is None:
            raise RuntimeError(f"Unsupported game type {self.config.game_type}")
        path = Path(self.config.base_path) / data_folder / "indices" / f"{archive}.index"
        with path.open("rb") as handle:
            self._parse_index(handle, archive_index)

    def _parse_index(self, stream, archive_index: int) -> None:
        reader = BinaryReader(stream)
        stream.seek(-12, io.SEEK_END)
        count = reader.read_int32()
        stream.seek(0, io.SEEK_SET)

        if count * 24 > reader.length():
            raise RuntimeError("ParseIndex failed")

        for _ in range(count):
            key = ensure_md5(reader.read_bytes(16))
            if is_zeroed_md5(key):
                key = ensure_md5(reader.read_bytes(16))
            if is_zeroed_md5(key):
                raise RuntimeError("key.IsZeroed()")

            self.cdn_index_data[key] = IndexEntry(
                index=archive_index,
                size=reader.read_int32_be(),
                offset=reader.read_int32_be(),
            )

    def get_index_info(self, key: MD5Hash) -> IndexEntry | None:
        return self.cdn_index_data.get(key)

    def open_data_file(self, entry: IndexEntry) -> io.BytesIO:
        archive = self.config.archives[entry.index]
        file = f"{self.config.cdn_path}/data/{archive[:2]}/{archive[2:4]}/{archive}"
        url = f"https://{self.config.cdn_host}/{file}"
        req = Request(
            url,
            headers={
                "Range": f"bytes={entry.offset}-{entry.offset + entry.size - 1}",
                "User-Agent": self.USER_AGENT,
            },
        )
        with urlopen(req) as response:
            return io.BytesIO(response.read())

    def open_data_file_direct(self, key: MD5Hash) -> io.BytesIO:
        key_str = key.hex().lower()
        file = f"{self.config.cdn_path}/data/{key_str[:2]}/{key_str[2:4]}/{key_str}"
        url = f"https://{self.config.cdn_host}/{file}"
        req = Request(url, headers={"User-Agent": self.USER_AGENT})
        with urlopen(req) as response:
            return io.BytesIO(response.read())
