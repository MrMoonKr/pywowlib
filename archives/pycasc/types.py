from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag


class CASCGameType(IntEnum):
    Unknown = 0
    HotS = 1
    WoW = 2
    D3 = 3
    S2 = 4
    Agent = 5
    Hearthstone = 6
    Overwatch = 7
    Bna = 8
    Client = 9


class LocaleFlags(IntFlag):
    All = 0xFFFFFFFF
    None_ = 0
    enUS = 0x2
    koKR = 0x4
    frFR = 0x10
    deDE = 0x20
    zhCN = 0x40
    esES = 0x80
    zhTW = 0x100
    enGB = 0x200
    enCN = 0x400
    enTW = 0x800
    esMX = 0x1000
    ruRU = 0x2000
    ptBR = 0x4000
    itIT = 0x8000
    ptPT = 0x10000
    enSG = 0x20000000
    plPL = 0x40000000
    All_WoW = (
        enUS
        | koKR
        | frFR
        | deDE
        | zhCN
        | esES
        | zhTW
        | enGB
        | esMX
        | ruRU
        | ptBR
        | itIT
        | ptPT
    )


class ContentFlags(IntFlag):
    None_ = 0
    LowViolence = 0x80
    NoCompression = 0x80000000


MD5Hash = bytes


@dataclass(frozen=True)
class IndexEntry:
    index: int
    offset: int
    size: int


@dataclass(frozen=True)
class EncodingEntry:
    key: MD5Hash
    size: int


@dataclass(frozen=True)
class BuildConfigReference:
    ckey: MD5Hash
    ekey: MD5Hash | None


@dataclass(frozen=True)
class RootEntry:
    md5: MD5Hash
    content_flags: ContentFlags
    locale_flags: LocaleFlags


def ensure_md5(value: bytes) -> MD5Hash:
    if len(value) != 16:
        raise ValueError(f"Expected 16-byte MD5 hash, got {len(value)} bytes")
    return bytes(value)


def md5_to_hex(value: MD5Hash) -> str:
    return value.hex().upper()


def is_zeroed_md5(value: MD5Hash) -> bool:
    return all(byte == 0 for byte in value)
