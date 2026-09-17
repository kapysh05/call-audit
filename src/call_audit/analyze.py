"""Stage 4 — score each transcript with an LLM.

One JSON per call in ``data/analytics``, idempotent like transcription. Small
local models drift from the requested schema now and then, so every answer goes
through :func:`normalize_analysis`: scores are coerced to numbers and clamped to
the configured scale, list fields are forced to be lists, and enum fields are
checked. Whatever could not be repaired is recorded in ``issues`` on the result
instead of being silently dropped — a call that scored oddly should be
explainable afterwards.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tqdm import tqdm

from .config import Config
from .llm import build_client, extract_json
from .prompt import PROMPT_VERSION, build_messages
from .privacy import redact_if

LIST_FIELDS = (
    "operator_strengths", "operator_weaknesses", "uncertainty_signs",
    "missed_opportunities", "product_issues", "knowledge_gaps",
    "script_gaps", "training_recommendations",
)
RESOLVED_VALUES = {"yes", "no", "partial"}
EMOTIONS = {"satisfied", "neutral", "frustrated", "angry"}


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


def _as_score(value, lo: int, hi: int) -> float | None:
    """Coerce a model score to a number inside the scale, or ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        cleaned = value.strip().split("/")[0].replace(",", ".")
        try:
            number = float(cleaned)
        except ValueError:
            return None
    else:
        return None
    return float(min(max(number, lo), hi))


def normalize_analysis(cfg: Config, parsed: dict) -> tuple[dict, list[str]]:
    """Repair a model answer into the shape the report expects."""
    issues: list[str] = []
    lo, hi = cfg.rubric.scale_min, cfg.rubric.scale_max
    raw_scores = parsed.get("scores") or {}
    if not isinstance(raw_scores, dict):
        raw_scores, issues = {}, issues + ["scores was not an object"]

    scores: dict[str, float | None] = {}
    for key in cfg.rubric.keys:
        score = _as_score(raw_scores.get(key), lo, hi)
        if score is None:
            issues.append(f"missing or unusable score: {key}")
        scores[key] = score

    present = [s for s in scores.values() if s is not None]
    overall = _as_score(parsed.get("overall_score"), lo, hi)
    if overall is None and present:
        overall = round(sum(present) / len(present), 2)
        issues.append("overall_score derived from criteria")

    resolved = str(parsed.get("resolved", "")).strip().lower()
    if resolved not in RESOLVED_VALUES:
        issues.append(f"unexpected resolved value: {parsed.get('resolved')!r}")
        resolved = "partial" if resolved else ""

    analysis = {
        "theme": str(parsed.get("theme") or "").strip() or "Other",
        "theme_detail": str(parsed.get("theme_detail") or "").strip(),
        "language": str(parsed.get("language") or "").strip(),
        "resolved": resolved,
        "resolution_summary": str(parsed.get("resolution_summary") or "").strip(),
        "scores": scores,
        "overall_score": overall,
    }
    for field in ("customer_emotion_start", "customer_emotion_end"):
        value = str(parsed.get(field) or "").strip().lower()
        if value and value not in EMOTIONS:
            issues.append(f"unexpected {field}: {value!r}")
            value = ""
        analysis[field] = value
    for field in LIST_FIELDS:
        analysis[field] = _as_list(parsed.get(field))
    return analysis, issues


def analyze_transcript(cfg: Config, client, transcript: dict) -> dict:
    meta = dict(transcript.get("meta") or {})
    meta.setdefault("call_id", transcript.get("call_id"))
    meta["language"] = transcript.get("language")
    meta["language_prob"] = transcript.get("language_prob")

    text = redact_if(transcript.get("text", ""), cfg.privacy.redact_transcripts
                     and not transcript.get("redacted"))
    result = client.chat(build_messages(cfg, meta, text))
    parsed = extract_json(result.text)
    analysis, issues = normalize_analysis(cfg, parsed) if parsed else (None, ["response was not JSON"])

    return {
        "call_id": meta.get("call_id"),
        "operator": meta.get("operator"),
        "direction": meta.get("direction"),
        "duration_sec": meta.get("duration_sec_file"),
        "model": cfg.llm.model,
        "prompt_version": PROMPT_VERSION,
        "elapsed_sec": result.elapsed_sec,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "tokens_per_sec": result.tokens_per_sec,
        "issues": issues,
        "analysis": analysis,
        "raw_if_parse_failed": None if analysis else result.text,
    }


def run(cfg: Config, only: str | None = None, limit: int | None = None,
        retry_failed: bool = False) -> dict[str, int]:
    """Analyze every transcript that has no analysis yet."""
    cfg.paths.ensure()
    transcripts = sorted(cfg.paths.transcripts_dir.glob("*.json"))
    if only:
        transcripts = [p for p in transcripts if p.stem == only]

    pending: list[Path] = []
    for path in transcripts:
        out_path = cfg.paths.analytics_dir / path.name
        if not out_path.exists():
            pending.append(path)
        elif retry_failed and _is_failed(out_path):
            pending.append(path)
    if limit:
        pending = pending[:limit]

    print(f"transcripts: {len(transcripts)}  |  to analyze: {len(pending)}  "
          f"|  model: {cfg.llm.model} via {cfg.llm.backend}")
    if not pending:
        return {"done": 0, "skipped": len(transcripts), "failed": 0}

    api_key = os.environ.get(cfg.llm.api_key_env, "")
    client = build_client(cfg, api_key=api_key)
    counters = {"done": 0, "skipped": len(transcripts) - len(pending), "failed": 0}

    for path in tqdm(pending, desc="analyze", unit="call"):
        try:
            transcript = json.loads(path.read_text(encoding="utf-8"))
            result = analyze_transcript(cfg, client, transcript)
        except Exception as exc:
            counters["failed"] += 1
            tqdm.write(f"  FAILED {path.stem}: {exc}")
            continue

        (cfg.paths.analytics_dir / path.name).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if result["analysis"]:
            counters["done"] += 1
            status = "ok" if not result["issues"] else f"ok ({len(result['issues'])} repaired)"
        else:
            counters["failed"] += 1
            status = "unparseable"
        tqdm.write(f"  {path.stem}: {status}  in={result['tokens_in']} "
                   f"out={result['tokens_out']} t={result['elapsed_sec']}s "
                   f"({result['tokens_per_sec']} tok/s)")
    return counters


def _is_failed(path: Path) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("analysis") is None
    except (OSError, json.JSONDecodeError):
        return True
