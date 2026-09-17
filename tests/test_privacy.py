from call_audit.privacy import (
    call_id,
    mask_tail,
    pseudonymize,
    redact,
)


def test_redacts_email_phone_and_long_ids() -> None:
    text = ("write to john.doe@example.com or call +7 701 123 45 67, "
            "contract 4400123456789012")

    cleaned = redact(text)

    assert "john.doe@example.com" not in cleaned
    assert "701" not in cleaned
    assert "4400123456789012" not in cleaned
    assert "[EMAIL]" in cleaned and "[PHONE]" in cleaned and "[ID]" in cleaned


def test_redaction_keeps_ordinary_numbers() -> None:
    """Small numbers carry meaning for the analyst and must survive."""
    text = "the invoice grew by 20% in 2026 after adding 2 seats"

    assert redact(text) == text


def test_redaction_is_idempotent() -> None:
    once = redact("call +7 701 123 45 67 now")

    assert redact(once) == once


def test_call_id_is_stable_relative_to_the_root() -> None:
    """The same recording keeps its id when the corpus moves machines."""
    left = call_id(r"C:\records\2026-04\call.mp3", r"C:\records")
    right = call_id("/mnt/archive/2026-04/call.mp3", "/mnt/archive")

    assert left == right
    assert len(left) == 16


def test_call_id_differs_per_file() -> None:
    root = "/records"

    assert call_id("/records/a.mp3", root) != call_id("/records/b.mp3", root)


def test_pseudonymize_is_deterministic_per_salt() -> None:
    assert pseudonymize("77011234567", "s1") == pseudonymize("77011234567", "s1")
    assert pseudonymize("77011234567", "s1") != pseudonymize("77011234567", "s2")
    assert pseudonymize("77011234567", "s1") != "77011234567"


def test_pseudonymize_passes_through_empty_values() -> None:
    assert pseudonymize(None) is None
    assert pseudonymize("") is None


def test_mask_tail() -> None:
    assert mask_tail("77011234567") == "*******4567"
    assert mask_tail("12") == "**"
    assert mask_tail(None) is None
