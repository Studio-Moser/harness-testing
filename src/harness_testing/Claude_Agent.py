"""Harbor Claude Code adapter for session-local plugin directories."""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath
from typing import Any, override

from harbor.agents.installed.claude_code import ClaudeCode


class HarnessClaude(ClaudeCode):
    """Claude Code with Harbor 0.22.0's missing session-local plugin flags."""

    def __init__(
        self,
        *args: Any,
        plugin_dirs: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        values = [] if plugin_dirs is None else plugin_dirs
        if not isinstance(values, list) or len(values) > 2:
            raise ValueError("plugin_dirs must contain zero to two paths")
        paths = tuple(PurePosixPath(value) for value in values if isinstance(value, str))
        root = PurePosixPath("/harness-arm/claude/plugins")
        if (
            len(paths) != len(values)
            or len(set(paths)) != len(paths)
            or any(path.parent != root or ".." in path.parts for path in paths)
        ):
            raise ValueError(
                "plugin_dirs must be unique direct children of "
                "/harness-arm/claude/plugins"
            )
        self._plugin_dirs = paths
        super().__init__(*args, **kwargs)

    @override
    def build_cli_flags(self) -> str:
        parts = [super().build_cli_flags()]
        parts.extend(
            f"--plugin-dir {shlex.quote(path.as_posix())}"
            for path in self._plugin_dirs
        )
        return " ".join(part for part in parts if part)
