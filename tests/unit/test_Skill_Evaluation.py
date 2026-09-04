import json
from pathlib import Path

import pytest

from harness_testing.Skill_Evaluation import (
    SkillEvaluation,
    explicit_instruction,
    observe_skill_invocation,
    write_skill_evaluation_report,
)


@pytest.mark.parametrize(
    ("provider", "expected"),
    (
        ("claude", "/harness:execute Build the requested change."),
        ("codex", "$harness:execute Build the requested change."),
    ),
)
def test_explicit_instruction_uses_provider_native_syntax(
    provider: str, expected: str
):
    assert (
        explicit_instruction(provider, "harness:execute", "Build the requested change.")
        == expected
    )


@pytest.mark.parametrize(
    "name",
    ("", "Harness:execute", "harness/execute", "harness:execute:again", "-bad"),
)
def test_skill_evaluation_rejects_noncanonical_names(name: str):
    with pytest.raises(ValueError, match="skill name"):
        SkillEvaluation(mode="capability", name=name)


def test_skill_evaluation_round_trips_manifest_state():
    evaluation = SkillEvaluation(mode="discovery", name="harness:execute")

    assert SkillEvaluation.from_document(evaluation.to_dict()) == evaluation
    assert SkillEvaluation.from_document(None) is None


def _trajectory(function_name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "ATIF-v1.7",
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "message": "",
                "tool_calls": [
                    {
                        "tool_call_id": "call-1",
                        "function_name": function_name,
                        "arguments": arguments,
                    }
                ],
            }
        ],
    }


def test_claude_discovery_counts_only_an_exact_skill_call():
    selected = _trajectory("Skill", {"skill": "harness:execute"})
    mentioned = _trajectory("Bash", {"command": "echo harness:execute"})

    assert observe_skill_invocation("claude", "harness:execute", selected) is True
    assert observe_skill_invocation("claude", "harness:execute", mentioned) is False


def test_codex_discovery_counts_a_pinned_plugin_skill_read_only():
    selected = _trajectory(
        "shell",
        {
            "cmd": (
                "sed -n '1,220p' /tmp/codex-home/plugins/cache/"
                "studio-moser/harness/0.8.7/skills/execute/SKILL.md"
            )
        },
    )
    unpinned = _trajectory(
        "shell",
        {"cmd": "sed -n '1,220p' /tmp/skills/execute/SKILL.md"},
    )
    mentioned = _trajectory("shell", {"cmd": "echo harness:execute"})

    assert observe_skill_invocation("codex", "harness:execute", selected) is True
    assert observe_skill_invocation("codex", "harness:execute", unpinned) is False
    assert observe_skill_invocation("codex", "harness:execute", mentioned) is False


def test_skill_report_contains_only_safe_trial_observations(tmp_path: Path):
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(
        json.dumps(_trajectory("Skill", {"skill": "harness:execute"})) + "\n"
    )
    output = tmp_path / "Skill_Evaluation.json"

    report = write_skill_evaluation_report(
        output,
        manifest_digest=f"sha256:{'a' * 64}",
        evaluation=SkillEvaluation("discovery", "harness:execute"),
        trials=(
            {
                "provider": "claude",
                "cell": "claude-A2-candidate",
                "task": "missing-rubric",
                "attempt": 1,
                "trajectory": trajectory,
            },
        ),
    )

    assert report["aggregate"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert report["trials"] == [
        {
            "provider": "claude",
            "cell": "claude-A2-candidate",
            "task": "missing-rubric",
            "attempt": 1,
            "invocation": "implicit",
        }
    ]
    serialized = output.read_text()
    assert "trajectory" not in serialized
    assert str(tmp_path) not in serialized


def test_capability_report_classifies_explicit_without_inspecting_trajectory(
    tmp_path: Path,
):
    output = tmp_path / "Skill_Evaluation.json"

    report = write_skill_evaluation_report(
        output,
        manifest_digest=f"sha256:{'b' * 64}",
        evaluation=SkillEvaluation("capability", "harness:execute"),
        trials=(
            {
                "provider": "codex",
                "cell": "codex-A2-candidate",
                "task": "missing-rubric",
                "attempt": 1,
                "trajectory": tmp_path / "missing.json",
            },
        ),
    )

    assert report["aggregate"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert report["trials"][0]["invocation"] == "explicit"
