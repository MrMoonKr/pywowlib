from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .casc_game import CASCGame
from .types import BuildConfigReference, CASCGameType, ensure_md5


class VerBarConfig:
    def __init__(self) -> None:
        self.data: list[dict[str, str]] = []

    def __getitem__(self, index: int) -> dict[str, str]:
        return self.data[index]

    @classmethod
    def read(cls, path: Path) -> "VerBarConfig":
        result = cls()
        fields: list[str] | None = None

        with path.open("r", encoding="utf-8") as handle:
            line_num = 0
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue

                tokens = raw_line.rstrip("\r\n").split("|")
                if line_num == 0:
                    fields = [token.split("!")[0].replace(" ", "") for token in tokens]
                else:
                    row: dict[str, str] = {}
                    for index, token in enumerate(tokens):
                        row[fields[index]] = token
                    result.data.append(row)
                line_num += 1

        return result


class KeyValueConfig:
    def __init__(self) -> None:
        self.data: dict[str, list[str]] = {}

    def __getitem__(self, key: str) -> list[str]:
        return self.data[key]

    @classmethod
    def read(cls, path: Path) -> "KeyValueConfig":
        result = cls()
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue

                tokens = line.split("=", 1)
                if len(tokens) != 2:
                    raise ValueError("KeyValueConfig: tokens.Length != 2")
                result.data[tokens[0].strip()] = tokens[1].strip().split()
        return result


@dataclass
class CASCConfig:
    region: str | None = None
    game_type: CASCGameType = CASCGameType.Unknown
    validate_data: bool = True
    throw_on_file_not_found: bool = True
    base_path: Path | None = None
    online_mode: bool = False
    active_build: int = 0
    product: str | None = None
    cdn_config: KeyValueConfig | None = None
    builds: list[KeyValueConfig] = field(default_factory=list)
    build_info: VerBarConfig | None = None

    @classmethod
    def load_local_storage_config(cls, base_path: str | Path) -> "CASCConfig":
        normalized = cls._normalize_base_path(Path(base_path))
        config = cls(online_mode=False, base_path=normalized)
        config.game_type = CASCGame.detect_local_game(normalized)

        if config.game_type in (CASCGameType.Unknown, CASCGameType.Agent, CASCGameType.Hearthstone):
            raise ValueError(f"Unsupported or unrecognized local game at '{normalized}'")

        build_info_path = normalized / ".build.info"
        if not build_info_path.is_file():
            raise FileNotFoundError(f"Missing build info file: {build_info_path}")

        config.build_info = VerBarConfig.read(build_info_path)
        active_build = None
        for entry in config.build_info.data:
            if entry.get("Active") == "1":
                active_build = entry
                break
        if active_build is None:
            raise RuntimeError("Can't find active BuildInfoEntry")

        data_folder = CASCGame.get_data_folder(config.game_type)
        build_key = active_build["BuildKey"]
        build_cfg_path = normalized / data_folder / "config" / build_key[:2] / build_key[2:4] / build_key
        config.builds.append(KeyValueConfig.read(build_cfg_path))

        cdn_key = active_build["CDNKey"]
        cdn_cfg_path = normalized / data_folder / "config" / cdn_key[:2] / cdn_key[2:4] / cdn_key
        config.cdn_config = KeyValueConfig.read(cdn_cfg_path)
        return config

    @staticmethod
    def _normalize_base_path(base_path: Path) -> Path:
        base_path = base_path.resolve()
        if (base_path / ".build.info").is_file() and (base_path / "Data").is_dir():
            return base_path
        if base_path.name.lower() in {"_retail_", "_ptr_", "_beta_"}:
            parent = base_path.parent
            if (parent / ".build.info").is_file() and (parent / "Data").is_dir():
                return parent
        return base_path

    @property
    def root_md5(self) -> bytes:
        return ensure_md5(bytes.fromhex(self.builds[self.active_build]["root"][0]))

    @property
    def encoding_key(self) -> bytes:
        return ensure_md5(bytes.fromhex(self.builds[self.active_build]["encoding"][1]))

    @property
    def encoding_md5(self) -> bytes:
        return ensure_md5(bytes.fromhex(self.builds[self.active_build]["encoding"][0]))

    def get_build_reference(self, name: str) -> BuildConfigReference | None:
        values = self.builds[self.active_build].data.get(name)
        if values is None:
            return None

        ckey = ensure_md5(bytes.fromhex(values[0]))
        ekey = ensure_md5(bytes.fromhex(values[1])) if len(values) > 1 else None
        return BuildConfigReference(ckey=ckey, ekey=ekey)

    @property
    def vfs_root(self) -> BuildConfigReference | None:
        return self.get_build_reference("vfs-root")

    @property
    def vfs_files(self) -> dict[str, BuildConfigReference]:
        result: dict[str, BuildConfigReference] = {}
        build = self.builds[self.active_build].data
        for key in sorted(build):
            if key.startswith("vfs-") and key != "vfs-root" and not key.endswith("-size"):
                reference = self.get_build_reference(key)
                if reference is not None:
                    result[key] = reference
        return result

    @property
    def archives(self) -> list[str]:
        if self.cdn_config is None:
            return []
        return self.cdn_config["archives"]

    @property
    def cdn_host(self) -> str:
        if self.build_info is None:
            raise RuntimeError("Build info is not loaded")
        return self.build_info.data[0]["CDNHosts"].split(" ")[0]

    @property
    def cdn_path(self) -> str:
        if self.build_info is None:
            raise RuntimeError("Build info is not loaded")
        return self.build_info.data[0]["CDNPath"]

    @property
    def cdn_url(self) -> str:
        cdn_path = self.cdn_path.lstrip("/")
        return f"https://{self.cdn_host}/{cdn_path}"
