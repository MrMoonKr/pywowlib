from __future__ import annotations

from .jenkins96 import Jenkins96
from .types import ContentFlags, LocaleFlags


class RootHandlerBase:
    def __init__(self) -> None:
        self.hasher = Jenkins96()
        self.locale = LocaleFlags.enUS
        self.content = ContentFlags.None_

    def set_flags(self, locale: LocaleFlags, content: ContentFlags) -> None:
        self.locale = locale
        self.content = content
