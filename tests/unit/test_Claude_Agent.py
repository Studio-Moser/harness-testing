import asyncio
import stat
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness_testing.Claude_Agent import HarnessClaude


def _agent(tmp_path: Path, plugin_dirs=None, skill_invocation=None) -> HarnessClaude:
    return HarnessClaude(
        logs_dir=tmp_path,
        model_name="anthropic/claude-sonnet-4-6",
        version="2.1.236",
        reasoning_effort="high",
        plugin_dirs=plugin_dirs,
        skill_invocation=skill_invocation,
    )


def test_claude_adapter_appends_ordered_repeatable_plugin_dirs(tmp_path):
    agent = _agent(
        tmp_path,
        [
            "/harness-arm/claude/plugins/superpowers",
            "/harness-arm/claude/plugins/harness",
        ],
    )
    assert agent.build_cli_flags() == (
        "--effort high --permission-mode=bypassPermissions "
        "--plugin-dir /harness-arm/claude/plugins/superpowers "
        "--plugin-dir /harness-arm/claude/plugins/harness"
    )


@pytest.mark.parametrize(
    "plugin_dirs",
    [
        [123],
        ["relative/harness"],
        ["/harness-arm/claude/plugins"],
        ["/harness-arm/claude/plugins/harness/nested"],
        ["/harness-arm/claude/plugins/../harness"],
        [
            "/harness-arm/claude/plugins/harness",
            "/harness-arm/claude/plugins/harness",
        ],
        [
            "/harness-arm/claude/plugins/one",
            "/harness-arm/claude/plugins/two",
            "/harness-arm/claude/plugins/three",
        ],
    ],
)
def test_claude_adapter_rejects_untrusted_plugin_dirs(tmp_path, plugin_dirs):
    with pytest.raises(ValueError, match="plugin_dirs"):
        _agent(tmp_path, plugin_dirs)


def test_claude_adapter_accepts_only_a_canonical_skill_invocation(tmp_path: Path):
    agent = _agent(tmp_path, skill_invocation="harness:execute")

    assert agent._skill_invocation == "harness:execute"
    with pytest.raises(ValueError, match="skill name"):
        _agent(tmp_path, skill_invocation="/harness:execute")


def test_claude_adapter_disables_the_unsecured_acp_bridge(tmp_path: Path):
    assert not _agent(tmp_path).SUPPORTED_BRIDGES


def test_claude_adapter_prefixes_explicit_skill_before_base_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    instructions: list[str] = []

    async def fake_run(self, instruction, environment, context):
        del self, environment, context
        instructions.append(instruction)

    monkeypatch.setattr("harness_testing.Claude_Agent.ClaudeCode.run", fake_run)
    agent = _agent(tmp_path, skill_invocation="harness:execute")

    asyncio.run(agent.run("Original task\n", object(), object()))

    assert instructions == ["/harness:execute Original task\n"]


@pytest.mark.parametrize("agent_fails", [False, True])
def test_claude_adapter_keeps_oauth_token_out_of_exec_argv_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent_fails: bool
):
    secret = "oauth-secret-that-must-not-reach-argv"

    class RecordingEnvironment:
        default_user = None

        def __init__(self):
            self.uploads: list[tuple[str, str, int]] = []
            self.execs: list[tuple[str, dict[str, str] | None]] = []
            self.argvs: list[tuple[str, ...]] = []
            self._scoped_env: dict[str, str] = {}

        @contextmanager
        def scoped_exec_env(self, env):
            previous = self._scoped_env
            self._scoped_env = {**previous, **env}
            try:
                yield
            finally:
                self._scoped_env = previous

        async def upload_file(self, source_path, target_path):
            source = Path(source_path)
            self.uploads.append(
                (source.read_text(), target_path, stat.S_IMODE(source.stat().st_mode))
            )

        async def exec(self, command, *, env=None, **kwargs):
            del kwargs
            merged_env = {**(env or {}), **self._scoped_env} or None
            self.execs.append((command, merged_env))
            argv = ["docker", "compose", "exec"]
            for key, value in (merged_env or {}).items():
                argv.extend(("-e", f"{key}={value}"))
            argv.extend(("main", "bash", "-c", command))
            self.argvs.append(tuple(argv))
            return SimpleNamespace(return_code=0, stdout="", stderr="")

    async def fake_run(self, instruction, environment, context):
        del instruction, context
        await self.exec_as_agent(
            environment,
            command="mkdir -p /logs/agent/sessions",
            env=self._resolve_auth_env(),
        )
        await self.exec_as_agent(
            environment,
            command="claude --verbose --output-format=stream-json --print",
            env=self._resolve_auth_env(),
        )
        if agent_fails:
            raise RuntimeError("agent failed")

    monkeypatch.setattr("harness_testing.Claude_Agent.ClaudeCode.run", fake_run)
    environment = RecordingEnvironment()
    agent = HarnessClaude(
        logs_dir=tmp_path,
        model_name="anthropic/claude-sonnet-4-6",
        version="2.1.236",
        reasoning_effort="high",
        extra_env={
            "CLAUDE_CODE_OAUTH_TOKEN": secret,
            "CLAUDE_FORCE_OAUTH": "1",
        },
    )

    async def run_in_trial_scope():
        with environment.scoped_exec_env(agent.extra_env):
            await agent.run("Original task\n", environment, object())

    if agent_fails:
        with pytest.raises(RuntimeError, match="agent failed"):
            asyncio.run(run_in_trial_scope())
    else:
        asyncio.run(run_in_trial_scope())

    assert environment.uploads == [
        (secret, "/tmp/Harness_Claude_OAuth_Token", 0o600)
    ]
    assert all(secret not in command for command, _ in environment.execs)
    assert all(secret not in argument for argv in environment.argvs for argument in argv)
    assert all(
        secret not in (env or {}).values() for _, env in environment.execs
    )
    assert all(
        "CLAUDE_CODE_OAUTH_TOKEN" not in (env or {})
        for _, env in environment.execs
    )
    assert any(
        'CLAUDE_CODE_OAUTH_TOKEN="$(cat -- /tmp/Harness_Claude_OAuth_Token)"'
        in command
        and "rm -f -- /tmp/Harness_Claude_OAuth_Token" in command
        for command, _ in environment.execs
    )
    assert environment.execs[-1][0] == "rm -f -- /tmp/Harness_Claude_OAuth_Token"
