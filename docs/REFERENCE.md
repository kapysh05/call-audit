# Reference

The interface of `call-audit`: its commands, the files each stage writes, and
every configuration key. This is the contract — stages talk to each other only
through the files described here, so you can replace any one of them (a
different ASR engine, your own scorer, a report in another format) without
touching the rest.

- [Commands](#commands)
- [Environment variables](#environment-variables)
- [Data contracts](#data-contracts)
- [Model response schema](#model-response-schema)
- [Configuration keys](#configuration-keys)
- [The workbook](#the-workbook)
- [Troubleshooting](#troubleshooting)

## Commands

Global options, valid before any subcommand:

| Option | Meaning |
|---|---|
| `--config PATH` | TOML file merged over the shipped defaults |
| `--audio-root PATH` | override `paths.audio_root` |
| `--data-dir PATH` | override `paths.data_dir` |

Exit code is `0` on success, `1` on a failed check or an empty result, `130`
after Ctrl+C.

### `call-audit doctor`

Checks dependencies, the audio root, the LLM endpoint and whether the model is
pulled, and warns when `CALL_AUDIT_SALT` is unset. Returns `1` if anything needs
attention. Takes no arguments.

### `call-audit index [SUBDIR]`

Scans the audio root (or one sub-folder of it — pass `2026-04` to process a
single month) and writes one row per recording.

| Option | Default | Meaning |
|---|---|---|
| `SUBDIR` | whole root | sub-folder of `paths.audio_root` to scan |
| `--out NAME` | `calls.parquet` | file name inside `data/index/` |

Reads audio headers only; nothing is decoded, so thousands of files take
seconds. Files whose names match no pattern are still indexed (see
`filename.on_no_match`) and counted in the printed summary.

### `call-audit sample`

Picks the calls that are worth the compute: up to N per operator, longer than a
floor, reproducible from a seed.

| Option | Default | Meaning |
|---|---|---|
| `--source NAME` | `calls.parquet` | index to sample from |
| `--out NAME` | `sample.parquet` | file name inside `data/index/` |
| `--per-op N` | `sampling.per_operator` | max calls per operator |
| `--min-sec S` | `sampling.min_duration_sec` | skip calls shorter than this |

Prints a runtime estimate for the two slow stages, measured from this machine's
own history when there is any. Returns `1` when the filters leave nothing.

### `call-audit transcribe [SAMPLE]`

Transcribes every call in the sample that has no transcript yet. `SAMPLE`
defaults to `sample.parquet`. Idempotent — rerun to resume.

### `call-audit analyze`

Scores every transcript that has no analysis yet. Idempotent.

| Option | Default | Meaning |
|---|---|---|
| `--only CALL_ID` | all | analyze a single call |
| `--limit N` | all | stop after N calls, for a trial run |
| `--retry-failed` | off | also redo calls whose stored answer was unparseable |

### `call-audit report`

Aggregates `data/analytics/*.json` into the workbook. `--out NAME` defaults to
`report.xlsx`, written to `data/reports/`. Exits with an error when there is
nothing to aggregate.

### `call-audit run [SUBDIR]`

`index` → `sample` → `transcribe` → `analyze` → `report` in one go. Accepts
`--per-op`, `--min-sec`, `--out`, and `--yes` to skip the confirmation before
the slow stages.

### `call-audit show-prompt`

Prints the system prompt your configuration generates; `--with-example` also
renders the user turn on a dummy transcript. Use it to review rubric and domain
changes before spending compute on them.

## Environment variables

| Variable | Overrides |
|---|---|
| `CALL_AUDIT_AUDIO_ROOT` | `paths.audio_root` |
| `CALL_AUDIT_DATA_DIR` | `paths.data_dir` |
| `CALL_AUDIT_MODEL_CACHE` | `paths.model_cache` |
| `CALL_AUDIT_ASR_MODEL` | `asr.model` |
| `CALL_AUDIT_ASR_DEVICE` | `asr.device` |
| `CALL_AUDIT_LLM_BACKEND` | `llm.backend` |
| `CALL_AUDIT_LLM_MODEL` | `llm.model` |
| `CALL_AUDIT_LLM_BASE_URL` | `llm.base_url` |
| `CALL_AUDIT_API_KEY` | API key for the `openai` backend (name set by `llm.api_key_env`) |
| `CALL_AUDIT_SALT` | salt for customer-identifier hashing (name set by `privacy.hash_salt_env`) |

Precedence: shipped defaults < `--config` file < environment < command-line
flags.

## Data contracts

### `data/index/*.parquet`

One row per recording.

| Column | Type | Notes |
|---|---|---|
| `call_id` | str | stable id, derived from the path relative to the audio root |
| `timestamp` | datetime | from the filename, or file mtime when nothing matched |
| `date`, `hour`, `weekday` | date / int / str | derived from `timestamp` |
| `operator` | str | `unknown` when the filename gave no operator |
| `direction` | str | `incoming` / `outgoing` / `None` |
| `client_ref` | str | salted hash of the customer number, or the raw value when `privacy.store_raw_identifiers = true` |
| `dest_ref` | str | same, for the dialled number |
| `duration_sec` | float | from the audio header; `None` if unreadable |
| `size_bytes` | int | |
| `filename`, `path` | str | local only — never leaves this file |
| `pattern` | str | which filename pattern matched, `None` if none did |
| `name_parsed` | bool | `False` means the timestamp came from mtime |

### `data/transcripts/<call_id>.json`

```json
{
  "call_id": "demo0000",
  "meta": {
    "call_id": "demo0000",
    "operator": "Dana R.",
    "direction": "incoming",
    "timestamp": "2026-04-06 09:15:00",
    "duration_sec_file": 214
  },
  "language": "en",
  "language_prob": 0.982,
  "duration_sec": 214.0,
  "transcribe_sec": 231.4,
  "rtf": 1.08,
  "redacted": true,
  "segments": [{ "start": 0.0, "end": 214.0, "text": "Hello, support desk ..." }],
  "text": "Hello, support desk ..."
}
```

`rtf` is the real-time factor: seconds of CPU per second of audio. `redacted`
records whether identifiers were masked — the analysis stage checks it so a
transcript is never redacted twice. `meta` carries `filename` and `client_ref`
only when `privacy.store_raw_identifiers` is on.

### `data/analytics/<call_id>.json`

```json
{
  "call_id": "demo0000",
  "operator": "Dana R.",
  "direction": "incoming",
  "duration_sec": 214,
  "model": "qwen2.5:7b-instruct",
  "prompt_version": "1.0",
  "elapsed_sec": 287.3,
  "tokens_in": 2104,
  "tokens_out": 396,
  "tokens_per_sec": 5.4,
  "issues": ["overall_score derived from criteria"],
  "analysis": { "...": "see the schema below" },
  "raw_if_parse_failed": null
}
```

| Field | Meaning |
|---|---|
| `model`, `prompt_version` | what produced these scores; scores from different values are not comparable |
| `elapsed_sec`, `tokens_*` | throughput, reused by `sample` to estimate future runs |
| `issues` | what the repair layer had to fix — an empty list means the model answered cleanly |
| `analysis` | the normalized result, or `null` when the answer could not be parsed |
| `raw_if_parse_failed` | the model's unparseable text, kept for debugging |

`report` silently skips records whose `analysis` is `null`; `analyze
--retry-failed` picks them up again.

## Model response schema

What the model is asked to return, and what `analysis` contains after
normalization. Score keys come from `[[rubric.criteria]]`, so this list follows
your configuration.

| Field | Type | Notes |
|---|---|---|
| `theme` | str | constrained to `domain.themes` when that list is non-empty |
| `theme_detail` | str | one sentence |
| `language` | str | one of `domain.languages`, or `mixed` |
| `resolved` | enum | `yes` / `no` / `partial` |
| `resolution_summary` | str | |
| `scores` | object | one key per rubric criterion, clamped to the scale, `null` when the model omitted it |
| `overall_score` | float | derived from the criteria when the model omits it |
| `customer_emotion_start` | enum | `satisfied` / `neutral` / `frustrated` / `angry` |
| `customer_emotion_end` | enum | same |
| `operator_strengths` | str[] | |
| `operator_weaknesses` | str[] | |
| `uncertainty_signs` | str[] | |
| `missed_opportunities` | str[] | |
| `product_issues` | str[] | feeds the `product_issues` sheet |
| `knowledge_gaps` | str[] | feeds the `knowledge_gaps` sheet |
| `script_gaps` | str[] | feeds the `script_gaps` sheet |
| `training_recommendations` | str[] | aggregated into the `coaching` column |

The repair layer coerces `"8/10"` and `"7,5"` to numbers, clamps out-of-range
values, wraps a bare string into a list, maps an unrecognised `resolved` to
`partial`, blanks an unrecognised emotion, and records every repair in `issues`.
A criterion the model skipped stays `null` rather than being guessed.

## Configuration keys

Defaults live in [`src/call_audit/default.toml`](../src/call_audit/default.toml),
which is also the fullest documentation of each key.

### `[paths]`

| Key | Default | Meaning |
|---|---|---|
| `audio_root` | `""` | folder holding the recordings, scanned recursively |
| `data_dir` | `"data"` | parent of `index/`, `transcripts/`, `analytics/`, `reports/` |
| `model_cache` | `".models"` | where ASR weights are downloaded |

### `[audio]`

| Key | Default |
|---|---|
| `extensions` | `["mp3", "wav", "m4a", "ogg", "opus", "flac"]` |

### `[filename]`

| Key | Default | Meaning |
|---|---|---|
| `on_no_match` | `"mtime"` | `mtime` keeps unmatched files using their modification time; `skip` drops them |
| `unknown_operator` | `"unknown"` | label for calls with no operator in the name |
| `patterns` | four common schemes | array of `{ name, regex, timestamp_format }`; first match wins |

### `[privacy]`

| Key | Default | Meaning |
|---|---|---|
| `store_raw_identifiers` | `false` | `true` keeps customer numbers in cleartext in the index |
| `hash_salt_env` | `"CALL_AUDIT_SALT"` | env var holding the hashing salt |
| `redact_transcripts` | `true` | mask identifiers before storing or sending a transcript |
| `redact_in_reports` | `true` | mask identifiers in free-text report columns |

### `[sampling]`

| Key | Default | Meaning |
|---|---|---|
| `per_operator` | `50` | cap per operator |
| `min_duration_sec` | `30` | floor, filters out missed calls |
| `seed` | `42` | makes the sample reproducible |
| `operators` | `[]` | whitelist; empty means everyone |

### `[asr]`

| Key | Default | Meaning |
|---|---|---|
| `backend` | `"faster-whisper"` | the only backend today |
| `model` | `"medium"` | `tiny` … `large-v3` |
| `device` | `"cpu"` | `cpu` or `cuda` |
| `compute_type` | `"int8"` | `int8` on CPU, `float16` on GPU |
| `cpu_threads` | `8` | |
| `beam_size` | `5` | |
| `vad_filter` | `true` | drop silence before transcribing |
| `language` | `""` | empty means autodetect |

### `[llm]`

| Key | Default | Meaning |
|---|---|---|
| `backend` | `"ollama"` | `ollama` or `openai` (any OpenAI-compatible endpoint) |
| `model` | `"qwen2.5:7b-instruct"` | |
| `temperature` | `0.2` | |
| `num_ctx` | `16384` | Ollama only; must fit a long transcript |
| `max_output_tokens` | `1500` | |
| `base_url` | `""` | defaults to `http://localhost:11434` for Ollama; required for `openai` |
| `api_key_env` | `"CALL_AUDIT_API_KEY"` | env var holding the key |
| `timeout_sec` | `900` | a 7B model on CPU can take minutes per call |

### `[domain]`

| Key | Default | Meaning |
|---|---|---|
| `role` | a senior QA supervisor | the persona the model adopts |
| `business`, `business_details`, `customers` | generic B2B SaaS | what the operators support |
| `languages` | `["en"]` | more than one adds the code-switching instruction |
| `output_language` | `"en"` | language of the model's free-text findings |
| `mono_recording` | `true` | adds the "speakers are not labelled" instruction |
| `themes` | six generic themes | empty lets the model invent a label |
| `asr_hints` | `[]` | recognition errors the model must not blame on the operator |

### `[rubric]`

| Key | Default | Meaning |
|---|---|---|
| `scale_min`, `scale_max` | `1`, `10` | |
| `criteria` | six criteria | `{ key, title, description }`; drives prompt, schema and report |
| `levels` | junior / middle / senior | `{ name, max_score }`, evaluated in ascending order |

### `[report]`

| Key | Default | Meaning |
|---|---|---|
| `top_n` | `50` | rows per frequency sheet |

## The workbook

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

Every score column is generated from `[[rubric.criteria]]`, so the workbook
follows whatever criteria your configuration defines.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `paths.audio_root is not set` | Pass `--audio-root`, export `CALL_AUDIT_AUDIO_ROOT`, or set it in your config file |
| `no audio files under ...` | Wrong folder, or the extension is missing from `audio.extensions` |
| Every operator is `unknown` | No filename pattern matched. Check the `index` summary and add a pattern under `[[filename.patterns]]` |
| `sample is empty` | `--min-sec` is above every call's duration, or `sampling.operators` excludes everyone |
| `cannot reach http://localhost:11434` | Ollama is not running. Start it, then `call-audit doctor` |
| `analyze` reports `unparseable` | The model ignored the schema. Rerun with `--retry-failed`; if it persists, use a larger model or lower `llm.temperature` |
| `Permission denied` on the `.xlsx` | The workbook is open in Excel. Close it and rerun `report` |
| Transcription starts from scratch | The audio root moved, so `call_id` changed. Keep `paths.audio_root` stable — ids are derived relative to it |
