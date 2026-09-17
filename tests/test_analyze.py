"""The repair layer between a small local model and the report.

Every case here was seen coming out of a 7B model asked for strict JSON.
"""
from call_audit.analyze import normalize_analysis
from call_audit.config import load
from call_audit.llm import extract_json

CFG = load()


def _answer(**overrides) -> dict:
    base = {
        "theme": "Billing and tariffs",
        "theme_detail": "invoice grew after adding seats",
        "language": "en",
        "resolved": "partial",
        "resolution_summary": "explained proration",
        "scores": {key: 7 for key in CFG.rubric.keys},
        "overall_score": 7,
        "operator_strengths": ["found the cause"],
        "operator_weaknesses": [],
        "uncertainty_signs": [],
        "missed_opportunities": [],
        "customer_emotion_start": "angry",
        "customer_emotion_end": "neutral",
        "product_issues": [],
        "knowledge_gaps": [],
        "script_gaps": [],
        "training_recommendations": [],
    }
    base.update(overrides)
    return base


def test_clean_answer_passes_through_without_issues() -> None:
    analysis, issues = normalize_analysis(CFG, _answer())

    assert issues == []
    assert analysis["overall_score"] == 7
    assert set(analysis["scores"]) == set(CFG.rubric.keys)


def test_scores_written_as_strings_are_coerced() -> None:
    analysis, _ = normalize_analysis(CFG, _answer(scores={"greeting": "8/10",
                                                         "empathy": "7,5"}))

    assert analysis["scores"]["greeting"] == 8.0
    assert analysis["scores"]["empathy"] == 7.5


def test_scores_outside_the_scale_are_clamped() -> None:
    analysis, _ = normalize_analysis(CFG, _answer(scores={"greeting": 99,
                                                         "empathy": -4}))

    assert analysis["scores"]["greeting"] == 10
    assert analysis["scores"]["empathy"] == 1


def test_missing_criterion_is_reported_not_hidden() -> None:
    analysis, issues = normalize_analysis(CFG, _answer(scores={"greeting": 8}))

    assert analysis["scores"]["empathy"] is None
    assert any("empathy" in issue for issue in issues)


def test_missing_overall_is_derived_from_the_criteria() -> None:
    answer = _answer(scores={key: 6 for key in CFG.rubric.keys})
    answer.pop("overall_score")

    analysis, issues = normalize_analysis(CFG, answer)

    assert analysis["overall_score"] == 6
    assert "overall_score derived from criteria" in issues


def test_single_string_becomes_a_list() -> None:
    analysis, _ = normalize_analysis(CFG, _answer(operator_strengths="was polite"))

    assert analysis["operator_strengths"] == ["was polite"]


def test_unexpected_enum_values_are_flagged_and_blanked() -> None:
    analysis, issues = normalize_analysis(
        CFG, _answer(resolved="maybe", customer_emotion_end="delighted"))

    assert analysis["resolved"] == "partial"
    assert analysis["customer_emotion_end"] == ""
    assert len(issues) == 2


def test_scores_not_an_object_does_not_crash() -> None:
    analysis, issues = normalize_analysis(CFG, _answer(scores="all good"))

    assert all(value is None for value in analysis["scores"].values())
    assert issues


def test_extract_json_handles_fences_and_prose() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here is the analysis:\n{"a": 1}\nHope that helps!') == {"a": 1}
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_rejects_non_objects_and_garbage() -> None:
    assert extract_json("[1, 2, 3]") is None
    assert extract_json("no json at all") is None
    assert extract_json("") is None
