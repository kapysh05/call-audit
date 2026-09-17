"""Identifiers and redaction.

Two jobs, both about keeping personal data out of files that are easy to
copy around:

* :func:`call_id` — a stable, opaque id for a recording, used as the filename
  for its transcript and analysis. Derived from the path *relative to* the
  audio root, so moving the corpus to another machine does not invalidate a
  20-hour transcription cache.
* :func:`redact` — masks phone numbers, e-mail addresses and long digit runs
  (card / national id numbers) before a transcript is sent to a model or
  written into a report.

Redaction is not a compliance guarantee: a transcript can still contain a name
or an address in plain prose. It removes the mechanically-extractable
identifiers — the ones that make a leaked corpus immediately actionable.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
# 9+ consecutive digits: card numbers, national ids, account numbers.
LONG_DIGITS_RE = re.compile(r"(?<!\d)\d{9,}(?!\d)")
# A phone number with separators: at least 8 digits, optional leading plus.
PHONE_RE = re.compile(r"(?<![\w\d])\+?\d(?:[\d\s().-]{6,}\d)(?![\w\d])")

EMAIL_TOKEN = "[EMAIL]"
PHONE_TOKEN = "[PHONE]"
ID_TOKEN = "[ID]"


def call_id(path: str | Path, root: str | Path | None = None,
            length: int = 16) -> str:
    """Return a stable opaque id for a recording."""
    p = Path(path)
    if root:
        try:
            p = p.relative_to(Path(root))
        except ValueError:
            p = Path(p.name)
    key = p.as_posix().lower()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:length]


def pseudonymize(value: str | None, salt: str = "", length: int = 12) -> str | None:
    """Hash a customer identifier so rows stay joinable but not identifying.

    The same phone number always maps to the same token *within one salt*,
    which is what you need to spot repeat callers, while the token is useless
    outside your environment.
    """
    if value is None or value == "":
        return None
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return digest[:length]


def salt_from_env(env_var: str = "CALL_AUDIT_SALT") -> str:
    """Read the hashing salt from the environment.

    An unset salt is allowed (hashes stay consistent locally) but it makes the
    tokens reversible by brute force for a known number space, so the CLI warns
    about it.
    """
    return os.environ.get(env_var, "")


def mask_tail(value: str | None, keep: int = 4) -> str | None:
    """Mask everything except the last ``keep`` characters, for display."""
    if not value:
        return value
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


def redact(text: str) -> str:
    """Replace e-mails, long digit runs and phone numbers with tokens."""
    if not text:
        return text
    text = EMAIL_RE.sub(EMAIL_TOKEN, text)
    text = LONG_DIGITS_RE.sub(ID_TOKEN, text)
    text = PHONE_RE.sub(PHONE_TOKEN, text)
    return text


def redact_if(text: str, enabled: bool) -> str:
    """Convenience wrapper for call sites driven by configuration."""
    return redact(text) if enabled else text
