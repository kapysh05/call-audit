"""Stage 5 — aggregate the per-call analyses into one Excel workbook.

Sheet layout:

``summary``          plain-language digest, including the caveats
``operators``        the ranking: level, scores per criterion, coaching notes
``themes``           what customers call about and how often it gets resolved
``product_issues``   defects customers reported, by frequency
``knowledge_gaps``   questions operators could not answer
``uncertainty``      moments operators sounded unsure
``script_gaps``      situations the script does not cover
``calls``            one row per call, for audit
``run_info``         model, prompt version, sample size — how this was produced

Every score column is generated from the rubric in the configuration, so the
workbook follows whatever criteria you defined.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import Config
from .privacy import redact_if
from .prompt import PROMPT_VERSION
from .xlsx_style import style_sheet

TEXT_COLUMNS = {
    "strengths": "operator_strengths",
    "weaknesses": "operator_weaknesses",
    "uncertainty": "uncertainty_signs",
    "missed_opportunities": "missed_opportunities",
    "product_issues": "product_issues",
    "knowledge_gaps": "knowledge_gaps",
    "script_gaps": "script_gaps",
    "training_recommendations": "training_recommendations",
}
SEPARATOR = " | "


def load_analytics(cfg: Config) -> pd.DataFrame:
    """Flatten ``data/analytics/*.json`` into one row per call."""
    rows: list[dict] = []
    redact = cfg.privacy.redact_in_reports
    for path in sorted(cfg.paths.analytics_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        analysis = record.get("analysis")
        if not analysis:
            continue
        scores = analysis.get("scores") or {}
        row = {
            "call_id": record.get("call_id"),
            "operator": record.get("operator"),
            "direction": record.get("direction"),
            "duration_sec": record.get("duration_sec"),
            "model": record.get("model"),
            "theme": analysis.get("theme"),
            "theme_detail": redact_if(analysis.get("theme_detail", ""), redact),
            "language": analysis.get("language"),
            "resolved": analysis.get("resolved"),
            "resolution_summary": redact_if(analysis.get("resolution_summary", ""), redact),
            "overall_score": analysis.get("overall_score"),
            "customer_emotion_start": analysis.get("customer_emotion_start"),
            "customer_emotion_end": analysis.get("customer_emotion_end"),
            "issues": SEPARATOR.join(record.get("issues") or []),
        }
        for key in cfg.rubric.keys:
            row[key] = scores.get(key)
        for column, field in TEXT_COLUMNS.items():
            row[column] = redact_if(SEPARATOR.join(analysis.get(field) or []), redact)
        rows.append(row)
    return pd.DataFrame(rows)


def _collect(df: pd.DataFrame, column: str) -> Counter:
    """Split a ``|``-joined column back into individual findings and count them."""
    items: list[str] = []
    for cell in df[column].fillna(""):
        items.extend(part.strip() for part in str(cell).split("|") if part.strip())
    return Counter(items)


def operator_table(cfg: Config, df: pd.DataFrame) -> pd.DataFrame:
    """The ranking sheet: one row per operator."""
    score_columns = list(cfg.rubric.keys) + ["overall_score"]
    grouped = df.groupby("operator")

    table = grouped[score_columns].mean().round(2)
    table["calls"] = grouped.size()
    for outcome in ("yes", "partial", "no"):
        table[f"resolved_{outcome}"] = grouped["resolved"].apply(
            lambda s, o=outcome: int((s == o).sum()))
    table["resolve_rate_%"] = (table["resolved_yes"] / table["calls"] * 100).round(0)

    # Emotion shift: did the customer end the call better or worse than they
    # started it? Counted with masks rather than per-group apply so the numbers
    # stay well defined when a column is entirely empty.
    calmed = ((df["customer_emotion_end"] == "satisfied") &
              (df["customer_emotion_start"].isin(["frustrated", "angry", "neutral"])))
    upset = ((df["customer_emotion_end"].isin(["frustrated", "angry"])) &
             (df["customer_emotion_start"] != df["customer_emotion_end"]))
    table["calmed_down"] = _count_by_operator(df, calmed, table.index)
    table["left_unhappy"] = _count_by_operator(df, upset, table.index)
    table["level"] = table["overall_score"].apply(cfg.rubric.level_for)

    qualitative = pd.DataFrame([
        {
            "operator": operator,
            "top_strengths": _top_lines(group, "strengths"),
            "top_weaknesses": _top_lines(group, "weaknesses"),
            "coaching": _top_lines(group, "training_recommendations"),
        }
        for operator, group in df.groupby("operator")
    ])

    table = table.sort_values("overall_score", ascending=False).reset_index()
    table.insert(0, "rank", range(1, len(table) + 1))
    merged = table.merge(qualitative, on="operator", how="left")

    ordered = (["rank", "operator", "level", "overall_score", "calls",
                "resolved_yes", "resolved_partial", "resolved_no", "resolve_rate_%",
                "calmed_down", "left_unhappy"]
               + list(cfg.rubric.keys)
               + ["top_strengths", "top_weaknesses", "coaching"])
    return merged[ordered]


def _count_by_operator(df: pd.DataFrame, mask: pd.Series,
                       operators: pd.Index) -> pd.Series:
    counts = df.loc[mask].groupby("operator").size()
    return counts.reindex(operators).fillna(0).astype(int)


def _top_lines(group: pd.DataFrame, column: str, top: int = 8) -> str:
    counted = _collect(group, column)
    return "\n".join(f"• {text} (x{count})" for text, count in counted.most_common(top))


def theme_table(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby("theme")
    table = pd.DataFrame({
        "calls": grouped.size(),
        "avg_score": grouped["overall_score"].mean().round(2),
        "avg_duration_sec": grouped["duration_sec"].mean().round(0),
        "resolved_yes": grouped["resolved"].apply(lambda s: int((s == "yes").sum())),
        "resolved_partial": grouped["resolved"].apply(lambda s: int((s == "partial").sum())),
        "resolved_no": grouped["resolved"].apply(lambda s: int((s == "no").sum())),
    })
    table["resolve_rate_%"] = (table["resolved_yes"] / table["calls"] * 100).round(0)
    return table.sort_values("calls", ascending=False).reset_index()


def frequency_table(counter: Counter, label: str, top: int) -> pd.DataFrame:
    return pd.DataFrame(counter.most_common(top), columns=[label, "mentions"])


def summary_table(cfg: Config, df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    resolved = df["resolved"].value_counts()
    smallest = df.groupby("operator").size().min() if total else 0
    hardest = (df.groupby("theme")
                 .agg(calls=("call_id", "count"), avg=("overall_score", "mean"))
                 .sort_values("avg").head(5).round(2))

    sections = [
        ("Scope",
         f"calls analyzed: {total}\n"
         f"operators: {df['operator'].nunique()}\n"
         f"resolved: {int(resolved.get('yes', 0))} "
         f"({resolved.get('yes', 0) / max(total, 1) * 100:.0f}%)\n"
         f"partial: {int(resolved.get('partial', 0))}\n"
         f"unresolved: {int(resolved.get('no', 0))}"),
        ("Operators", "See the 'operators' sheet: ranking, seniority band, "
                      "per-criterion averages and coaching notes."),
        ("What customers call about",
         "\n".join(f"• {theme} — {count} calls"
                   for theme, count in df["theme"].value_counts().head(8).items())),
        ("Hardest themes (lowest average score)", hardest.to_string()),
        ("Product issues customers reported",
         _bullets(_collect(df, "product_issues"))),
        ("Questions operators could not answer",
         _bullets(_collect(df, "knowledge_gaps"))),
        ("Where operators sounded unsure", _bullets(_collect(df, "uncertainty"))),
        ("Gaps in the script", _bullets(_collect(df, "script_gaps"))),
        ("How to read this",
         "Scores are produced by a language model from an ASR transcript. They "
         "are a screening signal for where to listen, not a performance verdict: "
         "sample sizes per operator are small "
         f"(smallest here: {smallest} calls), and ASR errors on names and "
         "product terms are common. Review the 'calls' sheet before acting on "
         "any individual score."),
    ]
    return pd.DataFrame(sections, columns=["section", "content"])


def _bullets(counter: Counter, top: int = 10) -> str:
    return "\n".join(f"• {text} (x{count})"
                     for text, count in counter.most_common(top)) or "—"


def run_info_table(cfg: Config, df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([
        {"key": "generated_at", "value": datetime.now().isoformat(timespec="seconds")},
        {"key": "calls_in_report", "value": len(df)},
        {"key": "llm_model", "value": cfg.llm.model},
        {"key": "llm_backend", "value": cfg.llm.backend},
        {"key": "asr_model", "value": cfg.asr.model},
        {"key": "prompt_version", "value": PROMPT_VERSION},
        {"key": "rubric_criteria", "value": ", ".join(cfg.rubric.keys)},
        {"key": "transcripts_redacted", "value": str(cfg.privacy.redact_transcripts)},
    ])


def build(cfg: Config, out_name: str) -> Path:
    """Write the workbook. Raises ``SystemExit`` when there is nothing to report."""
    cfg.paths.ensure()
    df = load_analytics(cfg)
    if df.empty:
        raise SystemExit("no analyses found — run `call-audit analyze` first")

    out_path = cfg.paths.reports_dir / out_name
    top_n = cfg.report_top_n
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        summary_table(cfg, df).to_excel(writer, sheet_name="summary", index=False)
        operator_table(cfg, df).to_excel(writer, sheet_name="operators", index=False)
        theme_table(df).to_excel(writer, sheet_name="themes", index=False)
        for sheet, column, label in (
            ("product_issues", "product_issues", "product_issue"),
            ("knowledge_gaps", "knowledge_gaps", "knowledge_gap"),
            ("uncertainty", "uncertainty", "uncertainty"),
            ("script_gaps", "script_gaps", "script_gap"),
        ):
            frequency_table(_collect(df, column), label, top_n).to_excel(
                writer, sheet_name=sheet, index=False)
        df.to_excel(writer, sheet_name="calls", index=False)
        run_info_table(cfg, df).to_excel(writer, sheet_name="run_info", index=False)

        for worksheet in writer.book.worksheets:
            style_sheet(worksheet)
    return out_path
