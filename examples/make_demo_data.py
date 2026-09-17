"""Generate the synthetic demo corpus under ``examples/demo``.

Everything this writes is invented: the operators, the customers, the calls and
the scores. It exists so that ``call-audit report`` can be run — and the
workbook inspected — without access to real recordings, and so that nobody is
ever tempted to commit real ones for a demo.

    python examples/make_demo_data.py
    call-audit --data-dir examples/demo report --out demo.xlsx
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent / "demo"
OPERATORS = ["Dana R.", "Marco P.", "Priya S."]

CALLS = [
    {
        "theme": "Account access",
        "detail": "Customer locked out after changing their phone number.",
        "text": ("Hello, support desk, my name is {op}, how can I help? — Hi, I "
                 "cannot log in since yesterday, it keeps asking for a code sent "
                 "to my old number [PHONE]. — I understand, that is frustrating. "
                 "Let me verify the account and move the second factor to your "
                 "new number. Can you confirm the company name on the account? "
                 "— Yes, it is Harbour Logistics. — Thank you, I have reset it, "
                 "you should get a code now. — Got it, I am in. Thank you."),
        "resolved": "yes",
        "emotions": ("frustrated", "satisfied"),
        "base": 8,
        "strengths": ["Named the company and themselves in the greeting",
                      "Acknowledged the customer's frustration before acting",
                      "Confirmed the fix worked before closing"],
        "weaknesses": ["Did not explain how to avoid the same lockout next time"],
        "uncertainty": [],
        "product_issues": ["Second factor stays bound to an old phone number "
                           "after the number is changed in the profile"],
        "knowledge_gaps": [],
        "script_gaps": [],
        "coaching": ["Add a short prevention tip at the end of access calls"],
    },
    {
        "theme": "Billing and tariffs",
        "detail": "Customer asked why the invoice grew after adding two seats.",
        "text": ("Support desk, {op} speaking. — Our invoice went up and nobody "
                 "told us why. — Let me look. You added two seats on the 3rd, so "
                 "the plan was prorated for the rest of the month. — Nobody "
                 "warned us about that. — I am sorry, I understand. I can send "
                 "the breakdown to [EMAIL] so you can check it line by line. — "
                 "Fine, send it."),
        "resolved": "partial",
        "emotions": ("angry", "neutral"),
        "base": 6,
        "strengths": ["Found the cause quickly", "Offered a written breakdown"],
        "weaknesses": ["Did not apologise for the missing notification",
                       "Left the customer without a next step for a refund request"],
        "uncertainty": ["Hesitated when asked whether proration can be disabled"],
        "product_issues": ["Adding seats does not trigger any notification about "
                           "the prorated charge"],
        "knowledge_gaps": ["Whether proration can be turned off for annual plans"],
        "script_gaps": ["No script branch for billing complaints that need a refund"],
        "coaching": ["Practise billing objections", "Learn the proration rules"],
    },
    {
        "theme": "Documents",
        "detail": "Signed document did not reach the counterparty.",
        "text": ("Hello, support. — I signed the delivery note two days ago and "
                 "the other side still does not see it. — Let me check the "
                 "document status. It is signed on your side and waiting for the "
                 "counterparty to accept it. — So it is stuck? — It is waiting, "
                 "not stuck. They have to open it from their inbox. — And how "
                 "would I know that? Nothing says so. — I agree it is not "
                 "obvious."),
        "resolved": "partial",
        "emotions": ("frustrated", "neutral"),
        "base": 6,
        "strengths": ["Checked the real document status instead of guessing"],
        "weaknesses": ["Did not offer to notify the counterparty",
                       "Closed the call without a clear next step"],
        "uncertainty": ["Unsure whether a reminder can be sent from the portal"],
        "product_issues": ["Document status 'waiting for counterparty' is not "
                           "visible to the sender"],
        "knowledge_gaps": ["How to send a reminder to a counterparty"],
        "script_gaps": ["No branch for 'the other side has not opened it'"],
        "coaching": ["Walk through the document lifecycle with the product team"],
    },
    {
        "theme": "Integrations",
        "detail": "API key rejected after a scheduled rotation.",
        "text": ("Support, how can I help? — Our integration stopped working "
                 "this morning, every request comes back unauthorised. — Did you "
                 "rotate the key recently? — Our admin did, last night. — Then "
                 "the old key is still in your config. Replace it and restart the "
                 "job. — That did it. Thanks."),
        "resolved": "yes",
        "emotions": ("neutral", "satisfied"),
        "base": 7,
        "strengths": ["Diagnosed from one symptom", "Gave a concrete fix"],
        "weaknesses": ["No greeting with the company name",
                       "Did not confirm whether other integrations use the same key"],
        "uncertainty": [],
        "product_issues": ["Key rotation does not warn about integrations still "
                           "using the previous key"],
        "knowledge_gaps": [],
        "script_gaps": [],
        "coaching": ["Use the full greeting on every call"],
    },
    {
        "theme": "Notifications",
        "detail": "Customer receives duplicate e-mails for every event.",
        "text": ("Support desk, {op}. — I get three identical e-mails for every "
                 "signature. — That is not expected. Are the addresses different? "
                 "— No, the same one, three times. — I have not seen this before. "
                 "I will pass it to the team and come back to you. — When? — I "
                 "cannot promise a date, sorry."),
        "resolved": "no",
        "emotions": ("neutral", "frustrated"),
        "base": 4,
        "strengths": ["Was honest about not knowing"],
        "weaknesses": ["No timeframe, no ticket number, no follow-up plan",
                       "Let the customer end the call unhappy"],
        "uncertainty": ["Admitted to never having seen the issue",
                        "Could not say when anyone would respond"],
        "product_issues": ["Duplicate notification e-mails for a single signature event"],
        "knowledge_gaps": ["What to do when an issue has to be escalated"],
        "script_gaps": ["No escalation script with an expected response time"],
        "coaching": ["Train the escalation path", "Always leave a ticket number"],
    },
    {
        "theme": "Other",
        "detail": "Customer asked for training for a new employee.",
        "text": ("Hello, support desk, {op} speaking, how can I help? — We hired "
                 "a new accountant, can someone show her the portal? — I can send "
                 "the onboarding guide and book a 30-minute session. — That would "
                 "be great. — Booked for Thursday, the invite is on its way."),
        "resolved": "yes",
        "emotions": ("neutral", "satisfied"),
        "base": 9,
        "strengths": ["Full greeting", "Offered more than was asked",
                      "Closed with a concrete commitment"],
        "weaknesses": [],
        "uncertainty": [],
        "product_issues": [],
        "knowledge_gaps": [],
        "script_gaps": [],
        "coaching": ["None — use this call as a good example in training"],
    },
]

CRITERIA = ["greeting", "empathy", "product_knowledge",
            "communication_clarity", "problem_solving", "script_adherence"]


def build(seed: int = 7) -> tuple[int, int]:
    rng = random.Random(seed)
    transcripts_dir = DEMO_DIR / "transcripts"
    analytics_dir = DEMO_DIR / "analytics"
    for directory in (transcripts_dir, analytics_dir):
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("*.json"):
            stale.unlink()

    start = datetime(2026, 4, 6, 9, 15)
    written = 0
    for index in range(12):
        call = CALLS[index % len(CALLS)]
        operator = OPERATORS[index % len(OPERATORS)]
        call_id = f"demo{index:04d}"
        timestamp = start + timedelta(hours=index * 3 + index % 4)
        duration = rng.randint(95, 420)
        text = call["text"].format(op=operator.split()[0])

        (transcripts_dir / f"{call_id}.json").write_text(json.dumps({
            "call_id": call_id,
            "meta": {
                "call_id": call_id,
                "operator": operator,
                "direction": "incoming" if index % 3 else "outgoing",
                "timestamp": timestamp.isoformat(sep=" "),
                "duration_sec_file": duration,
            },
            "language": "en",
            "language_prob": round(rng.uniform(0.93, 0.99), 3),
            "duration_sec": duration,
            "transcribe_sec": round(duration * rng.uniform(0.8, 1.3), 2),
            "rtf": round(rng.uniform(0.8, 1.3), 2),
            "redacted": True,
            "segments": [{"start": 0.0, "end": float(duration), "text": text}],
            "text": text,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        base = call["base"] + rng.choice([-1, 0, 0, 1])
        scores = {c: max(1, min(10, base + rng.choice([-1, 0, 1]))) for c in CRITERIA}
        overall = round(sum(scores.values()) / len(scores), 2)

        (analytics_dir / f"{call_id}.json").write_text(json.dumps({
            "call_id": call_id,
            "operator": operator,
            "direction": "incoming" if index % 3 else "outgoing",
            "duration_sec": duration,
            "model": "demo-fixture",
            "prompt_version": "1.0",
            "elapsed_sec": round(rng.uniform(180, 380), 1),
            "tokens_in": rng.randint(1400, 2600),
            "tokens_out": rng.randint(280, 520),
            "tokens_per_sec": round(rng.uniform(3.0, 6.5), 1),
            "issues": ["overall_score derived from criteria"] if index == 4 else [],
            "analysis": {
                "theme": call["theme"],
                "theme_detail": call["detail"],
                "language": "en",
                "resolved": call["resolved"],
                "resolution_summary": call["detail"],
                "scores": scores,
                "overall_score": overall,
                "customer_emotion_start": call["emotions"][0],
                "customer_emotion_end": call["emotions"][1],
                "operator_strengths": call["strengths"],
                "operator_weaknesses": call["weaknesses"],
                "uncertainty_signs": call["uncertainty"],
                "missed_opportunities": call["weaknesses"][:1],
                "product_issues": call["product_issues"],
                "knowledge_gaps": call["knowledge_gaps"],
                "script_gaps": call["script_gaps"],
                "training_recommendations": call["coaching"],
            },
            "raw_if_parse_failed": None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1

    return written, written


if __name__ == "__main__":
    transcripts, analytics = build()
    print(f"wrote {transcripts} transcripts and {analytics} analyses to {DEMO_DIR}")
