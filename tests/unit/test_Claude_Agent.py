import asyncio
from pathlib import Path

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
