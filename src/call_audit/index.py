"""Stage 1 — scan a folder of recordings into a tabular index.

Cheap by design: filename parsing plus an audio-header read for the duration,
no decoding. Running this first tells you how much material you actually have
before you commit hours of CPU to transcription.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from .config import Config
from .filenames import FilenameParser
from .privacy import call_id, pseudonymize, salt_from_env

INDEX_COLUMNS = [
    "call_id", "timestamp", "date", "hour", "weekday",
    "operator", "direction", "client_ref", "dest_ref",
    "duration_sec", "size_bytes", "filename", "path",
    "pattern", "name_parsed",
]


def audio_duration_sec(path: Path) -> float | None:
    """Read duration from the audio header. ``None`` if the file is unreadable."""
    try:
        from mutagen import File as MutagenFile
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RuntimeError("mutagen is required for indexing") from exc
    try:
        audio = MutagenFile(path)
        if audio is None or not getattr(audio, "info", None):
            return None
        return float(audio.info.length)
    except Exception:
        return None


def iter_audio_files(root: Path, extensions: tuple[str, ...]) -> list[Path]:
    wanted = {f".{e.lower().lstrip('.')}" for e in extensions}
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and p.suffix.lower() in wanted)


def build_index(cfg: Config, subdir: str | None = None) -> pd.DataFrame:
    """Scan the audio root (or one sub-folder of it) and return the index."""
    if cfg.paths.audio_root is None:
        raise ValueError(
            "paths.audio_root is not set — pass --audio-root, set "
            "CALL_AUDIT_AUDIO_ROOT, or put it in your config file"
        )
    root = cfg.paths.audio_root / subdir if subdir else cfg.paths.audio_root
    if not root.exists():
        raise FileNotFoundError(f"audio root does not exist: {root}")

    files = iter_audio_files(root, cfg.audio_extensions)
    if not files:
        raise SystemExit(f"no audio files ({', '.join(cfg.audio_extensions)}) under {root}")

    parser = FilenameParser(cfg.filename)
    salt = salt_from_env(cfg.privacy.hash_salt_env)
    keep_raw = cfg.privacy.store_raw_identifiers

    rows: list[dict] = []
    skipped = 0
    for path in tqdm(files, desc="indexing", unit="file"):
        parsed = parser.parse(path.name)
        if parsed is None:
            skipped += 1
            continue

        timestamp = parsed.timestamp or datetime.fromtimestamp(path.stat().st_mtime)
        rows.append({
            "call_id": parsed.call_id_hint or call_id(path, cfg.paths.audio_root),
            "timestamp": timestamp,
            "date": timestamp.date(),
            "hour": timestamp.hour,
            "weekday": timestamp.strftime("%A"),
            "operator": parsed.operator,
            "direction": parsed.direction,
            "client_ref": parsed.client if keep_raw else pseudonymize(parsed.client, salt),
            "dest_ref": parsed.dest if keep_raw else pseudonymize(parsed.dest, salt),
            "duration_sec": audio_duration_sec(path),
            "size_bytes": path.stat().st_size,
            "filename": path.name,
            "path": str(path),
            "pattern": parsed.pattern,
            "name_parsed": parsed.matched,
        })

    df = pd.DataFrame(rows, columns=INDEX_COLUMNS)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df.attrs["skipped"] = skipped
    return df


def save_index(cfg: Config, df: pd.DataFrame, name: str) -> Path:
    cfg.paths.ensure()
    out = cfg.paths.index_dir / name
    df.to_parquet(out, index=False)
    return out


def summarize(df: pd.DataFrame) -> str:
    """A short human-readable digest of an index, printed after stage 1."""
    total = len(df)
    unmatched = int((~df["name_parsed"]).sum()) if total else 0
    hours = (df["duration_sec"].fillna(0).sum() / 3600) if total else 0.0
    lines = [
        f"indexed:            {total}",
        f"filename unmatched: {unmatched} (timestamp fell back to file mtime)",
        f"audio total:        {hours:.1f} h",
        "",
        "calls per operator:",
        df["operator"].value_counts().to_string() if total else "  (empty)",
    ]
    return "\n".join(lines)
