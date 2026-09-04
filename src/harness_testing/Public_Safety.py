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
_LOCAL_PATH = re.compile(r"(?:file://|/Users/|/home/|[A-Za-z]:\\Users\\)")
_SECRET_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|"
    r"secret)\s*[:=]|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}"
)


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
    elif isinstance(value, str) and (
        _LOCAL_PATH.search(value) or _SECRET_VALUE.search(value)
    ):
        errors.append(f"sensitive or local-only string: {path}")
    return tuple(errors)
