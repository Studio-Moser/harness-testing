"""Harbor Claude Code adapter for session-local plugin directories."""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, override

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from harness_testing.Native_Conversation import (
    remove_controller,
    stage_controller,
    validate_conversation,
)
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
        conversation: dict | None = None,
        **kwargs: Any,
    ) -> None:
        values = [] if plugin_dirs is None else plugin_dirs
        if not isinstance(values, list) or (conversation is None and len(values) > 2):
            raise ValueError("plugin_dirs must contain zero to two paths")
        paths = tuple(PurePosixPath(value) for value in values if isinstance(value, str))
        root = PurePosixPath("/harness-arm/claude/plugins")
        if (
            len(paths) != len(values)
            or len(set(paths)) != len(paths)
            or any(path.parent != root or ".." in path.parts for path in paths)
        ):
            raise ValueError(
                "plugin_dirs must be unique direct children of /harness-arm/claude/plugins"
            )
        self._plugin_dirs = paths
        self._skill_invocation = (
            validate_skill_name(skill_invocation) if skill_invocation is not None else None
        )
        self._conversation = conversation
        self._conversation_instruction = None
        self._oauth_token_path: PurePosixPath | None = None
        self._external_codex_home = None
        super().__init__(*args, **kwargs)

    @property
    @override
    def extra_env(self) -> dict[str, str]:
        env = super().extra_env
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        if self._conversation is not None:
            env.pop("OPENAI_API_KEY", None)
        return env

    @override
    def _resolve_auth_env(self) -> dict[str, str]:
        env = super()._resolve_auth_env()
        if self._oauth_token_path is not None:
            env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        return env

    async def _stage_oauth_token(self, token: str, environment: BaseEnvironment) -> None:
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

    async def _stage_external_codex_auth(self, environment):
        self._external_codex_home = "/tmp/Harness_External_Codex"
        home = self._external_codex_home
        result = await environment.exec(f"mkdir -p {home} && chmod 700 {home}", user="root")
        if result.return_code:
            raise RuntimeError("external_codex_credential_staging_failed")
        descriptor, temporary = tempfile.mkstemp(prefix="Harness_External_Codex_")
        source = Path(temporary)
        try:
            with os.fdopen(descriptor, "w") as handle:
                if (self._get_env("CODEX_FORCE_AUTH_JSON") or "").lower() in {"1", "true", "yes"}:
                    path = Path(
                        self._get_env("CODEX_AUTH_JSON_PATH") or Path.home() / ".codex/auth.json"
                    )
                    auth = json.loads(path.read_text())
                    if auth.get("auth_mode") != "chatgpt" or not auth.get("tokens", {}).get(
                        "access_token"
                    ):
                        raise ValueError("external_codex_subscription_credential_invalid")
                else:
                    key = self._get_env("OPENAI_API_KEY")
                    if not key:
                        raise ValueError("external_codex_api_credential_missing")
                    auth = {"OPENAI_API_KEY": key}
                json.dump(auth, handle)
            await environment.upload_file(source, home + "/auth.json")
            owner = (
                f"chown -R {shlex.quote(str(environment.default_user))} {home} && "
                if environment.default_user is not None
                else ""
            )
            result = await environment.exec(f"{owner}chmod 600 {home}/auth.json", user="root")
            if result.return_code:
                raise RuntimeError("external_codex_credential_staging_failed")
        finally:
            source.unlink(missing_ok=True)

    @override
    async def exec_as_agent(
        self,
        environment: BaseEnvironment,
        command: str,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_sec: int | None = None,
    ) -> Any:
        native_launch = "claude --verbose --output-format=stream-json" in command
        if self._conversation is not None:
            env = dict(env or {})
            if "ANTHROPIC_BASE_URL" in env:
                for key in (
                    "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                    "CLAUDE_CODE_SUBAGENT_MODEL",
                ):
                    # Harbor injects these only for proxies, forcing every route
                    # onto the kickoff model. Preserve native child selection.
                    env.pop(key, None)
            if native_launch:
                cli = [
                    "claude",
                    "--verbose",
                    "--print",
                    "--input-format",
                    "stream-json",
                    "--output-format",
                    "stream-json",
                    "--permission-prompt-tool",
                    "stdio",
                    "--forward-subagent-text",
                    "--model",
                    self._resolved_model_name(),
                ]
                cli.extend(shlex.split(self.build_cli_flags()))
                if self.config_source is not None:
                    cli.extend(["--settings", self._REMOTE_SETTINGS_PATH.as_posix()])
                config = {
                    **self._conversation,
                    "provider": "claude",
                    "command": cli,
                    "model": self._resolved_model_name(),
                    "effort": self._resolved_flags.get("reasoning_effort"),
                    "runtime_version": self._version,
                    "instruction": self._conversation_instruction,
                    "external_codex_home": self._external_codex_home,
                }
                command = 'export PATH="$HOME/.local/bin:$PATH"; ' + await stage_controller(
                    environment, config
                )
                timeout_sec = self._conversation["timeout_seconds"] + 10
                env = {
                    key: value
                    for key, value in env.items()
                    if not key.startswith("HARBOR_CLAUDE_CODE_INSTRUCTION_")
                }
        # ponytail: Harbor 0.22.0 command marker; delete when Docker supports
        # secret environment handoff without putting credential values in argv.
        if self._oauth_token_path is not None and native_launch:
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
            instruction = explicit_instruction("claude", self._skill_invocation, instruction)
        if self._conversation is not None:
            validate_conversation(self._conversation, "claude")
            if self._resume or self._load:
                raise ValueError(
                    "native_resume_requires_explicit_root: use conversation.root_session_id"
                )
            self._conversation_instruction = instruction
        token = (self._get_env("CLAUDE_CODE_OAUTH_TOKEN") or "").strip()
        if not token and self._conversation is None:
            await super().run(instruction, environment, context)
            return
        try:
            if self._conversation is not None and any(
                row["provider"] == "openai"
                for row in self._conversation.get("executor_inventory", [])
            ):
                await self._stage_external_codex_auth(environment)
            if token:
                self._oauth_token_path = _OAUTH_TOKEN_PATH
                await self._stage_oauth_token(token, environment)
            await super().run(instruction, environment, context)
        finally:
            try:
                if token:
                    self._oauth_token_path = None
                    await self._remove_oauth_token(environment)
            finally:
                try:
                    if self._external_codex_home is not None:
                        result = await environment.exec(
                            f"rm -rf -- {self._external_codex_home}", user="root"
                        )
                        if result.return_code:
                            raise RuntimeError("external_codex_credential_cleanup_failed")
                finally:
                    if self._conversation is not None:
                        await remove_controller(environment)

    @override
    def build_cli_flags(self) -> str:
        parts = [super().build_cli_flags()]
        parts.extend(f"--plugin-dir {shlex.quote(path.as_posix())}" for path in self._plugin_dirs)
        return " ".join(part for part in parts if part)
