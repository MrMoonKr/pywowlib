from __future__ import annotations

import time
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen

from .cache import get_cache_dir


class ListfileDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ListfileFile:
    name: str
    file_data_id: int


@dataclass
class ListfileNode:
    directories: dict[str, "ListfileNode"] = field(default_factory=dict)
    files: list[ListfileFile] = field(default_factory=list)


class ListfileLoader:
    COMMUNITY_LISTFILE_URL = "https://github.com/wowdev/wow-listfile/releases/latest/download/community-listfile.csv"
    LEGACY_LISTFILE_URL = "https://raw.githubusercontent.com/wowdev/wow-listfile/master/listfile.txt"
    COMMUNITY_CACHE_PATH = get_cache_dir() / "community-listfile.csv"
    LEGACY_CACHE_PATH = get_cache_dir() / "listfile.txt"
    CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
    _entries: list[tuple[int, str]] | None = None

    @classmethod
    def load_names(cls) -> list[str]:
        return [path for _, path in cls.load_entries()]

    @classmethod
    def load_entries(cls) -> list[tuple[int, str]]:
        if cls._entries is not None:
            return cls._entries

        cache_path = cls._ensure_cache()
        entries_by_id: dict[int, str] = {}
        for raw_line in cache_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            file_data_id: int | None = None
            path_text = ""
            if ";" in line:
                candidate_id, candidate_path = line.split(";", 1)
                candidate_id = candidate_id.strip()
                if candidate_id.isdigit():
                    file_data_id = int(candidate_id)
                    path_text = candidate_path.strip()
            elif line.isdigit():
                file_data_id = int(line)

            if file_data_id is None:
                continue

            normalized = path_text.replace("/", "\\")
            normalized = normalized.lstrip("\\")
            if not normalized:
                continue

            existing_path = entries_by_id.get(file_data_id)
            if existing_path is None or normalized.lower() < existing_path.lower():
                entries_by_id[file_data_id] = normalized

        cls._entries = sorted(entries_by_id.items(), key=lambda item: item[1].lower())
        return cls._entries

    @classmethod
    def load_tree(cls, existing_file_data_ids: Collection[int] | None = None) -> ListfileNode:
        if existing_file_data_ids is None:
            allowed_ids = None
        elif isinstance(existing_file_data_ids, set):
            allowed_ids = existing_file_data_ids
        else:
            allowed_ids = set(existing_file_data_ids)
        root = ListfileNode()
        for file_data_id, path in cls.load_entries():
            if allowed_ids is not None and file_data_id not in allowed_ids:
                continue

            parts = [part for part in path.split("\\") if part]
            if not parts:
                continue

            node = root
            for part in parts[:-1]:
                node = node.directories.setdefault(part, ListfileNode())
            node.files.append(ListfileFile(name=parts[-1], file_data_id=file_data_id))

        for node in cls._walk_nodes(root):
            node.files.sort(key=lambda entry: entry.name.lower())

        return root

    @classmethod
    def _walk_nodes(cls, root: ListfileNode):
        stack = [root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.directories.values())

    @classmethod
    def _ensure_cache(cls) -> Path:
        errors: list[Exception] = []
        try:
            cls._refresh_cache_if_needed(cls.COMMUNITY_CACHE_PATH, cls.COMMUNITY_LISTFILE_URL)
            return cls.COMMUNITY_CACHE_PATH
        except Exception as exc:
            errors.append(exc)

        try:
            cls._refresh_cache_if_needed(cls.LEGACY_CACHE_PATH, cls.LEGACY_LISTFILE_URL)
            return cls.LEGACY_CACHE_PATH
        except Exception as exc:
            errors.append(exc)

        raise ListfileDownloadError("Listfile cache is unavailable and automatic download failed.") from errors[-1]

    @classmethod
    def _refresh_cache_if_needed(cls, cache_path: Path, url: str) -> None:
        if cache_path.is_file():
            age = time.time() - cache_path.stat().st_mtime
            if age < cls.CACHE_MAX_AGE_SECONDS:
                return

        req = Request(url, headers={"User-Agent": "pycasc"})
        try:
            with urlopen(req) as response:
                cache_path.write_bytes(response.read())
        except Exception:
            if cache_path.is_file():
                return
            raise

    @classmethod
    def download_custom_listfile(cls, url: str) -> Path:
        target_path = cls.COMMUNITY_CACHE_PATH
        cls._download_to_path(target_path, url)
        cls._entries = None
        return target_path

    @staticmethod
    def _download_to_path(path: Path, url: str) -> None:
        req = Request(url, headers={"User-Agent": "pycasc"})
        with urlopen(req) as response:
            path.write_bytes(response.read())
