"""Stage 3 — speech to text with faster-whisper.

One JSON per call in ``data/transcripts``. The stage is idempotent: a call
whose transcript already exists is skipped, so an interrupted overnight run
resumes instead of restarting. On CPU this is the slowest part of the
pipeline, and losing it to a stray Ctrl+C is the expensive mistake this
design exists to prevent.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm import tqdm

from .config import Config
from .privacy import redact_if


def load_model(cfg: Config) -> Any:
    """Instantiate the ASR backend (imported lazily — it is a heavy import)."""
    if cfg.asr.backend != "faster-whisper":
        raise ValueError(f"unsupported asr.backend: {cfg.asr.backend}")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed — `pip install 'call-audit[asr]'`"
        ) from exc

    print(f"loading whisper '{cfg.asr.model}' "
          f"({cfg.asr.device}/{cfg.asr.compute_type}) ...")
    started = time.time()
    model = WhisperModel(
        cfg.asr.model,
        device=cfg.asr.device,
        compute_type=cfg.asr.compute_type,
        download_root=str(cfg.paths.model_cache),
        cpu_threads=cfg.asr.cpu_threads,
        num_workers=1,
    )
    print(f"  ready in {time.time() - started:.1f}s")
    return model


def transcribe_file(model: Any, cfg: Config, audio_path: Path,
                    meta: dict) -> dict:
    started = time.time()
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=cfg.asr.beam_size,
        vad_filter=cfg.asr.vad_filter,
        vad_parameters=dict(min_silence_duration_ms=500),
        language=cfg.asr.language or None,
        task="transcribe",
        condition_on_previous_text=False,
    )

    redact = cfg.privacy.redact_transcripts
    collected = [
        {"start": round(s.start, 2), "end": round(s.end, 2),
         "text": redact_if(s.text.strip(), redact)}
        for s in segments
    ]
    elapsed = time.time() - started
    return {
        "call_id": meta["call_id"],
        "meta": meta,
        "language": info.language,
        "language_prob": round(info.language_probability, 3),
        "duration_sec": round(info.duration, 2),
        "transcribe_sec": round(elapsed, 2),
        "rtf": round(elapsed / max(info.duration, 0.1), 2),
        "redacted": redact,
        "segments": collected,
        "text": " ".join(s["text"] for s in collected).strip(),
    }


def row_meta(cfg: Config, row: pd.Series) -> dict:
    """Metadata carried into the transcript — identifiers stay out of it."""
    meta = {
        "call_id": row["call_id"],
        "operator": row["operator"],
        "direction": row.get("direction"),
        "timestamp": str(row.get("timestamp")),
        "duration_sec_file": float(row["duration_sec"]) if pd.notna(row.get("duration_sec")) else None,
    }
    if cfg.privacy.store_raw_identifiers:
        meta["filename"] = row.get("filename")
        meta["client_ref"] = row.get("client_ref")
    return meta


def run(cfg: Config, sample_name: str) -> dict[str, int]:
    """Transcribe every call in a sample parquet. Returns simple counters."""
    cfg.paths.ensure()
    df = pd.read_parquet(cfg.paths.index_dir / sample_name)
    print(f"calls in sample: {len(df)}")

    pending = [row for _, row in df.iterrows()
               if not (cfg.paths.transcripts_dir / f"{row['call_id']}.json").exists()]
    print(f"already transcribed: {len(df) - len(pending)}  |  to do: {len(pending)}")
    if not pending:
        return {"done": 0, "skipped": len(df), "failed": 0}

    model = load_model(cfg)
    counters = {"done": 0, "skipped": len(df) - len(pending), "failed": 0}
    audio_total = elapsed_total = 0.0

    for row in tqdm(pending, desc="transcribe", unit="call"):
        out_path = cfg.paths.transcripts_dir / f"{row['call_id']}.json"
        try:
            result = transcribe_file(model, cfg, Path(row["path"]), row_meta(cfg, row))
        except Exception as exc:
            counters["failed"] += 1
            tqdm.write(f"  FAILED {row['call_id']}: {exc}")
            continue

        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        counters["done"] += 1
        audio_total += result["duration_sec"]
        elapsed_total += result["transcribe_sec"]
        tqdm.write(f"  {result['call_id']}: lang={result['language']} "
                   f"({result['language_prob']}) audio={result['duration_sec']:.0f}s "
                   f"rtf={result['rtf']}")

    if audio_total:
        print(f"\naudio {audio_total / 3600:.2f} h in {elapsed_total / 3600:.2f} h "
              f"(overall RTF {elapsed_total / audio_total:.2f})")
    return counters
