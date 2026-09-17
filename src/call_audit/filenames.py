"""Pull call metadata out of recording filenames.

Every PBX exports its own naming scheme, so the schemes live in configuration
as a list of regexes with named groups and this module just applies them in
order. Recognised group names:

``ts``
    timestamp text, parsed with the pattern's ``timestamp_format``
``operator``, ``client``, ``direction``, ``dest``, ``call_id``
    passed through as-is

A file that matches nothing is not necessarily a failure: with
``filename.on_no_match = "mtime"`` it still enters the index with its
modification time and an ``unknown`` operator, which keeps the pipeline usable
on a folder whose naming scheme you have not described yet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import FilenameRules

DIRECTIONS = {"in": "incoming", "incoming": "incoming", "inbound": "incoming",
              "out": "outgoing", "outgoing": "outgoing", "outbound": "outgoing"}


@dataclass(frozen=True)
class ParsedName:
    timestamp: datetime | None = None
    operator: str | None = None
    client: str | None = None
    direction: str | None = None
    dest: str | None = None
    call_id_hint: str | None = None
    pattern: str | None = None
    matched: bool = True


class FilenameParser:
    """Applies the configured patterns to filenames, first match wins."""

    def __init__(self, rules: FilenameRules) -> None:
        self.rules = rules
        self._compiled = [
            (p.name, re.compile(p.regex), p.timestamp_format)
            for p in rules.patterns
        ]

    def parse(self, filename: str) -> ParsedName | None:
        """Parse one filename.

        Returns ``None`` only when nothing matched *and* the configuration says
        such files should be skipped.
        """
        stem = Path(filename).stem
        for name, regex, ts_format in self._compiled:
            match = regex.match(stem)
            if not match:
                continue
            groups = match.groupdict()
            return ParsedName(
                timestamp=_parse_timestamp(groups.get("ts"), ts_format),
                operator=_clean(groups.get("operator")) or self.rules.unknown_operator,
                client=_clean(groups.get("client")),
                direction=_normalize_direction(groups.get("direction")),
                dest=_clean(groups.get("dest")),
                call_id_hint=_clean(groups.get("call_id")),
                pattern=name,
            )
        if self.rules.on_no_match == "skip":
            return None
        return ParsedName(operator=self.rules.unknown_operator,
                          pattern=None, matched=False)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip(" _-")
    return value or None


def _normalize_direction(value: str | None) -> str | None:
    if not value:
        return None
    return DIRECTIONS.get(value.strip().lower(), value.strip().lower())


def _parse_timestamp(value: str | None, ts_format: str) -> datetime | None:
    if not value or not ts_format:
        return None
    try:
        return datetime.strptime(value, ts_format)
    except ValueError:
        return None
