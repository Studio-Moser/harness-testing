from pathlib import Path

import pytest

from harness_testing.Claude_Agent import HarnessClaude


def _agent(tmp_path: Path, plugin_dirs=None) -> HarnessClaude:
    return HarnessClaude(
        logs_dir=tmp_path,
        model_name="anthropic/claude-sonnet-4-6",
        version="2.1.236",
        reasoning_effort="high",
        plugin_dirs=plugin_dirs,
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
