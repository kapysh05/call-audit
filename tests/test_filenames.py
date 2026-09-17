from datetime import datetime

import pytest

from call_audit.config import FilenamePattern, FilenameRules, load
from call_audit.filenames import FilenameParser


@pytest.fixture()
def parser() -> FilenameParser:
    return FilenameParser(load().filename)


def test_parses_outgoing_pbx_name(parser: FilenameParser) -> None:
    parsed = parser.parse("17-04-2026_10-32_77011234567_outgoing__user_Aida K.mp3")

    assert parsed is not None
    assert parsed.timestamp == datetime(2026, 4, 17, 10, 32)
    assert parsed.operator == "Aida K"
    assert parsed.client == "77011234567"
    assert parsed.direction == "outgoing"
    assert parsed.matched


def test_parses_incoming_with_destination(parser: FilenameParser) -> None:
    parsed = parser.parse("17-04-2026_10-32_77011234567_incoming_7172000000_user_Aida.mp3")

    assert parsed is not None
    assert parsed.direction == "incoming"
    assert parsed.dest == "7172000000"
    assert parsed.operator == "Aida"


def test_parses_iso_scheme(parser: FilenameParser) -> None:
    parsed = parser.parse("2026-04-17_10-32-05_dana_+15551234567.wav")

    assert parsed is not None
    assert parsed.timestamp == datetime(2026, 4, 17, 10, 32, 5)
    assert parsed.operator == "dana"
    assert parsed.client == "+15551234567"


def test_empty_operator_falls_back_to_unknown(parser: FilenameParser) -> None:
    parsed = parser.parse("17-04-2026_10-32_77011234567_outgoing__user_.mp3")

    assert parsed is not None
    assert parsed.operator == "unknown"


def test_unmatched_name_is_kept_by_default(parser: FilenameParser) -> None:
    """An unknown scheme still enters the index, flagged as unparsed."""
    parsed = parser.parse("recording 42.mp3")

    assert parsed is not None
    assert parsed.matched is False
    assert parsed.timestamp is None
    assert parsed.operator == "unknown"


def test_unmatched_name_is_dropped_when_configured() -> None:
    rules = FilenameRules(patterns=(), on_no_match="skip")

    assert FilenameParser(rules).parse("recording 42.mp3") is None


def test_direction_synonyms_are_normalized() -> None:
    rules = FilenameRules(patterns=(FilenamePattern(
        name="t", regex=r"^(?P<direction>\w+)-(?P<operator>\w+)$"),))

    assert FilenameParser(rules).parse("inbound-dana.mp3").direction == "incoming"
    assert FilenameParser(rules).parse("OUT-dana.mp3").direction == "outgoing"


def test_bad_timestamp_does_not_kill_the_row() -> None:
    rules = FilenameRules(patterns=(FilenamePattern(
        name="t", regex=r"^(?P<ts>\d+)_(?P<operator>\w+)$",
        timestamp_format="%Y-%m-%d"),))

    parsed = FilenameParser(rules).parse("99999_dana.mp3")

    assert parsed is not None
    assert parsed.timestamp is None
    assert parsed.operator == "dana"
