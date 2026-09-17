"""Command line interface.

    call-audit doctor                 check the environment before a long run
    call-audit index [SUBDIR]         scan recordings into an index
    call-audit sample                 pick a stratified subset to process
    call-audit transcribe SAMPLE      speech to text
    call-audit analyze                score transcripts with the LLM
    call-audit report                 build the Excel workbook
    call-audit run [SUBDIR]           all of the above, in order
    call-audit show-prompt            print the prompt your config produces
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request

from . import analyze as analyze_stage
from . import index as index_stage
from . import report as report_stage
from . import sample as sample_stage
from . import transcribe as transcribe_stage
from .config import Config, load
from .prompt import build_system_prompt, build_user_prompt

DEFAULT_INDEX_NAME = "calls.parquet"
DEFAULT_SAMPLE_NAME = "sample.parquet"
DEFAULT_REPORT_NAME = "report.xlsx"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="call-audit",
        description="Local call-centre quality analytics: ASR + LLM -> Excel.",
    )
    parser.add_argument("--config", help="path to a TOML config file")
    parser.add_argument("--audio-root", help="override paths.audio_root")
    parser.add_argument("--data-dir", help="override paths.data_dir")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check dependencies, paths and the LLM endpoint")

    p_index = sub.add_parser("index", help="scan recordings into an index")
    p_index.add_argument("subdir", nargs="?", help="sub-folder of the audio root")
    p_index.add_argument("--out", default=DEFAULT_INDEX_NAME)

    p_sample = sub.add_parser("sample", help="pick a stratified subset")
    p_sample.add_argument("--source", default=DEFAULT_INDEX_NAME)
    p_sample.add_argument("--out", default=DEFAULT_SAMPLE_NAME)
    p_sample.add_argument("--per-op", type=int, help="max calls per operator")
    p_sample.add_argument("--min-sec", type=float, help="minimum call duration")

    p_tr = sub.add_parser("transcribe", help="speech to text")
    p_tr.add_argument("sample", nargs="?", default=DEFAULT_SAMPLE_NAME)

    p_an = sub.add_parser("analyze", help="score transcripts with the LLM")
    p_an.add_argument("--only", help="a single call_id")
    p_an.add_argument("--limit", type=int, help="stop after N calls")
    p_an.add_argument("--retry-failed", action="store_true",
                      help="re-run calls whose previous answer was unparseable")

    p_rep = sub.add_parser("report", help="build the Excel workbook")
    p_rep.add_argument("--out", default=DEFAULT_REPORT_NAME)

    p_run = sub.add_parser("run", help="index -> sample -> transcribe -> analyze -> report")
    p_run.add_argument("subdir", nargs="?")
    p_run.add_argument("--per-op", type=int)
    p_run.add_argument("--min-sec", type=float)
    p_run.add_argument("--out", default=DEFAULT_REPORT_NAME)
    p_run.add_argument("--yes", action="store_true",
                       help="do not ask for confirmation before the long stages")

    p_prompt = sub.add_parser("show-prompt", help="print the generated prompt")
    p_prompt.add_argument("--with-example", action="store_true",
                          help="also render the user turn on a dummy transcript")
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    if args.audio_root:
        os.environ["CALL_AUDIT_AUDIO_ROOT"] = args.audio_root
    if args.data_dir:
        os.environ["CALL_AUDIT_DATA_DIR"] = args.data_dir
    return load(args.config)


def cmd_doctor(cfg: Config) -> int:
    ok = True
    print("dependencies:")
    for module, needed_for in (("pandas", "index/report"), ("pyarrow", "index"),
                               ("openpyxl", "report"), ("mutagen", "index"),
                               ("tqdm", "progress"), ("faster_whisper", "transcribe")):
        try:
            __import__(module)
            print(f"  ok   {module:<16} ({needed_for})")
        except ImportError:
            ok = ok and module == "faster_whisper"
            print(f"  MISS {module:<16} ({needed_for})")

    print("\npaths:")
    root = cfg.paths.audio_root
    print(f"  audio_root: {root or '(not set)'}"
          f"{'' if root and root.exists() else '  <- missing'}")
    print(f"  data_dir:   {cfg.paths.data_dir.resolve()}")

    print("\nllm:")
    print(f"  backend: {cfg.llm.backend}  model: {cfg.llm.model}")
    if cfg.llm.backend == "ollama":
        base = (cfg.llm.base_url or "http://localhost:11434").rstrip("/")
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as response:
                body = response.read().decode("utf-8")
            installed = cfg.llm.model.split(":")[0] in body
            print(f"  ok   server reachable at {base}")
            print(f"  {'ok  ' if installed else 'WARN'} model "
                  f"{'found' if installed else 'not pulled: run ollama pull ' + cfg.llm.model}")
            ok = ok and installed
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            ok = False
            print(f"  FAIL cannot reach {base}: {exc}")

    print("\nprivacy:")
    print(f"  transcripts redacted: {cfg.privacy.redact_transcripts}")
    print(f"  raw identifiers kept: {cfg.privacy.store_raw_identifiers}")
    if not os.environ.get(cfg.privacy.hash_salt_env):
        print(f"  WARN {cfg.privacy.hash_salt_env} is not set — customer hashes "
              "are guessable by brute force")
    print("\n" + ("all good" if ok else "issues above need attention"))
    return 0 if ok else 1


def cmd_index(cfg: Config, subdir: str | None, out: str) -> int:
    df = index_stage.build_index(cfg, subdir)
    path = index_stage.save_index(cfg, df, out)
    print(index_stage.summarize(df))
    print(f"\nsaved -> {path}")
    return 0


def cmd_sample(cfg: Config, source: str, out: str,
               per_op: int | None, min_sec: float | None) -> int:
    import pandas as pd  # local: keeps `doctor` usable when pandas is missing

    df = pd.read_parquet(cfg.paths.index_dir / source)
    sample = sample_stage.stratified_sample(
        df,
        per_operator=per_op or cfg.sampling.per_operator,
        min_duration_sec=min_sec if min_sec is not None else cfg.sampling.min_duration_sec,
        seed=cfg.sampling.seed,
        operators=cfg.sampling.operators,
    )
    if sample.empty:
        print(sample_stage.summarize(sample))
        return 1
    path = sample_stage.save_sample(cfg, sample, out)
    print(sample_stage.summarize(sample))
    print()
    print(sample_stage.estimate(cfg, sample).render())
    print(f"\nsaved -> {path}")
    return 0


def cmd_show_prompt(cfg: Config, with_example: bool) -> int:
    print("=== system ===")
    print(build_system_prompt(cfg))
    if with_example:
        meta = {"operator": "A. Operator", "direction": "incoming",
                "duration_sec_file": 214, "language": "en", "language_prob": 0.98}
        print("\n=== user ===")
        print(build_user_prompt(cfg, meta,
                                "Hello, support desk. — Hi, I cannot log in ..."))
    return 0


def cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    code = cmd_index(cfg, args.subdir, DEFAULT_INDEX_NAME)
    if code:
        return code
    print("\n" + "-" * 60 + "\n")
    code = cmd_sample(cfg, DEFAULT_INDEX_NAME, DEFAULT_SAMPLE_NAME,
                      args.per_op, args.min_sec)
    if code:
        return code

    if not args.yes and sys.stdin.isatty():
        answer = input("\ntranscription and analysis take hours. continue? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("stopped. the sample is saved; resume with `call-audit transcribe`.")
            return 0

    print("\n" + "-" * 60 + "\n")
    transcribe_stage.run(cfg, DEFAULT_SAMPLE_NAME)
    print("\n" + "-" * 60 + "\n")
    analyze_stage.run(cfg)
    print("\n" + "-" * 60 + "\n")
    print(f"report -> {report_stage.build(cfg, args.out)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = _config_from_args(args)

    if args.command == "doctor":
        return cmd_doctor(cfg)
    if args.command == "index":
        return cmd_index(cfg, args.subdir, args.out)
    if args.command == "sample":
        return cmd_sample(cfg, args.source, args.out, args.per_op, args.min_sec)
    if args.command == "transcribe":
        counters = transcribe_stage.run(cfg, args.sample)
        print(counters)
        return 0
    if args.command == "analyze":
        counters = analyze_stage.run(cfg, only=args.only, limit=args.limit,
                                     retry_failed=args.retry_failed)
        print(counters)
        return 0
    if args.command == "report":
        print(f"report -> {report_stage.build(cfg, args.out)}")
        return 0
    if args.command == "run":
        return cmd_run(cfg, args)
    if args.command == "show-prompt":
        return cmd_show_prompt(cfg, args.with_example)
    return 1


def entrypoint() -> None:  # pragma: no cover - thin wrapper for the console script
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted — finished work is cached, rerun to resume")
        raise SystemExit(130)


if __name__ == "__main__":  # pragma: no cover
    entrypoint()
