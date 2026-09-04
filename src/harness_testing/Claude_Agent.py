"""Harbor Claude Code adapter for session-local plugin directories."""

from __future__ import annotations

import os
import shlex
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, override

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from harness_testing.Skill_Evaluation import explicit_instruction, validate_skill_name

_OAUTH_TOKEN_PATH = PurePosixPath("/tmp/Harness_Claude_OAuth_Token")


class HarnessClaude(ClaudeCode):
    """Claude Code with Harbor 0.22.0's missing session-local plugin flags."""

    # ponytail: direct trials only; restore ACP after its pre-run bridge path
    # gains the same secret-safe file handoff.
    SUPPORTED_BRIDGES = frozenset()

    def __init__(
        self,
        *args: Any,
        plugin_dirs: list[str] | None = None,
        skill_invocation: str | None = None,
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
        self._skill_invocation = (
            validate_skill_name(skill_invocation)
            if skill_invocation is not None
            else None
        )
        self._oauth_token_path: PurePosixPath | None = None
        super().__init__(*args, **kwargs)

    @property
    @override
    def extra_env(self) -> dict[str, str]:
        env = super().extra_env
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        return env

    @override
    def _resolve_auth_env(self) -> dict[str, str]:
        env = super()._resolve_auth_env()
        if self._oauth_token_path is not None:
            env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        return env

    async def _stage_oauth_token(
        self, token: str, environment: BaseEnvironment
    ) -> None:
        descriptor, source_name = tempfile.mkstemp(prefix="Harness_Claude_OAuth_")
        source = Path(source_name)
        try:
            with os.fdopen(descriptor, "w") as token_file:
                token_file.write(token)
            await environment.upload_file(source, _OAUTH_TOKEN_PATH.as_posix())
        finally:
            source.unlink(missing_ok=True)

        target = shlex.quote(_OAUTH_TOKEN_PATH.as_posix())
        commands = []
        if environment.default_user is not None:
            commands.append(f"chown {shlex.quote(str(environment.default_user))} {target}")
        commands.append(f"chmod 600 {target}")
        result = await environment.exec(" && ".join(commands), user="root")
        if result.return_code != 0:
            raise RuntimeError("Claude OAuth credential staging failed")

    async def _remove_oauth_token(self, environment: BaseEnvironment) -> None:
        target = shlex.quote(_OAUTH_TOKEN_PATH.as_posix())
        result = await environment.exec(f"rm -f -- {target}", user="root")
        if result.return_code != 0:
            raise RuntimeError("Claude OAuth credential cleanup failed")

    @override
    async def exec_as_agent(
        self,
        environment: BaseEnvironment,
        command: str,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_sec: int | None = None,
    ) -> Any:
        # ponytail: Harbor 0.22.0 command marker; delete this bridge when its
        # Docker environment can pass secret values without placing them in argv.
        if (
            self._oauth_token_path is not None
            and "claude --verbose --output-format=stream-json" in command
        ):
            target = shlex.quote(self._oauth_token_path.as_posix())
            command = (
                f'CLAUDE_CODE_OAUTH_TOKEN="$(cat -- {target})" && '
                f"rm -f -- {target} && export CLAUDE_CODE_OAUTH_TOKEN && {command}"
            )
        return await super().exec_as_agent(
            environment,
            command,
            env=env,
            cwd=cwd,
            timeout_sec=timeout_sec,
        )

    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        if self._skill_invocation is not None:
            instruction = explicit_instruction(
                "claude", self._skill_invocation, instruction
            )
        token = (self._get_env("CLAUDE_CODE_OAUTH_TOKEN") or "").strip()
        if not token:
            await super().run(instruction, environment, context)
            return

        self._oauth_token_path = _OAUTH_TOKEN_PATH
        try:
            await self._stage_oauth_token(token, environment)
            await super().run(instruction, environment, context)
        finally:
            self._oauth_token_path = None
            await self._remove_oauth_token(environment)

    @override
    def build_cli_flags(self) -> str:
        parts = [super().build_cli_flags()]
        parts.extend(
            f"--plugin-dir {shlex.quote(path.as_posix())}"
            for path in self._plugin_dirs
        )
        return " ".join(part for part in parts if part)
