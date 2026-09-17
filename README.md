# call-audit

**Support-call QA that runs entirely on your own machine.** Point it at a folder
of call recordings and get an Excel workbook: who handled calls well, what
customers actually called about, which product defects keep coming up, and which
questions nobody on the desk can answer. No audio, no transcript and no customer
data ever leaves the host.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![tests 67 passing](https://img.shields.io/badge/tests-67%20passing-brightgreen)
![100% local](https://img.shields.io/badge/data-100%25%20local-informational)

| | |
|---|---|
| **In** | a folder of `.mp3` / `.wav` / `.m4a` call recordings |
| **Out** | a 9-sheet Excel workbook: operator ranking, themes, defects, knowledge gaps |
| **Stack** | Python 3.11 · faster-whisper (ASR) · any local or OpenAI-compatible LLM · pandas + openpyxl |
| **Hardware** | a laptop CPU, no GPU. 120 calls ≈ 17 h unattended, resumable after Ctrl+C |
| **Configurable** | filename schemes, scoring rubric, call themes, output language — all TOML, zero code changes |
| **Proof** | 67 tests, CI on 3.11 and 3.12, and a synthetic corpus so you can see the output with no audio and no model |

```
recordings/          call-audit index        data/index/calls.parquet
   *.mp3       ──▶   filename + duration ──▶ one row per call
                                                   │
                     call-audit sample             │  stratified, per operator
                     ─────────────────────▶ data/index/sample.parquet
                                                   │
                     call-audit transcribe         │  faster-whisper, resumable
                     ─────────────────────▶ data/transcripts/<call_id>.json
                                                   │
                     call-audit analyze            │  LLM scores it, resumable
                     ─────────────────────▶ data/analytics/<call_id>.json
                                                   │
                     call-audit report             │  pandas + openpyxl
                     ─────────────────────▶ data/reports/report.xlsx
```

**Why it is built this way.** Local-only inference on a CPU costs minutes per
call, so a month of a real contact centre is days of compute. Three decisions
follow from that, and they are the interesting part of this repository:
sampling per operator instead of processing everything, idempotent stages so an
interrupted overnight run resumes instead of restarting, and a repair layer
that fixes the malformed JSON small models return instead of losing the call.

Full command and data-format reference: [docs/REFERENCE.md](docs/REFERENCE.md).

---

## Running it

### Prerequisites

| | |
|---|---|
| Python | 3.11 or newer |
| Disk | ~1.5 GB for the ASR model, ~5 GB for a 7B LLM |
| LLM | [Ollama](https://ollama.com) running locally, **or** any OpenAI-compatible endpoint |
| ffmpeg | not needed — faster-whisper decodes audio through PyAV |

### 1. Install

```bash
git clone https://github.com/<you>/call-audit.git
cd call-audit
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -e ".[asr,dev]"
```

`[asr]` adds faster-whisper, `[dev]` adds pytest. Without `[asr]` everything
except the transcription stage still works — useful on a machine that only
builds reports.

### 2. See the output before committing any compute

The repository ships a synthetic corpus: twelve invented calls, three invented
operators, pre-scored. No model, no GPU, no recordings.

```bash
python examples/make_demo_data.py
call-audit --data-dir examples/demo report --out demo.xlsx
```

Open `examples/demo/reports/demo.xlsx`. That is exactly the shape of the real
output.

### 3. Check the machine

```bash
call-audit doctor
```

Verifies dependencies, that the audio root exists, that the LLM endpoint answers
and that the model is actually pulled, and warns when the hashing salt is unset.
Run this *before* starting an overnight job, not after.

```bash
ollama pull qwen2.5:7b-instruct      # if doctor says the model is missing
```

### 4. Run the pipeline on real calls

Point it at your recordings once, either with `--audio-root`, or with
`CALL_AUDIT_AUDIO_ROOT`, or in a config file.

```bash
call-audit --audio-root /data/recordings index
call-audit sample --per-op 50 --min-sec 30
call-audit transcribe
call-audit analyze
call-audit report --out april.xlsx
```

| Stage | Writes | Typical cost | Resumable |
|---|---|---|---|
| `index` | `data/index/calls.parquet` | seconds for thousands of files | — |
| `sample` | `data/index/sample.parquet` | instant; prints a runtime estimate | — |
| `transcribe` | `data/transcripts/*.json` | ≈ 1.1× real time on CPU | yes |
| `analyze` | `data/analytics/*.json` | ≈ 5 min per call on a 7B model | yes |
| `report` | `data/reports/*.xlsx` | seconds | — |

`call-audit run` chains all five and asks for confirmation before the two slow
stages. Ctrl+C is safe at any point: both slow stages skip calls that already
have output, so rerunning the same command continues where it stopped.

Process one month at a time by passing a sub-folder: `call-audit index 2026-04`.

### 5. Read the workbook

| Sheet | Contents |
|---|---|
| `summary` | Plain-language digest of the run, including the caveats |
| `operators` | The ranking: seniority band, per-criterion averages, resolution rates, emotion shifts, aggregated coaching notes |
| `themes` | What customers call about, average score and resolution rate per theme |
| `product_issues` | Defects customers described, by frequency |
| `knowledge_gaps` | Questions operators could not answer |
| `uncertainty` | Moments operators sounded unsure |
| `script_gaps` | Situations the support script does not cover |
| `calls` | One row per call, for audit |
| `run_info` | Model, prompt version, rubric, sample size — how this workbook was produced |

### When something goes wrong

| Symptom | Cause and fix |
|---|---|
| `paths.audio_root is not set` | Pass `--audio-root`, export `CALL_AUDIT_AUDIO_ROOT`, or set it in your config |
| `no audio files under ...` | Wrong folder, or the extension is missing from `audio.extensions` |
| Every operator is `unknown` | No filename pattern matched. Check `call-audit index` output and add a pattern |
| `sample is empty` | `--min-sec` is above every call's duration, or the operator whitelist excludes everyone |
| `cannot reach http://localhost:11434` | Ollama is not running. Start it, then `call-audit doctor` |
| `analyze` reports `unparseable` | The model ignored the schema. Rerun with `--retry-failed`; if it persists, use a larger model |
| `Permission denied` on the `.xlsx` | The workbook is open in Excel. Close it and rerun `report` |

---

## Making it yours

Nothing about a particular company, PBX or language is hard-coded. Copy
[`config/example-multilingual.toml`](config/example-multilingual.toml), change
what you need, and pass it with `--config`. Your file lists only the keys you
override; the rest is merged from
[`default.toml`](src/call_audit/default.toml).

**Filenames.** Every PBX exports its own scheme, so schemes are regexes in
config. Named groups `ts`, `operator`, `client`, `direction`, `dest` and
`call_id` are recognised; `timestamp_format` is an ordinary `strptime` format:

```toml
[[filename.patterns]]
name = "pbx_incoming"
regex = '''^(?P<ts>\d{2}-\d{2}-\d{4}_\d{2}-\d{2})_(?P<client>\d+)_(?P<direction>incoming)_(?P<dest>\d+)_user_(?P<operator>[^.]*)$'''
timestamp_format = "%d-%m-%Y_%H-%M"
```

A file matching nothing still enters the index with its modification time and an
`unknown` operator, so you get a usable index on day one and refine patterns
afterwards.

**The rubric drives everything.** Criteria are configuration, and they generate
the prompt, the JSON schema the model must return, *and* the report columns — so
the three cannot drift apart:

```toml
[[rubric.criteria]]
key = "data_handling"
title = "Customer data handling"
description = "Verifies identity before changing anything."
```

**The domain block** describes your product, customers, call themes and
languages; `output_language` decides the language the model writes its findings
in. Inspect what your config produces before spending a night of compute:

```bash
call-audit --config my.toml show-prompt --with-example
```

The instruction scaffolding stays in English while your domain text stays in
your language; multilingual instruct models handle the mix and still answer in
`output_language`.

**Somewhere other than Ollama?** Set `llm.backend = "openai"` and `llm.base_url`
to any OpenAI-compatible `/chat/completions` endpoint — a hosted API, vLLM, LM
Studio, llama.cpp. Both backends are plain HTTP; there is no vendor SDK in the
dependency list.

## Privacy defaults

A leaked call corpus is a list of customers, what they bought and what went
wrong for them. The defaults assume that:

- **customer numbers are hashed** in the index (`privacy.store_raw_identifiers =
  false`), salted from `CALL_AUDIT_SALT`, so repeat callers still group together
  but the file is not a phone list;
- **transcripts are redacted at write time** — e-mail addresses, phone numbers
  and long digit runs become `[EMAIL]`, `[PHONE]`, `[ID]` before anything is
  stored or sent to a model, and the prompt explains those tokens so the model
  does not read them as recognition errors;
- **`data/` is in `.gitignore`**, all of it.

This is damage reduction, not compliance: a transcript can still contain a name
in plain prose. Treat `data/` as production customer data.

## Performance, measured

On a 12-core laptop CPU (Intel i5-1235U, no GPU), `whisper-medium` at INT8 and a
7B instruct model at Q4:

| | |
|---|---|
| Transcription | ~1.1× real time — one hour of audio ≈ one hour of CPU |
| Scoring | ~5 min per call at ~5 tok/s |
| 120 calls end to end | ~17 h |
| Schema failures | 1 answer in 120 unparseable, recovered by a retry |

That is why the sampling stage exists, and why `call-audit sample` estimates
runtime from *your* machine's measured throughput once it has history to learn
from.

## How to read the scores

An LLM reading an ASR transcript is a screening tool, not a performance review.

- Per-operator samples are small; the ranking says who to listen to first, not
  who is good at their job.
- Small models compress scores toward the middle of the scale. Calibrate the
  `[[rubric.levels]]` bands against your own data instead of trusting defaults.
- ASR mangles names, e-mail addresses and product terms. The prompt tells the
  model not to blame the operator for that; it does not always listen.
- Scores are not comparable across models or prompt versions, which is why both
  are recorded in every analysis file and on the `run_info` sheet.

The `summary` sheet repeats this inside the workbook, where the person acting on
it will actually see it.

## Development

```bash
pip install -e ".[dev]"
python examples/make_demo_data.py
pytest -q
```

67 tests covering filename parsing, config layering, the privacy helpers, the
repair layer for malformed model answers, sampling, and the report build. None
of them need a model or any audio, so CI runs the whole suite in seconds.

## License

MIT
