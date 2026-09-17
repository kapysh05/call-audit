"""Prompt construction.

The prompt is generated from configuration, not written by hand: the rubric
criteria become both the instructions and the keys of the JSON schema, and the
domain block describes the business the operators are supporting. Add a
criterion to the config and it appears in the prompt, in the model's answer and
in the report — no code changes, and no risk of the three drifting apart.

Three things here are lessons from real call-centre audio rather than
decoration:

* mono recordings have no speaker labels, so the model is told to infer roles
  from context instead of silently inventing them;
* the transcript comes from ASR, and the model is told not to penalise the
  operator for its mistakes;
* multilingual contact centres code-switch mid-sentence, so the language of
  the call is an output field rather than an assumption.
"""
from __future__ import annotations

import json

from .config import Config

#: Bump when the wording changes — it is recorded in every analysis file so you
#: can tell which prompt produced a given score.
PROMPT_VERSION = "1.0"

FIXED_FIELDS: dict[str, str] = {
    "theme": "the single best-fitting theme for the call",
    "theme_detail": "one sentence on what actually happened",
    "language": "language of the conversation, or 'mixed' when the speakers switch",
    "resolved": "yes | no | partial",
    "resolution_summary": "what was done, or why it was not, in 1-2 sentences",
    "overall_score": "overall quality of the operator's handling of this call",
    "operator_strengths": "list of what the operator did well",
    "operator_weaknesses": "list of what the operator did badly",
    "uncertainty_signs": "list of moments where the operator sounded unsure",
    "missed_opportunities": "list of things that could have been done better",
    "customer_emotion_start": "satisfied | neutral | frustrated | angry",
    "customer_emotion_end": "satisfied | neutral | frustrated | angry",
    "product_issues": "list of real product or service defects the customer described",
    "knowledge_gaps": "list of customer questions the operator could not answer precisely",
    "script_gaps": "list of situations the support script does not cover",
    "training_recommendations": "list of concrete coaching actions for this operator",
}


def response_schema(cfg: Config) -> dict:
    """The JSON object the model is asked to return, as an example skeleton."""
    scale = f"{cfg.rubric.scale_min}-{cfg.rubric.scale_max}"
    schema: dict = {
        "theme": " | ".join(cfg.domain.themes) if cfg.domain.themes else "short theme label",
        "theme_detail": "string",
        "language": " | ".join(cfg.domain.languages) + " | mixed",
        "resolved": "yes | no | partial",
        "resolution_summary": "string",
        "scores": {c.key: scale for c in cfg.rubric.criteria},
        "overall_score": scale,
    }
    for key in ("operator_strengths", "operator_weaknesses", "uncertainty_signs",
                "missed_opportunities"):
        schema[key] = ["string"]
    schema["customer_emotion_start"] = "satisfied | neutral | frustrated | angry"
    schema["customer_emotion_end"] = "satisfied | neutral | frustrated | angry"
    for key in ("product_issues", "knowledge_gaps", "script_gaps",
                "training_recommendations"):
        schema[key] = ["string"]
    return schema


def build_system_prompt(cfg: Config) -> str:
    domain, rubric = cfg.domain, cfg.rubric
    parts: list[str] = [
        f"You are {domain.role} for {domain.business}.",
    ]
    if domain.business_details:
        parts.append(domain.business_details)
    if domain.customers:
        parts.append(f"The customers are {domain.customers}.")

    parts.append(
        "You are given the transcript of one phone call between a support "
        "operator and a customer. Judge the operator, not the customer."
    )
    if domain.mono_recording:
        parts.append(
            "The recording is mono and the speakers are NOT labelled. Work out "
            "who is who from context: whoever greets the caller and names the "
            "company is the operator; whoever describes a problem of their own "
            "is the customer."
        )
    parts.append(
        "The transcript comes from automatic speech recognition and contains "
        "errors. Names, e-mail addresses and product names are often mangled. "
        "Never hold an ASR error against the operator."
    )
    if domain.asr_hints:
        parts.append("Known ASR confusions: " + "; ".join(domain.asr_hints) + ".")
    if len(domain.languages) > 1:
        parts.append(
            "Calls may be in " + ", ".join(domain.languages) +
            ", and speakers may switch language mid-call. Report what you hear "
            "in the 'language' field; do not treat a language switch as a fault."
        )
    parts.append(
        "Some identifiers have been replaced by [PHONE], [EMAIL] or [ID] before "
        "you received the transcript. Treat them as redacted values, not as "
        "speech errors, and never try to reconstruct them."
    )

    scale = f"{rubric.scale_min} (worst) to {rubric.scale_max} (best)"
    criteria = "\n".join(
        f"- {c.key}: {c.description or c.title}" for c in rubric.criteria
    )
    parts.append(f"Score every criterion from {scale}:\n{criteria}")
    parts.append(
        "Use the whole scale. A routine call handled adequately is a middle "
        "score; reserve the top of the scale for genuinely excellent handling "
        "and the bottom for calls that failed the customer."
    )
    parts.append(
        f"Write every free-text field in {domain.output_language}. "
        "Answer with a single valid JSON object and nothing else: no markdown "
        "fences, no commentary before or after."
    )
    return "\n\n".join(parts)


def build_user_prompt(cfg: Config, meta: dict, transcript: str) -> str:
    schema = json.dumps(response_schema(cfg), ensure_ascii=False, indent=2)
    duration = meta.get("duration_sec_file") or meta.get("duration_sec") or 0
    themes = (
        "Pick `theme` from exactly this list: " + ", ".join(cfg.domain.themes) + "."
        if cfg.domain.themes else
        "Use a short theme label of your own."
    )
    return "\n".join([
        "Call metadata:",
        f"- operator: {meta.get('operator')}",
        f"- direction: {meta.get('direction')} "
        "(incoming = the customer called, outgoing = the operator called)",
        f"- duration: {int(duration)} seconds",
        f"- ASR language: {meta.get('language')} "
        f"(confidence {meta.get('language_prob')})",
        "",
        "Transcript:",
        "---",
        transcript.strip(),
        "---",
        "",
        themes,
        "",
        "Return JSON with exactly this shape:",
        schema,
    ])


def build_messages(cfg: Config, meta: dict, transcript: str) -> list[dict]:
    return [
        {"role": "system", "content": build_system_prompt(cfg)},
        {"role": "user", "content": build_user_prompt(cfg, meta, transcript)},
    ]
