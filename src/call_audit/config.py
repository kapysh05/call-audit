"""Configuration: TOML file + environment overrides -> typed objects.

Layering, lowest priority first:

1. ``call_audit/default.toml`` — shipped defaults, always loaded.
2. ``--config my.toml`` — only the keys you want to change.
3. environment variables — see :data:`ENV_OVERRIDES`.

Nothing about a particular company, PBX or language lives in the code; it all
comes from configuration, which is what lets the same pipeline run on a
different contact centre without touching a single module.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "default.toml"

#: Environment variable -> dotted path in the configuration tree.
ENV_OVERRIDES: dict[str, str] = {
    "CALL_AUDIT_AUDIO_ROOT": "paths.audio_root",
    "CALL_AUDIT_DATA_DIR": "paths.data_dir",
    "CALL_AUDIT_MODEL_CACHE": "paths.model_cache",
    "CALL_AUDIT_ASR_MODEL": "asr.model",
    "CALL_AUDIT_ASR_DEVICE": "asr.device",
    "CALL_AUDIT_LLM_BACKEND": "llm.backend",
    "CALL_AUDIT_LLM_MODEL": "llm.model",
    "CALL_AUDIT_LLM_BASE_URL": "llm.base_url",
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base``, returning a new dict.

    Lists are replaced wholesale, never concatenated: overriding
    ``domain.themes`` gives you *your* themes, not yours appended to ours.
    """
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _set_dotted(tree: dict[str, Any], dotted: str, value: Any) -> None:
    head, _, tail = dotted.partition(".")
    if tail:
        node = tree.setdefault(head, {})
        if isinstance(node, dict):
            _set_dotted(node, tail, value)
    else:
        tree[head] = value


@dataclass(frozen=True)
class FilenamePattern:
    name: str
    regex: str
    timestamp_format: str = ""


@dataclass(frozen=True)
class Criterion:
    key: str
    title: str
    description: str = ""


@dataclass(frozen=True)
class Level:
    name: str
    max_score: float


@dataclass(frozen=True)
class Paths:
    audio_root: Path | None
    data_dir: Path
    model_cache: Path

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def analytics_dir(self) -> Path:
        return self.data_dir / "analytics"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def ensure(self) -> None:
        for directory in (self.index_dir, self.transcripts_dir,
                          self.analytics_dir, self.reports_dir):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class FilenameRules:
    patterns: tuple[FilenamePattern, ...]
    on_no_match: str = "mtime"
    unknown_operator: str = "unknown"


@dataclass(frozen=True)
class Privacy:
    store_raw_identifiers: bool = False
    hash_salt_env: str = "CALL_AUDIT_SALT"
    redact_transcripts: bool = True
    redact_in_reports: bool = True


@dataclass(frozen=True)
class Sampling:
    per_operator: int = 50
    min_duration_sec: float = 30.0
    seed: int = 42
    operators: tuple[str, ...] = ()


@dataclass(frozen=True)
class Asr:
    backend: str = "faster-whisper"
    model: str = "medium"
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = 8
    beam_size: int = 5
    vad_filter: bool = True
    language: str = ""


@dataclass(frozen=True)
class Llm:
    backend: str = "ollama"
    model: str = "qwen2.5:7b-instruct"
    temperature: float = 0.2
    num_ctx: int = 16384
    max_output_tokens: int = 1500
    base_url: str = ""
    api_key_env: str = "CALL_AUDIT_API_KEY"
    timeout_sec: float = 900.0


@dataclass(frozen=True)
class Domain:
    role: str
    business: str
    business_details: str = ""
    customers: str = ""
    languages: tuple[str, ...] = ("en",)
    output_language: str = "en"
    mono_recording: bool = True
    themes: tuple[str, ...] = ()
    asr_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rubric:
    criteria: tuple[Criterion, ...]
    levels: tuple[Level, ...]
    scale_min: int = 1
    scale_max: int = 10

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(c.key for c in self.criteria)

    def level_for(self, score: float | None) -> str:
        """Map an average score onto a seniority band."""
        if score is None:
            return "n/a"
        for level in self.levels:
            if score <= level.max_score:
                return level.name
        return self.levels[-1].name if self.levels else "n/a"


@dataclass(frozen=True)
class Config:
    paths: Paths
    filename: FilenameRules
    privacy: Privacy
    sampling: Sampling
    asr: Asr
    llm: Llm
    domain: Domain
    rubric: Rubric
    audio_extensions: tuple[str, ...] = ("mp3",)
    report_top_n: int = 50
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def load_tree(path: str | Path | None = None,
              env: dict[str, str] | None = None) -> dict[str, Any]:
    """Return the merged configuration tree (defaults + file + environment)."""
    env = os.environ if env is None else env
    with DEFAULT_CONFIG_PATH.open("rb") as fh:
        tree = tomllib.load(fh)

    if path:
        user_path = Path(path)
        if not user_path.exists():
            raise FileNotFoundError(f"config file not found: {user_path}")
        with user_path.open("rb") as fh:
            tree = deep_merge(tree, tomllib.load(fh))

    for var, dotted in ENV_OVERRIDES.items():
        value = env.get(var)
        if value:
            _set_dotted(tree, dotted, value)
    return tree


def from_tree(tree: dict[str, Any]) -> Config:
    """Build a typed :class:`Config` from a merged configuration tree."""
    paths_tree = tree.get("paths", {})
    audio_root = paths_tree.get("audio_root") or ""
    paths = Paths(
        audio_root=Path(audio_root).expanduser() if audio_root else None,
        data_dir=Path(paths_tree.get("data_dir", "data")).expanduser(),
        model_cache=Path(paths_tree.get("model_cache", ".models")).expanduser(),
    )

    fname_tree = tree.get("filename", {})
    filename = FilenameRules(
        patterns=tuple(
            FilenamePattern(
                name=item.get("name", f"pattern_{i}"),
                regex=item["regex"],
                timestamp_format=item.get("timestamp_format", ""),
            )
            for i, item in enumerate(fname_tree.get("patterns", []))
        ),
        on_no_match=fname_tree.get("on_no_match", "mtime"),
        unknown_operator=fname_tree.get("unknown_operator", "unknown"),
    )

    domain_tree = tree.get("domain", {})
    domain = Domain(
        role=domain_tree.get("role", "a senior quality supervisor"),
        business=domain_tree.get("business", "a service company"),
        business_details=domain_tree.get("business_details", ""),
        customers=domain_tree.get("customers", ""),
        languages=tuple(domain_tree.get("languages", ["en"])),
        output_language=domain_tree.get("output_language", "en"),
        mono_recording=bool(domain_tree.get("mono_recording", True)),
        themes=tuple(domain_tree.get("themes", [])),
        asr_hints=tuple(domain_tree.get("asr_hints", [])),
    )

    rubric_tree = tree.get("rubric", {})
    rubric = Rubric(
        criteria=tuple(
            Criterion(key=item["key"],
                      title=item.get("title", item["key"]),
                      description=item.get("description", ""))
            for item in rubric_tree.get("criteria", [])
        ),
        levels=tuple(sorted(
            (Level(name=item["name"], max_score=float(item["max_score"]))
             for item in rubric_tree.get("levels", [])),
            key=lambda level: level.max_score,
        )),
        scale_min=int(rubric_tree.get("scale_min", 1)),
        scale_max=int(rubric_tree.get("scale_max", 10)),
    )
    if not rubric.criteria:
        raise ValueError("config: [[rubric.criteria]] must define at least one criterion")

    sampling_tree = tree.get("sampling", {})
    asr_tree = tree.get("asr", {})
    llm_tree = tree.get("llm", {})
    privacy_tree = tree.get("privacy", {})

    return Config(
        paths=paths,
        filename=filename,
        privacy=Privacy(
            store_raw_identifiers=bool(privacy_tree.get("store_raw_identifiers", False)),
            hash_salt_env=privacy_tree.get("hash_salt_env", "CALL_AUDIT_SALT"),
            redact_transcripts=bool(privacy_tree.get("redact_transcripts", True)),
            redact_in_reports=bool(privacy_tree.get("redact_in_reports", True)),
        ),
        sampling=Sampling(
            per_operator=int(sampling_tree.get("per_operator", 50)),
            min_duration_sec=float(sampling_tree.get("min_duration_sec", 30)),
            seed=int(sampling_tree.get("seed", 42)),
            operators=tuple(sampling_tree.get("operators", [])),
        ),
        asr=Asr(
            backend=asr_tree.get("backend", "faster-whisper"),
            model=asr_tree.get("model", "medium"),
            device=asr_tree.get("device", "cpu"),
            compute_type=asr_tree.get("compute_type", "int8"),
            cpu_threads=int(asr_tree.get("cpu_threads", 8)),
            beam_size=int(asr_tree.get("beam_size", 5)),
            vad_filter=bool(asr_tree.get("vad_filter", True)),
            language=asr_tree.get("language", ""),
        ),
        llm=Llm(
            backend=llm_tree.get("backend", "ollama"),
            model=llm_tree.get("model", "qwen2.5:7b-instruct"),
            temperature=float(llm_tree.get("temperature", 0.2)),
            num_ctx=int(llm_tree.get("num_ctx", 16384)),
            max_output_tokens=int(llm_tree.get("max_output_tokens", 1500)),
            base_url=llm_tree.get("base_url", ""),
            api_key_env=llm_tree.get("api_key_env", "CALL_AUDIT_API_KEY"),
            timeout_sec=float(llm_tree.get("timeout_sec", 900)),
        ),
        domain=domain,
        rubric=rubric,
        audio_extensions=tuple(tree.get("audio", {}).get("extensions", ["mp3"])),
        report_top_n=int(tree.get("report", {}).get("top_n", 50)),
        raw=tree,
    )


def load(path: str | Path | None = None) -> Config:
    """Load defaults, an optional user file and environment overrides."""
    return from_tree(load_tree(path))
