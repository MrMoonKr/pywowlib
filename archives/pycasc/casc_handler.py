from __future__ import annotations

import io
from typing import Any

from .casc_config import CASCConfig
from .casc_handler_base import CASCHandlerBase
from .tvfs_manifest import TVFSManifest
from .types import ContentFlags, LocaleFlags, md5_to_hex
from .wowdbdefs_resolver import WowDBDefsResolver
from .wow_root_handler import WowRootHandler


class CASCHandler(CASCHandlerBase):
    def __init__(self, config: CASCConfig, progress=None) -> None:
        super().__init__(config, progress)
        self.encoding = self.load_encoding_handler()

        if config.game_type.name != "WoW":
            raise NotImplementedError(f"pycasc currently focuses on WoW; got {config.game_type.name}")

        root_stream = self.open_root_file(self.encoding)
        self.root = WowRootHandler(root_stream, progress)
        self.root.set_flags(LocaleFlags.enUS, ContentFlags.None_)
        self.tvfs = self.load_vfs_root_manifest() if config.vfs_root is not None else None

    @classmethod
    def open_local_storage(cls, base_path: str, progress=None) -> "CASCHandler":
        return cls(CASCConfig.load_local_storage_config(base_path), progress)

    def set_flags(self, locale: LocaleFlags, content: ContentFlags = ContentFlags.None_) -> None:
        self.root.set_flags(locale, content)

    def open_build_config_file(self, key_name: str) -> io.BytesIO:
        reference = self.config.get_build_reference(key_name)
        if reference is None:
            raise FileNotFoundError(key_name)
        return self.open_build_reference(reference)

    def open_vfs_root_manifest(self) -> io.BytesIO:
        reference = self.config.vfs_root
        if reference is None:
            raise FileNotFoundError("vfs-root")
        return self.open_build_reference(reference)

    def open_vfs_manifest(self, key_name: str) -> io.BytesIO:
        if key_name != "vfs-root" and not key_name.startswith("vfs-"):
            raise ValueError(key_name)
        return self.open_build_config_file(key_name)

    def load_vfs_root_manifest(self) -> TVFSManifest:
        with self.open_vfs_root_manifest() as stream:
            return TVFSManifest.from_stream(stream)

    def load_vfs_manifest(self, key_name: str) -> TVFSManifest:
        with self.open_vfs_manifest(key_name) as stream:
            return TVFSManifest.from_stream(stream)

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.replace("/", "\\").lstrip("\\")

    def file_exists_by_name(self, name: str) -> bool:
        if self.root.get_entries(self.root.get_file_data_id_by_name(name)):
            return True
        if self.tvfs is not None and self.tvfs.get_entry(name) is not None:
            return True

        for file_data_id in WowDBDefsResolver.resolve_candidate_file_data_ids(name):
            if self.file_exists_by_file_data_id(file_data_id):
                return True
        return False

    def file_exists_by_hash(self, file_hash: int) -> bool:
        return bool(self.root.get_entries(self.root.get_file_data_id_by_hash(file_hash)))

    def file_exists_by_file_data_id(self, file_data_id: int) -> bool:
        return bool(self.root.get_entries(file_data_id))

    def get_file_data_id_storage_info(self, file_data_id: int) -> dict[str, Any]:
        result: dict[str, Any] = {
            "storage": "unresolved",
            "download_required": False,
            "local_index_count": 0,
            "encoding_key": None,
        }

        entries = self.root.get_entries(file_data_id)
        if not entries:
            return result

        enc_info = self.encoding.get_entry(entries[0].md5)
        if enc_info is None:
            return result

        local_indexes = self._inspect_local_indexes(enc_info.key)
        result["encoding_key"] = md5_to_hex(enc_info.key)
        result["local_index_count"] = len(local_indexes)
        if local_indexes:
            result["storage"] = "local"
            return result

        result["storage"] = "cdn"
        result["download_required"] = True
        return result

    def classify_file_data_id_storage(self, file_data_id: int) -> str:
        return str(self.get_file_data_id_storage_info(file_data_id)["storage"])

    def classify_name_source(self, name: str, file_data_id: int | None = None) -> str:
        normalized = self._normalize_name(name)
        if file_data_id is not None and self.root.get_all_entries(file_data_id):
            return "listfile_id"

        root_file_data_id = self.root.get_file_data_id_by_name(normalized)
        if root_file_data_id and self.root.get_all_entries(root_file_data_id):
            return "root"

        if self.tvfs is not None and self.tvfs.get_entry(normalized) is not None:
            return "tvfs"

        for file_data_id in WowDBDefsResolver.resolve_candidate_file_data_ids(normalized):
            if self.root.get_all_entries(file_data_id):
                return "wowdbdefs"

        return "unresolved"

    def inspect_entry(self, name: str, file_data_id: int | None = None) -> dict[str, Any]:
        normalized = self._normalize_name(name)
        name_hash = self.root.hash_name(normalized)
        root_file_data_id = self.root.get_file_data_id_by_name(normalized)
        tvfs_entry = self.tvfs.get_entry(normalized) if self.tvfs is not None else None
        wowdbdefs_candidates = WowDBDefsResolver.resolve_candidate_file_data_ids(normalized)

        selected_source: str | None = None
        selected_file_data_id: int | None = None
        if file_data_id is not None and self.root.get_entries(file_data_id):
            selected_source = "listfile_id"
            selected_file_data_id = file_data_id
        elif root_file_data_id:
            selected_source = "root_name"
            selected_file_data_id = root_file_data_id
        else:
            for candidate in wowdbdefs_candidates:
                if self.root.get_entries(candidate):
                    selected_source = "wowdbdefs"
                    selected_file_data_id = candidate
                    break
            if selected_source is None and tvfs_entry is not None:
                selected_source = "tvfs"

        result: dict[str, Any] = {
            "name": normalized,
            "name_hash": f"{name_hash:016X}",
            "provided_file_data_id": file_data_id,
            "root_file_data_id": root_file_data_id or None,
            "wowdbdefs_candidates": wowdbdefs_candidates,
            "selected_source": selected_source,
            "selected_file_data_id": selected_file_data_id,
            "root_entries": [],
            "encoding": None,
            "local_indexes": [],
            "storage": None,
            "tvfs": None,
        }

        if selected_file_data_id is not None:
            root_entries = self.root.get_entries(selected_file_data_id)
            result["root_entries"] = [
                {
                    "md5": md5_to_hex(entry.md5),
                    "locale_flags": int(entry.locale_flags),
                    "content_flags": int(entry.content_flags),
                }
                for entry in root_entries
            ]

            if root_entries:
                enc_info = self.encoding.get_entry(root_entries[0].md5)
                if enc_info is not None:
                    storage_info = self.get_file_data_id_storage_info(selected_file_data_id)
                    result["encoding"] = {
                        "md5": md5_to_hex(root_entries[0].md5),
                        "key": md5_to_hex(enc_info.key),
                        "size": enc_info.size,
                    }
                    result["local_indexes"] = self._inspect_local_indexes(enc_info.key)
                    result["storage"] = storage_info

        if tvfs_entry is not None:
            tvfs_info: dict[str, Any] = {
                "entry_type": tvfs_entry.entry_type,
                "path": tvfs_entry.path,
            }
            if tvfs_entry.target_path is not None:
                tvfs_info["target_path"] = tvfs_entry.target_path
            if tvfs_entry.inline_data is not None:
                tvfs_info["inline_size"] = len(tvfs_entry.inline_data)
            if tvfs_entry.spans:
                tvfs_info["spans"] = [
                    {
                        "offset": span.offset,
                        "size": span.size,
                        "encoding_key": md5_to_hex(span.cft_entry.full_encoding_key),
                        "local_indexes": self._inspect_local_indexes(span.cft_entry.full_encoding_key),
                    }
                    for span in tvfs_entry.spans
                ]
            result["tvfs"] = tvfs_info

        return result

    def inspect_name(self, name: str) -> dict[str, Any]:
        return self.inspect_entry(name)

    def open_file_reference(self, name: str, file_data_id: int | None = None) -> io.BytesIO:
        errors: list[Exception] = []

        if file_data_id is not None:
            try:
                return self.open_file_by_file_data_id(file_data_id)
            except Exception as exc:
                errors.append(exc)

        normalized = self._normalize_name(name)
        root_file_data_id = self.root.get_file_data_id_by_name(normalized)
        if root_file_data_id:
            try:
                return self.open_file_by_file_data_id(root_file_data_id)
            except Exception as exc:
                errors.append(exc)

        if self.tvfs is not None:
            entry = self.tvfs.get_entry(normalized)
            if entry is not None:
                return self.open_tvfs_entry(entry)

        for candidate_file_data_id in WowDBDefsResolver.resolve_candidate_file_data_ids(normalized):
            try:
                return self.open_file_by_file_data_id(candidate_file_data_id)
            except Exception as exc:
                errors.append(exc)

        if errors and self.config.throw_on_file_not_found:
            raise errors[-1]

        if self.config.throw_on_file_not_found:
            raise FileNotFoundError(normalized)
        return io.BytesIO()

    def open_file_by_name(self, name: str) -> io.BytesIO:
        return self.open_file_reference(name)

    def preview_file_reference(self, name: str, file_data_id: int | None = None, max_bytes: int = 4096) -> tuple[bytes, bool]:
        errors: list[Exception] = []

        if file_data_id is not None:
            try:
                return self.preview_file_by_file_data_id(file_data_id, max_bytes)
            except Exception as exc:
                errors.append(exc)

        normalized = self._normalize_name(name)
        root_file_data_id = self.root.get_file_data_id_by_name(normalized)
        if root_file_data_id:
            try:
                return self.preview_file_by_file_data_id(root_file_data_id, max_bytes)
            except Exception as exc:
                errors.append(exc)

        if self.tvfs is not None:
            entry = self.tvfs.get_entry(normalized)
            if entry is not None:
                data = self.open_tvfs_entry(entry).read(max_bytes + 1)
                return data[:max_bytes], len(data) > max_bytes

        for candidate_file_data_id in WowDBDefsResolver.resolve_candidate_file_data_ids(normalized):
            try:
                return self.preview_file_by_file_data_id(candidate_file_data_id, max_bytes)
            except Exception as exc:
                errors.append(exc)

        if errors and self.config.throw_on_file_not_found:
            raise errors[-1]
        if self.config.throw_on_file_not_found:
            raise FileNotFoundError(normalized)
        return b"", False

    def open_file_by_file_data_id(self, file_data_id: int) -> io.BytesIO:
        entries = self.root.get_entries(file_data_id)
        if not entries:
            if self.config.throw_on_file_not_found:
                raise FileNotFoundError(str(file_data_id))
            return io.BytesIO()

        enc_info = self.encoding.get_entry(entries[0].md5)
        if enc_info is None:
            raise FileNotFoundError(f"encoding info missing for file data id {file_data_id}")
        return self.open_file_by_key(enc_info.key)

    def preview_file_by_file_data_id(self, file_data_id: int, max_bytes: int) -> tuple[bytes, bool]:
        entries = self.root.get_entries(file_data_id)
        if not entries:
            if self.config.throw_on_file_not_found:
                raise FileNotFoundError(str(file_data_id))
            return b"", False

        enc_info = self.encoding.get_entry(entries[0].md5)
        if enc_info is None:
            raise FileNotFoundError(f"encoding info missing for file data id {file_data_id}")

        data = self.preview_file_by_key(enc_info.key, max_bytes + 1)
        return data[:max_bytes], len(data) > max_bytes

    def open_file_by_hash(self, file_hash: int) -> io.BytesIO:
        return self.open_file_by_file_data_id(self.root.get_file_data_id_by_hash(file_hash))

    def open_tvfs_entry(self, entry) -> io.BytesIO:
        if entry.entry_type == "inline":
            return io.BytesIO(entry.inline_data or b"")

        if entry.entry_type == "link":
            if entry.target_path is None:
                raise FileNotFoundError(entry.path)
            linked = self.tvfs.get_entry(entry.target_path) if self.tvfs is not None else None
            if linked is None:
                raise FileNotFoundError(entry.target_path)
            return self.open_tvfs_entry(linked)

        if entry.entry_type != "file":
            raise FileNotFoundError(entry.path)

        chunks: list[bytes] = []
        for span in entry.spans:
            stream = self.open_file_by_partial_key(span.cft_entry.encoding_key)
            data = stream.read()
            chunks.append(data[span.offset : span.offset + span.size])
        return io.BytesIO(b"".join(chunks))

    def _inspect_local_indexes(self, key: bytes) -> list[dict[str, int]]:
        if self.local_index is None:
            return []
        padded_key = (key + (b"\0" * 16))[:16]
        return [
            {
                "index": entry.index,
                "offset": entry.offset,
                "size": entry.size,
            }
            for entry in self.local_index.get_index_infos(padded_key)
        ]
