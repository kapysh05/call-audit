import json

import pandas as pd
import pytest

from call_audit.config import from_tree, load_tree
from call_audit.sample import (
    DEFAULT_LLM_SEC_PER_CALL,
    estimate,
    observed_rates,
    stratified_sample,
)


@pytest.fixture()
def calls() -> pd.DataFrame:
    rows = []
    for operator, count in (("busy", 40), ("quiet", 3)):
        for i in range(count):
            rows.append({
                "operator": operator,
                "duration_sec": 10.0 if i % 10 == 0 else 120.0,
                "timestamp": pd.Timestamp("2026-04-01") + pd.Timedelta(minutes=i),
                "filename": f"{operator}-{i}.mp3",
            })
    return pd.DataFrame(rows)


def test_sampling_caps_every_operator(calls: pd.DataFrame) -> None:
    """The point of the stage: a busy operator must not drown out a quiet one."""
    sample = stratified_sample(calls, per_operator=5, min_duration_sec=30)

    # "quiet" has three calls but one of them is below the duration floor.
    assert sample.groupby("operator").size().to_dict() == {"busy": 5, "quiet": 2}


def test_short_calls_are_dropped(calls: pd.DataFrame) -> None:
    sample = stratified_sample(calls, per_operator=100, min_duration_sec=30)

    assert (sample["duration_sec"] >= 30).all()
    assert len(sample) == 38  # 4 of busy's 40 and 1 of quiet's 3 were short


def test_sampling_is_reproducible(calls: pd.DataFrame) -> None:
    first = stratified_sample(calls, per_operator=5, min_duration_sec=30, seed=42)
    second = stratified_sample(calls, per_operator=5, min_duration_sec=30, seed=42)
    other = stratified_sample(calls, per_operator=5, min_duration_sec=30, seed=7)

    assert list(first["filename"]) == list(second["filename"])
    assert list(first["filename"]) != list(other["filename"])


def test_operator_whitelist(calls: pd.DataFrame) -> None:
    sample = stratified_sample(calls, per_operator=100, min_duration_sec=30,
                               operators=("quiet",))

    assert set(sample["operator"]) == {"quiet"}


def test_missing_durations_do_not_crash_sampling() -> None:
    df = pd.DataFrame([
        {"operator": "a", "duration_sec": None, "timestamp": pd.Timestamp("2026-04-01"),
         "filename": "a.mp3"},
        {"operator": "a", "duration_sec": 90.0, "timestamp": pd.Timestamp("2026-04-01"),
         "filename": "b.mp3"},
    ])

    sample = stratified_sample(df, per_operator=10, min_duration_sec=30)

    assert list(sample["filename"]) == ["b.mp3"]


def test_too_strict_a_floor_returns_empty(calls: pd.DataFrame) -> None:
    assert stratified_sample(calls, per_operator=10, min_duration_sec=10_000).empty


def _cfg(tmp_path):
    return from_tree(load_tree(env={"CALL_AUDIT_DATA_DIR": str(tmp_path)}))


def test_estimate_falls_back_to_defaults_without_history(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.paths.ensure()
    sample = pd.DataFrame([{"duration_sec": 600.0}] * 6)

    result = estimate(cfg, sample)

    assert result.measured is False
    assert result.llm_hours == pytest.approx(6 * DEFAULT_LLM_SEC_PER_CALL / 3600)


def test_estimate_uses_measured_throughput_when_available(tmp_path) -> None:
    """Once the machine has run, the forecast comes from its own numbers."""
    cfg = _cfg(tmp_path)
    cfg.paths.ensure()
    (cfg.paths.transcripts_dir / "a.json").write_text(
        json.dumps({"duration_sec": 100, "transcribe_sec": 200}), encoding="utf-8")
    (cfg.paths.analytics_dir / "a.json").write_text(
        json.dumps({"elapsed_sec": 60}), encoding="utf-8")

    rtf, per_call = observed_rates(cfg)
    result = estimate(cfg, pd.DataFrame([{"duration_sec": 3600.0}]))

    assert (rtf, per_call) == (2.0, 60.0)
    assert result.measured is True
    assert result.asr_hours == pytest.approx(2.0)
    assert result.llm_hours == pytest.approx(60 / 3600)


def test_corrupt_history_is_ignored(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.paths.ensure()
    (cfg.paths.transcripts_dir / "broken.json").write_text("{not json", encoding="utf-8")

    assert observed_rates(cfg) == (None, None)
