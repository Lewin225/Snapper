"""Rules that keep tags and generated names usable as file and folder names on every platform."""
from __future__ import annotations

import re

# Characters Windows forbids in a name (the strictest common rule), plus control characters.
INVALID_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
# For QRegularExpressionValidator: accepts only text without invalid characters.
VALID_INPUT_PATTERN = r'[^\\/:*?"<>|\x00-\x1f\x7f]*'
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
MAX_TAG_LENGTH = 80
INVALID_HELP = 'Names can\'t contain  \\ / : * ? " < > |'


def has_invalid_chars(text: str) -> bool:
    return bool(INVALID_RE.search(text))


def clean_part(text: str, max_len: int = 120, replacement: str = "_") -> str:
    """One safe path component: invalid characters replaced, no leading/trailing dots or spaces, never a reserved
    device name, never empty or a dot-only name. Used for every file and folder name the export writes."""
    t = INVALID_RE.sub(replacement, text)
    t = re.sub(r"\s+", " ", t).strip(" .")
    t = t[:max_len].rstrip(" .")
    if not t:
        return "_"
    if t.split(".")[0].lower() in RESERVED:
        t = "_" + t
    return t


def clean_tag(text: str) -> str:
    """A tag name or value as the user may keep it: invalid characters removed, trimmed, length-limited.
    (Removed rather than replaced, so a value never silently turns into a different-looking one.)"""
    t = INVALID_RE.sub("", text).strip(" .")
    return t[:MAX_TAG_LENGTH].rstrip(" .")
