import pytest

from call_audit.config import deep_merge, from_tree, load, load_tree


def test_deep_merge_keeps_untouched_branches() -> None:
    base = {"llm": {"model": "a", "temperature": 0.2}, "paths": {"data_dir": "data"}}

    merged = deep_merge(base, {"llm": {"model": "b"}})

    assert merged["llm"] == {"model": "b", "temperature": 0.2}
    assert merged["paths"] == {"data_dir": "data"}
    assert base["llm"]["model"] == "a", "merge must not mutate its input"


def test_deep_merge_replaces_lists_wholesale() -> None:
    """Overriding themes must give you your list, not yours plus the defaults."""
    merged = deep_merge({"domain": {"themes": ["a", "b"]}},
                        {"domain": {"themes": ["c"]}})

    assert merged["domain"]["themes"] == ["c"]


def test_user_file_overrides_defaults(tmp_path) -> None:
    config_file = tmp_path / "my.toml"
    config_file.write_text(
        '[llm]\nmodel = "my-model"\n\n[domain]\noutput_language = "ru"\n',
        encoding="utf-8")

    cfg = load(config_file)

    assert cfg.llm.model == "my-model"
    assert cfg.domain.output_language == "ru"
    assert cfg.llm.temperature == 0.2, "untouched defaults survive"
    assert len(cfg.rubric.criteria) == 6


def test_environment_beats_the_file(tmp_path) -> None:
    config_file = tmp_path / "my.toml"
    config_file.write_text('[paths]\ndata_dir = "from-file"\n', encoding="utf-8")

    tree = load_tree(config_file, env={"CALL_AUDIT_DATA_DIR": "from-env"})

    assert from_tree(tree).paths.data_dir.name == "from-env"


def test_missing_config_file_is_an_error(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope.toml")


def test_rubric_levels_are_sorted_and_applied() -> None:
    cfg = load()

    assert cfg.rubric.level_for(5.9) == "junior"
    assert cfg.rubric.level_for(6.0) == "junior"
    assert cfg.rubric.level_for(7.5) == "middle"
    assert cfg.rubric.level_for(9.0) == "senior"
    assert cfg.rubric.level_for(None) == "n/a"


def test_rubric_must_not_be_empty() -> None:
    tree = load_tree()
    tree["rubric"]["criteria"] = []

    with pytest.raises(ValueError, match="rubric.criteria"):
        from_tree(tree)


def test_paths_derive_the_data_layout(tmp_path) -> None:
    tree = load_tree(env={"CALL_AUDIT_DATA_DIR": str(tmp_path)})
    paths = from_tree(tree).paths
    paths.ensure()

    assert paths.transcripts_dir.is_dir()
    assert paths.analytics_dir.is_dir()
    assert paths.reports_dir.parent == tmp_path
