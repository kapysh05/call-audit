"""Indexing a folder of recordings, including the privacy defaults."""
from datetime import datetime

import pytest

from call_audit.config import from_tree, load_tree
from call_audit.index import build_index, iter_audio_files, save_index, summarize

NAMES = [
    "17-04-2026_10-32_77011234567_outgoing__user_Aida.mp3",
    "17-04-2026_11-05_77019876543_incoming_7172000000_user_Bolat.mp3",
    "some other recording.mp3",
    "notes.txt",
]


@pytest.fixture()
def cfg(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    for name in NAMES:
        (audio / name).write_bytes(b"")
    return from_tree(load_tree(env={
        "CALL_AUDIT_AUDIO_ROOT": str(audio),
        "CALL_AUDIT_DATA_DIR": str(tmp_path / "data"),
    }))


def test_only_audio_extensions_are_picked_up(cfg) -> None:
    found = iter_audio_files(cfg.paths.audio_root, cfg.audio_extensions)

    assert {p.name for p in found} == set(NAMES[:3])


def test_index_parses_what_it_can_and_keeps_the_rest(cfg) -> None:
    df = build_index(cfg)

    assert len(df) == 3
    assert set(df["operator"]) == {"Aida", "Bolat", "unknown"}
    parsed = df[df["name_parsed"]]
    assert set(parsed["direction"]) == {"outgoing", "incoming"}
    assert parsed["timestamp"].min() == datetime(2026, 4, 17, 10, 32)


def test_customer_numbers_are_hashed_by_default(cfg) -> None:
    """The default index must not be a usable phone list."""
    df = build_index(cfg)

    refs = set(df["client_ref"].dropna())
    assert refs
    assert not any("77011234567" in str(ref) for ref in refs)
    assert all(len(str(ref)) == 12 for ref in refs)


def test_raw_identifiers_can_be_opted_into(tmp_path) -> None:
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / NAMES[0]).write_bytes(b"")
    tree = load_tree(env={"CALL_AUDIT_AUDIO_ROOT": str(audio),
                          "CALL_AUDIT_DATA_DIR": str(tmp_path / "data")})
    tree["privacy"]["store_raw_identifiers"] = True

    df = build_index(from_tree(tree))

    assert df.loc[0, "client_ref"] == "77011234567"


def test_unreadable_audio_gets_no_duration_instead_of_crashing(cfg) -> None:
    df = build_index(cfg)

    assert df["duration_sec"].isna().all()


def test_index_round_trips_through_parquet(cfg) -> None:
    import pandas as pd

    path = save_index(cfg, build_index(cfg), "calls.parquet")

    assert path.exists()
    assert len(pd.read_parquet(path)) == 3


def test_summary_mentions_unparsed_names(cfg) -> None:
    text = summarize(build_index(cfg))

    assert "filename unmatched: 1" in text
    assert "Aida" in text


def test_missing_audio_root_is_a_clear_error(tmp_path) -> None:
    cfg = from_tree(load_tree(env={"CALL_AUDIT_DATA_DIR": str(tmp_path)}))

    with pytest.raises(ValueError, match="paths.audio_root"):
        build_index(cfg)
