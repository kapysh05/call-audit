"""Stage 2 — pick a stratified subset of calls to actually process.

Transcription and LLM scoring cost minutes per call, so a full month of a real
contact centre is days of compute. Sampling per operator (rather than at
random across the corpus) keeps the comparison between operators fair: a
busy operator and a quiet one contribute the same number of calls to the
ranking, instead of the loudest voice dominating the averages.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import Config

#: Fallbacks used until this installation has measured itself.
DEFAULT_RTF = 1.0          # ASR seconds per second of audio
DEFAULT_LLM_SEC_PER_CALL = 300.0


@dataclass(frozen=True)
class Estimate:
    calls: int
    audio_minutes: float
    asr_hours: float
    llm_hours: float
    measured: bool

    @property
    def total_hours(self) -> float:
        return self.asr_hours + self.llm_hours

    def render(self) -> str:
        source = "measured on this machine" if self.measured else "rough defaults"
        return "\n".join([
            f"estimated runtime ({source}):",
            f"  calls:        {self.calls}",
            f"  audio:        {self.audio_minutes:.0f} min",
            f"  transcribe:   ~{self.asr_hours:.1f} h",
            f"  analyze:      ~{self.llm_hours:.1f} h",
            f"  total:        ~{self.total_hours:.1f} h",
        ])


def stratified_sample(df: pd.DataFrame, per_operator: int,
                      min_duration_sec: float, seed: int = 42,
                      operators: tuple[str, ...] = ()) -> pd.DataFrame:
    """Up to ``per_operator`` calls for each operator, longer than the floor."""
    out = df.copy()
    if operators:
        out = out[out["operator"].isin(operators)]
    out = out[out["duration_sec"].notna()]
    out = out[out["duration_sec"] >= min_duration_sec]
    if out.empty:
        return out.reset_index(drop=True)

    parts = [
        group.sample(n=min(per_operator, len(group)), random_state=seed)
        for _, group in out.groupby("operator")
    ]
    sample = pd.concat(parts, ignore_index=True)
    return sample.sort_values(["operator", "timestamp"]).reset_index(drop=True)


def observed_rates(cfg: Config) -> tuple[float | None, float | None]:
    """Measure real throughput from whatever this machine has already produced.

    Returns ``(asr_rtf, llm_seconds_per_call)``; either may be ``None`` when
    there is nothing to learn from yet.
    """
    rtf: float | None = None
    per_call: float | None = None

    audio = elapsed = 0.0
    for path in cfg.paths.transcripts_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        audio += float(data.get("duration_sec") or 0)
        elapsed += float(data.get("transcribe_sec") or 0)
    if audio > 0 and elapsed > 0:
        rtf = elapsed / audio

    times = []
    for path in cfg.paths.analytics_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("elapsed_sec"):
            times.append(float(data["elapsed_sec"]))
    if times:
        per_call = sum(times) / len(times)

    return rtf, per_call


def estimate(cfg: Config, sample: pd.DataFrame) -> Estimate:
    rtf, per_call = observed_rates(cfg)
    measured = rtf is not None and per_call is not None
    rtf = rtf or DEFAULT_RTF
    per_call = per_call or DEFAULT_LLM_SEC_PER_CALL

    audio_sec = float(sample["duration_sec"].fillna(0).sum())
    return Estimate(
        calls=len(sample),
        audio_minutes=audio_sec / 60,
        asr_hours=audio_sec * rtf / 3600,
        llm_hours=len(sample) * per_call / 3600,
        measured=measured,
    )


def save_sample(cfg: Config, sample: pd.DataFrame, name: str) -> Path:
    cfg.paths.ensure()
    out = cfg.paths.index_dir / name
    sample.to_parquet(out, index=False)
    return out


def summarize(sample: pd.DataFrame) -> str:
    if sample.empty:
        return "sample is empty — lower sampling.min_duration_sec or check the index"
    by_op = sample.groupby("operator").agg(
        calls=("filename", "count"),
        total_min=("duration_sec", lambda s: round(s.sum() / 60, 1)),
        avg_sec=("duration_sec", lambda s: round(s.mean(), 1)),
    )
    return "calls per operator:\n" + by_op.to_string()
