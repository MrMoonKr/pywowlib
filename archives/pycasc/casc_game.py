from __future__ import annotations

from pathlib import Path

from .types import CASCGameType


class CASCGame:
    @staticmethod
    def detect_local_game(path: str | Path) -> CASCGameType:
        base_path = Path(path)

        if (base_path / "HeroesData").is_dir():
            return CASCGameType.HotS
        if (base_path / "SC2Data").is_dir():
            return CASCGameType.S2
        if (base_path / "Hearthstone_Data").is_dir():
            return CASCGameType.Hearthstone

        if (base_path / "Data").is_dir():
            if (base_path / "Diablo III.exe").is_file():
                return CASCGameType.D3
            if (base_path / "Wow.exe").is_file():
                return CASCGameType.WoW
            if (base_path / "WowT.exe").is_file():
                return CASCGameType.WoW
            if (base_path / "WowB.exe").is_file():
                return CASCGameType.WoW
            if (base_path / "_retail_" / "Wow.exe").is_file():
                return CASCGameType.WoW
            if (base_path / "_ptr_" / "Wow.exe").is_file():
                return CASCGameType.WoW
            if (base_path / "_beta_" / "Wow.exe").is_file():
                return CASCGameType.WoW
            if (base_path / "Agent.exe").is_file():
                return CASCGameType.Agent
            if (base_path / "Battle.net.exe").is_file():
                return CASCGameType.Bna
            if (base_path / "Overwatch Launcher.exe").is_file():
                return CASCGameType.Overwatch

        return CASCGameType.Unknown

    @staticmethod
    def get_data_folder(game_type: CASCGameType) -> str | None:
        if game_type == CASCGameType.HotS:
            return "HeroesData"
        if game_type == CASCGameType.S2:
            return "SC2Data"
        if game_type == CASCGameType.Hearthstone:
            return "Hearthstone_Data"
        if game_type in (CASCGameType.WoW, CASCGameType.D3):
            return "Data"
        if game_type == CASCGameType.Overwatch:
            return "data/casc"
        return None
