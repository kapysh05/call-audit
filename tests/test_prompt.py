"""The prompt is generated from config, so config changes must reach it."""
from call_audit.config import load, load_tree, from_tree
from call_audit.prompt import build_messages, build_system_prompt, response_schema


def test_every_rubric_criterion_reaches_the_prompt() -> None:
    cfg = load()

    system = build_system_prompt(cfg)

    for criterion in cfg.rubric.criteria:
        assert criterion.key in system


def test_custom_criterion_flows_into_prompt_and_schema(tmp_path) -> None:
    config_file = tmp_path / "my.toml"
    config_file.write_text(
        '[[rubric.criteria]]\nkey = "upsell"\ntitle = "Upsell"\n'
        'description = "Offers the right plan."\n', encoding="utf-8")
    cfg = load(config_file)

    assert cfg.rubric.keys == ("upsell",)
    assert "upsell" in build_system_prompt(cfg)
    assert "upsell" in response_schema(cfg)["scores"]


def test_themes_constrain_the_answer_when_configured() -> None:
    cfg = load()

    user = build_messages(cfg, {"operator": "x"}, "hello")[1]["content"]

    assert "Pick `theme` from exactly this list" in user
    for theme in cfg.domain.themes:
        assert theme in user


def test_without_themes_the_model_is_told_to_invent_one() -> None:
    tree = load_tree()
    tree["domain"]["themes"] = []
    cfg = from_tree(tree)

    user = build_messages(cfg, {"operator": "x"}, "hello")[1]["content"]

    assert "short theme label of your own" in user


def test_output_language_is_requested() -> None:
    tree = load_tree()
    tree["domain"]["output_language"] = "ru"

    assert "Write every free-text field in ru" in build_system_prompt(from_tree(tree))


def test_multilingual_note_only_when_several_languages() -> None:
    tree = load_tree()
    tree["domain"]["languages"] = ["ru", "kk"]

    multilingual = build_system_prompt(from_tree(tree))
    single = build_system_prompt(load())

    assert "switch language mid-call" in multilingual
    assert "switch language mid-call" not in single


def test_mono_recording_note_is_optional() -> None:
    tree = load_tree()
    tree["domain"]["mono_recording"] = False

    assert "speakers are NOT labelled" not in build_system_prompt(from_tree(tree))
    assert "speakers are NOT labelled" in build_system_prompt(load())


def test_redaction_tokens_are_explained_to_the_model() -> None:
    """Otherwise the model reads [PHONE] as a speech-recognition failure."""
    system = build_system_prompt(load())

    assert "[PHONE]" in system and "redacted" in system


def test_messages_are_a_system_and_a_user_turn() -> None:
    messages = build_messages(load(), {"operator": "Dana", "duration_sec_file": 100},
                              "hello there")

    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Dana" in messages[1]["content"]
    assert "hello there" in messages[1]["content"]
