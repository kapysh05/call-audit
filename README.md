# call-audit

**Support-call QA that never leaves your machine.** Point it at a folder of call
recordings — get an Excel workbook ranking your operators, the themes customers
call about, the defects they report and the questions nobody can answer.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
[![tests](https://github.com/kapysh05/call-audit/actions/workflows/tests.yml/badge.svg)](https://github.com/kapysh05/call-audit/actions/workflows/tests.yml)
![100% local](https://img.shields.io/badge/data-100%25%20local-informational)

| | |
|---|---|
| **In** | a folder of `.mp3` / `.wav` / `.m4a` recordings |
| **Out** | a 9-sheet Excel workbook: ranking, themes, defects, knowledge gaps |
| **Stack** | faster-whisper · any local or OpenAI-compatible LLM · pandas + openpyxl |
| **Hardware** | a laptop CPU, no GPU — 120 calls ≈ 17 h unattended, resumable |
| **Config** | filename schemes, rubric, themes, output language — all TOML, no code |
| **Proof** | 67 tests, CI on Linux + Windows × 3.11/3.12, demo runs with no audio and no model |

```
recordings/     index       →  one row per call          seconds
    *.mp3       sample      →  N calls per operator      instant
                transcribe  →  data/transcripts/*.json   ≈1.1× real time
                analyze     →  data/analytics/*.json     ≈5 min per call
                report      →  data/reports/*.xlsx       seconds
```

**Why it looks like this.** Local inference on a CPU costs minutes per call, so a
month of a real contact centre is days of compute. Everything interesting here
follows from that one constraint:

- **Sampling per operator**, not across the corpus — a busy agent and a quiet one
  contribute equally, so the ranking compares people, not call volume.
- **Idempotent stages** — an interrupted overnight run resumes instead of
  restarting. Losing 17 hours to a stray Ctrl+C is the failure this prevents.
- **A repair layer** — small models drift from the schema. Scores are coerced and
  clamped, every repair is recorded, and one bad answer never costs the call.

## See it in 60 seconds

No model, no GPU, no recordings — the repo ships a synthetic corpus.

```bash
pip install -e ".[dev]"
python examples/make_demo_data.py
call-audit --data-dir examples/demo report --out demo.xlsx
```

## On your own calls

```bash
pip install -e ".[asr]"                       # adds faster-whisper
call-audit doctor                             # deps, paths, LLM, privacy warnings
call-audit --audio-root /data/recordings index
call-audit sample --per-op 50 --min-sec 30    # prints a runtime estimate first
call-audit transcribe && call-audit analyze
call-audit report --out april.xlsx
```

`call-audit run` chains all five stages, and Ctrl+C is always safe.

Aim it at a different contact centre by copying
[`config/example-multilingual.toml`](config/example-multilingual.toml). Filename
regexes, rubric criteria, call themes and output language are configuration — and
the rubric generates the prompt, the response schema *and* the report columns, so
the three cannot drift apart.

## Measured on a laptop CPU

Intel i5-1235U, no GPU, `whisper-medium` INT8 and a 7B instruct model at Q4:

| Transcription | Scoring | 120 calls end to end | Schema failures |
|---|---|---|---|
| ~1.1× real time | ~5 min/call at ~5 tok/s | ~17 h | 1 in 120, recovered on retry |

## Privacy by default

Customer numbers are **hashed** in the index, transcripts are **redacted**
(`[EMAIL]`, `[PHONE]`, `[ID]`) before they are stored or sent to a model, and
`data/` is in `.gitignore` entirely. A leaked call corpus is a list of customers
and what went wrong for them; the defaults assume that.

## Honest limits

An LLM reading an ASR transcript is a screening tool, not a performance review.
Per-operator samples are small, small models compress scores toward the middle of
the scale, and ASR mangles names and product terms. The workbook repeats this on
its `summary` sheet, where the person acting on it will actually see it.

## More

- [docs/REFERENCE.md](docs/REFERENCE.md) — commands, data contracts, every config key, troubleshooting
- `pytest -q` — 67 tests, none of which need a model or any audio

MIT
