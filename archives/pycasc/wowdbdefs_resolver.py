from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .cache import get_cache_dir


class WowDBDefsResolver:
    MANIFEST_URL = "https://raw.githubusercontent.com/wowdev/WoWDBDefs/master/manifest.json"
    CACHE_PATH = get_cache_dir() / "wowdbdefs_manifest.json"
    CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
    LISTFILE_PATH = Path(__file__).resolve().parent.parent / "listfile.csv"
    _manifest: dict[str, dict[str, object]] | None = None
    _listfile: dict[str, list[int]] | None = None

    @classmethod
    def resolve_file_data_id(cls, name: str) -> int | None:
        candidates = cls.resolve_candidate_file_data_ids(name)
        return candidates[0] if candidates else None

    @classmethod
    def resolve_candidate_file_data_ids(cls, name: str) -> list[int]:
        normalized = name.replace("/", "\\").lower()
        result = cls._resolve_from_listfile(normalized)
        if result:
            return result

        if not normalized.startswith("dbfilesclient\\"):
            return []

        leaf = normalized.rsplit("\\", 1)[-1]
        if "." not in leaf:
            return []

        stem, ext = leaf.rsplit(".", 1)
        if ext.lower() == "db2":
            fields = ("db2FileDataID", "dbcFileDataID")
        elif ext.lower() == "dbc":
            fields = ("dbcFileDataID", "db2FileDataID")
        else:
            return []

        manifest = cls._load_manifest()
        row = manifest.get(stem.lower())
        if row is None:
            return []

        result: list[int] = []
        for field in fields:
            value = row.get(field)
            if value is None:
                continue
            file_data_id = int(value)
            if file_data_id not in result:
                result.append(file_data_id)
        return result

    @classmethod
    def _resolve_from_listfile(cls, normalized: str) -> list[int]:
        if cls._listfile is None:
            cls._load_listfile()

        result: list[int] = []
        for candidate in cls._iter_listfile_candidates(normalized):
            for file_data_id in cls._listfile.get(candidate, []):
                if file_data_id not in result:
                    result.append(file_data_id)

        return result

    @staticmethod
    def _iter_listfile_candidates(normalized: str):
        yield normalized

        leaf = normalized.rsplit("\\", 1)[-1]
        if "." not in leaf:
            return

        stem, ext = leaf.rsplit(".", 1)
        if ext == "dbc":
            yield normalized[: -len(leaf)] + f"{stem}.db2"
        elif ext == "db2":
            yield normalized[: -len(leaf)] + f"{stem}.dbc"

    @classmethod
    def _load_listfile(cls) -> None:
        cls._listfile = {}
        if not cls.LISTFILE_PATH.is_file():
            return

        with cls.LISTFILE_PATH.open(encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle, delimiter=";"):
                if len(row) != 2:
                    continue

                try:
                    file_data_id = int(row[0])
                except ValueError:
                    continue

                normalized = row[1].replace("/", "\\").lower()
                cls._listfile.setdefault(normalized, []).append(file_data_id)

    @classmethod
    def _load_manifest(cls) -> dict[str, dict[str, object]]:
        if cls._manifest is not None:
            return cls._manifest

        cls._refresh_cache_if_needed()
        rows = json.loads(cls.CACHE_PATH.read_text(encoding="utf-8"))
        cls._manifest = {
            str(row["tableName"]).lower(): row
            for row in rows
            if isinstance(row, dict) and "tableName" in row
        }
        return cls._manifest

    @classmethod
    def _refresh_cache_if_needed(cls) -> None:
        if cls.CACHE_PATH.is_file():
            age = time.time() - cls.CACHE_PATH.stat().st_mtime
            if age < cls.CACHE_MAX_AGE_SECONDS:
                return

        req = Request(cls.MANIFEST_URL, headers={"User-Agent": "pycasc"})
        with urlopen(req) as response:
            cls.CACHE_PATH.write_bytes(response.read())
