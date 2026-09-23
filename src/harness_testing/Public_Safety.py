"""Shared fail-closed checks for values crossing public result boundaries."""

from __future__ import annotations

import re
from collections.abc import Mapping

_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:api_key|access_token|refresh_token|auth_token|authorization|password|"
    r"secret|credential)(?:$|_)",
    re.IGNORECASE,
)
_PRIVATE_FIELDS = {
    "command_output",
    "env",
    "environment",
    "environment_variables",
    "extra",
    "prompt",
    "prompts",
    "reasoning",
    "reasoning_content",
    "tool_output",
    "trajectory",
    "trajectories",
}
_LOCAL_PATH = re.compile(
    r"file://|(?<![A-Za-z])[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|"
    r"(?<![\w:/])//[^\s/]|"
    r"(?<![\w:/])/(?!app(?:/|(?=$|[\s<>\"'`),;:!?]|\.(?:\s|$))))[^\s/<>\"'`]+|"
    r"/app/[^\s]*\.\."
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|"
    r"secret)\s*[:=]|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}"
)


def normalize_visible_local_paths(text: str) -> str:
    """Omit path references from visible prose, never sanitize credentials into evidence."""
    if _SECRET_VALUE.search(text):
        return text  # The unchanged secret must still fail public-boundary validation.
    text = re.sub(
        r"!?\[([^\]\n]*)\]\(([^)\n]+)\)",
        lambda match: (
            match[1] + " [local link omitted]" if _LOCAL_PATH.search(match[2]) else match[0]
        ),
        text,
    )
    # Quoted paths may contain spaces; consume the entire reference, not just its prefix.
    text = re.sub(
        r"(?<!\w)(?P<quote>[`\"'])(?P<path>[^\n]*?)(?P=quote)",
        lambda match: (
            match["quote"] + "[local path omitted]" + match["quote"]
            if _LOCAL_PATH.match(match["path"])
            else match[0]
        ),
        text,
    )

    def omit_token(match: re.Match) -> str:
        token = match[0]
        if not _LOCAL_PATH.search(token):
            return token
        path = token.rstrip(".,;:!?")
        return "[local path omitted]" + token[len(path) :]

    return re.sub(r"[^\s<>\"'`()\[\]]+", omit_token, text)


def public_safety_errors(value: object, path: str = "$") -> tuple[str, ...]:
    """Return stable public-boundary errors without mutating or filtering input."""

    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = re.sub(r"[^a-zA-Z0-9]+", "_", str(key)).strip("_").lower()
            child_path = f"{path}.{key}"
            if normalized in _PRIVATE_FIELDS or _SENSITIVE_KEY.search(normalized):
                errors.append(f"forbidden public field: {child_path}")
            errors.extend(public_safety_errors(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(public_safety_errors(child, f"{path}[{index}]"))
    elif isinstance(value, str) and (_LOCAL_PATH.search(value) or _SECRET_VALUE.search(value)):
        errors.append(f"sensitive or local-only string: {path}")
    return tuple(errors)
