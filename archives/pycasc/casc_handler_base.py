from __future__ import annotations

import io

from .blte_handler import BLTEHandler
from .cdn_index_handler import CDNIndexHandler
from .encoding_handler import EncodingHandler
from .local_index_handler import LocalIndexHandler
from .types import BuildConfigReference, MD5Hash


class CASCHandlerBase:
    def __init__(self, config, progress=None) -> None:
        self.config = config
        self.progress = progress
        self.cdn_index = CDNIndexHandler(config)
        self.cdn_index_loaded = False
        self.local_index = None if config.online_mode else LocalIndexHandler.initialize(config, progress)
        self.data_streams: dict[int, io.BufferedReader] = {}

    def open_file_by_key(self, key: MD5Hash) -> io.BytesIO:
        if self.config.online_mode:
            raise NotImplementedError("Online storage is not implemented in pycasc")
        try:
            stream = self.get_local_data_stream(key)
            return BLTEHandler(stream, key, validate_data=self.config.validate_data).open_file()
        except Exception:
            return self.open_file_online(key)

    def preview_file_by_key(self, key: MD5Hash, max_bytes: int) -> bytes:
        if self.config.online_mode:
            raise NotImplementedError("Online storage is not implemented in pycasc")

        raw_stream = None
        try:
            raw_stream = self.get_local_data_stream(key)
        except Exception:
            raw_stream = self._open_online_data_stream(key)

        return BLTEHandler(raw_stream, key, validate_data=False, max_output_size=max_bytes).open_file().read()

    def open_file_by_partial_key(self, key: bytes) -> io.BytesIO:
        padded_key = (key + (b"\0" * 16))[:16]
        if self.config.online_mode:
            raise NotImplementedError("Online storage is not implemented in pycasc")
        stream = self.get_local_data_stream(padded_key)
        return BLTEHandler(stream, padded_key, validate_data=False).open_file()

    def open_file_online(self, key: MD5Hash) -> io.BytesIO:
        stream = self._open_online_data_stream(key)
        return BLTEHandler(stream, key, validate_data=self.config.validate_data).open_file()

    def _open_online_data_stream(self, key: MD5Hash) -> io.BytesIO:
        try:
            stream = self.cdn_index.open_data_file_direct(key)
        except Exception:
            self._ensure_cdn_index_loaded()
            cdn_index = self.cdn_index
            entry = cdn_index.get_index_info(key)
            if entry is None:
                raise
            stream = cdn_index.open_data_file(entry)
        return stream

    def get_local_data_stream(self, key: MD5Hash):
        if self.local_index is None:
            raise RuntimeError("Local index is unavailable")
        errors: list[Exception] = []
        for index_info in self.local_index.get_index_infos(key):
            try:
                return self.get_local_data_stream_internal(index_info, key)
            except Exception as exc:
                errors.append(exc)

        if errors:
            raise errors[-1]
        raise FileNotFoundError("local index missing")

    def get_local_data_stream_internal(self, index_info, key: MD5Hash):
        if index_info is None:
            raise FileNotFoundError("local index missing")

        data_stream = self._get_data_stream(index_info.index)
        data_stream.seek(index_info.offset)
        md5 = data_stream.read(16)[::-1]
        truncated_match = md5[:9] == key[:9] and md5[9:] == (b"\0" * 7)
        if md5 != key and not truncated_match:
            raise RuntimeError("local data corrupted")

        size = int.from_bytes(data_stream.read(4), "little", signed=True)
        if size != index_info.size:
            raise RuntimeError("local data corrupted")

        data_stream.seek(10, io.SEEK_CUR)
        data = data_stream.read(index_info.size - 30)
        return io.BytesIO(data)

    def open_encoding_file(self):
        return self.open_file_by_key(self.config.encoding_key)

    def load_encoding_handler(self) -> EncodingHandler:
        return EncodingHandler(self.open_encoding_file(), self.progress)

    def open_root_file(self, encoding: EncodingHandler):
        enc_info = encoding.get_entry(self.config.root_md5)
        if enc_info is None:
            raise FileNotFoundError("encoding info for root file missing!")
        return self.open_file_by_key(enc_info.key)

    def open_build_reference(self, reference: BuildConfigReference):
        if reference.ekey is not None:
            return self.open_file_by_key(reference.ekey)

        encoding = getattr(self, "encoding", None)
        if encoding is None:
            encoding = self.load_encoding_handler()

        enc_info = encoding.get_entry(reference.ckey)
        if enc_info is None:
            raise FileNotFoundError(reference.ckey.hex())
        return self.open_file_by_key(enc_info.key)

    def _get_data_stream(self, index: int):
        stream = self.data_streams.get(index)
        if stream is not None:
            return stream

        data_path = self.config.base_path / "Data" / "data" / f"data.{index:03d}"
        stream = data_path.open("rb")
        self.data_streams[index] = stream
        return stream

    def _ensure_cdn_index_loaded(self) -> None:
        if not self.cdn_index_loaded:
            if self.progress is not None:
                self.progress(0, 'Loading "CDN indexes"...')
            self.cdn_index.initialize(self.config, self.progress)
            self.cdn_index_loaded = True

    def close(self) -> None:
        for stream in self.data_streams.values():
            stream.close()
        self.data_streams.clear()
