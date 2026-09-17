"""End-to-end check of the reporting stage on the synthetic demo corpus."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from call_audit.config import from_tree, load_tree
from call_audit.report import build, load_analytics, operator_table

DEMO_ANALYTICS = Path(__file__).resolve().parents[1] / "examples" / "demo" / "analytics"


@pytest.fixture()
def cfg(tmp_path):
    config = from_tree(load_tree(env={"CALL_AUDIT_DATA_DIR": str(tmp_path)}))
    config.paths.ensure()
    if not DEMO_ANALYTICS.exists():  # pragma: no cover - generated on demand
        subprocess.run([sys.executable,
                        str(DEMO_ANALYTICS.parents[1] / "make_demo_data.py")],
                       check=True)
    for source in DEMO_ANALYTICS.glob("*.json"):
        shutil.copy(source, config.paths.analytics_dir / source.name)
    return config


def test_report_has_every_sheet(cfg) -> None:
    path = build(cfg, "report.xlsx")
    sheets = pd.ExcelFile(path).sheet_names

    assert sheets == ["summary", "operators", "themes", "product_issues",
                      "knowledge_gaps", "uncertainty", "script_gaps",
                      "calls", "run_info"]


def test_operator_sheet_is_ranked_and_scored(cfg) -> None:
    table = operator_table(cfg, load_analytics(cfg))

    assert list(table["rank"]) == list(range(1, len(table) + 1))
    assert table["overall_score"].is_monotonic_decreasing
    for key in cfg.rubric.keys:
        assert key in table.columns
    assert set(table["level"]) <= {"junior", "middle", "senior", "n/a"}


def test_resolution_counts_add_up(cfg) -> None:
    df = load_analytics(cfg)
    table = operator_table(cfg, df)

    totals = table[["resolved_yes", "resolved_partial", "resolved_no"]].sum(axis=1)

    assert list(totals) == list(table["calls"])
    assert table["calls"].sum() == len(df)


def test_findings_are_split_back_into_rows(cfg) -> None:
    """Free-text findings are stored joined; the report must count them apart."""
    path = build(cfg, "report.xlsx")
    issues = pd.ExcelFile(path).parse("product_issues")

    assert list(issues.columns) == ["product_issue", "mentions"]
    assert issues["mentions"].max() > 1
    assert not issues["product_issue"].str.contains(r"\|").any()


def test_unparseable_analyses_are_excluded(cfg) -> None:
    (cfg.paths.analytics_dir / "broken.json").write_text(
        json.dumps({"call_id": "broken", "operator": "x", "analysis": None}),
        encoding="utf-8")

    assert "broken" not in set(load_analytics(cfg)["call_id"])


def test_report_refuses_to_build_from_nothing(tmp_path) -> None:
    empty = from_tree(load_tree(env={"CALL_AUDIT_DATA_DIR": str(tmp_path / "empty")}))

    with pytest.raises(SystemExit, match="run `call-audit analyze`"):
        build(empty, "report.xlsx")


def test_summary_states_the_caveats(cfg) -> None:
    path = build(cfg, "report.xlsx")
    summary = pd.ExcelFile(path).parse("summary")
    text = " ".join(summary["content"].astype(str))

    assert "not a performance verdict" in text
