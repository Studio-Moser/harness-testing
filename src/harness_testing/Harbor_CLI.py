"""Build Harbor commands through the active Python environment."""

from __future__ import annotations

import sys


def harbor_command(*arguments: str) -> tuple[str, ...]:
    return (sys.executable, "-m", "harbor.cli.main", *arguments)
