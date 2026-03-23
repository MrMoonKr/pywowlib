from __future__ import annotations

import time
from pathlib import Path
from urllib.request import Request, urlopen

from .cache import get_cache_dir
from .salsa20 import Salsa20


class KeyService:
    KEYS_URL = "https://raw.githubusercontent.com/wowdev/TACTKeys/master/WoW.txt"
    CACHE_PATH = get_cache_dir() / "TACTKeys_WoW.txt"
    CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
    KEYS: dict[int, bytes] = {
        0x402CD9D8D6BFED98: bytes.fromhex("AEB0EADEA47612FE6C041A03958DF241"),
        0xFB680CB6A8BF81F3: bytes.fromhex("62D90EFA7F36D71C398AE2F1FE37BDB9"),
        0xDBD3371554F60306: bytes.fromhex("34E397ACE6DD30EEFDC98A2AB093CD3C"),
        0x11A9203C9881710A: bytes.fromhex("2E2CB8C397C2F24ED0B5E452F18DC267"),
        0xA19C4F859F6EFA54: bytes.fromhex("0196CB6F5ECBAD7CB5283891B9712B4B"),
        0x87AEBBC9C4E6B601: bytes.fromhex("685E86C6063DFDA6C9E85298076B3D42"),
        0xDEE3A0521EFF6F03: bytes.fromhex("AD740CE3FFFF9231468126985708E1B9"),
        0x8C9106108AA84F07: bytes.fromhex("53D859DDA2635A38DC32E72B11B32F29"),
        0x49166D358A34D815: bytes.fromhex("667868CD94EA0135B9B16C93B1124ABA"),
        0xB76729641141CB34: bytes.fromhex("9849D1AA7B1FD09819C5C66283A326EC"),
        0x23C5B5DF837A226C: bytes.fromhex("1406E2D873B6FC99217A180881DA8D62"),
        0xD1E9B5EDF9283668: bytes.fromhex("8E4A2579894E38B4AB9058BA5C7328EE"),
    }
    SALSA_INSTANCE = Salsa20()
    _external_keys_loaded = False

    @classmethod
    def get_key(cls, key_name: int) -> bytes | None:
        key = cls.KEYS.get(key_name)
        if key is not None:
            return key

        cls._load_external_keys()
        return cls.KEYS.get(key_name)

    @classmethod
    def _load_external_keys(cls) -> None:
        if cls._external_keys_loaded:
            return
        cls._external_keys_loaded = True

        try:
            cls._refresh_cache_if_needed()
            for raw_line in cls.CACHE_PATH.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue

                tokens = line.split()
                if len(tokens) != 2:
                    continue

                try:
                    cls.KEYS[int(tokens[0], 16)] = bytes.fromhex(tokens[1])
                except ValueError:
                    continue
        except Exception:
            return

    @classmethod
    def _refresh_cache_if_needed(cls) -> None:
        if cls.CACHE_PATH.is_file():
            age = time.time() - cls.CACHE_PATH.stat().st_mtime
            if age < cls.CACHE_MAX_AGE_SECONDS:
                return

        req = Request(cls.KEYS_URL, headers={"User-Agent": "pycasc"})
        with urlopen(req) as response:
            cls.CACHE_PATH.write_bytes(response.read())
