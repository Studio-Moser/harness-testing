from pathlib import Path

import pytest
from harbor.models.agent.context import AgentContext

from harness_testing.Config import load_trajectory
from harness_testing.Metrics import classify_command, load_metric_policy, trajectory_metrics

REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURES = REPOSITORY_ROOT / "tests" / "Fixtures" / "ATIF"
POLICY = REPOSITORY_ROOT / "policy" / "Command_Classification.toml"
ENVELOPES = REPOSITORY_ROOT / "policy" / "Verification_Envelopes.toml"


@pytest.fixture
def grouped_policy():
    return load_metric_policy(POLICY, ENVELOPES, "grouped")


@pytest.mark.parametrize(
    ("command", "scope"),
    [
        ("npm run check:accent", "direct_check"),
        ("npx vitest run src/App.test.tsx", "targeted_test"),
        ("npm --workspace dashboard test", "package_test"),
        ("npm test", "comprehensive_test"),
        ("npm run gate", "comprehensive_test"),
        ("npm run lint", "lint"),
        ("npx tsc --noEmit", "typecheck"),
        ("npm run build", "build"),
        ("npx playwright test", "browser"),
        ("cargo fmt --check", "format"),
        (
            "cargo test --offline --locked quoted_value_preserves_embedded_equals",
            "targeted_test",
        ),
        ("cargo test --locked -p config_line --offline", "package_test"),
        ("cargo test --offline --workspace --locked", "comprehensive_test"),
        ("mystery-tool --all", "unknown"),
    ],
)
def test_classifies_supported_command_scopes(grouped_policy, command: str, scope: str):
    assert classify_command(command, grouped_policy).scope == scope


def test_compound_commands_keep_components_and_take_the_widest_scope(grouped_policy):
    classification = classify_command(
        "cd web && npm run lint; npm test",
        grouped_policy,
    )

    assert classification.scope == "comprehensive_test"
    assert [component.scope for component in classification.components] == [
        "unknown",
        "lint",
        "comprehensive_test",
    ]


def test_extracts_claude_and_codex_tools_and_exit_status(grouped_policy):
    claude = trajectory_metrics(load_trajectory(FIXTURES / "Valid_Claude.json"), grouped_policy)
    codex = trajectory_metrics(load_trajectory(FIXTURES / "Valid_Codex.json"), grouped_policy)

    assert claude.command_records[0].tool_name == "Bash"
    assert claude.command_records[0].success is True
    assert codex.command_records[0].tool_name == "shell"
    assert codex.command_records[0].success is True
    assert claude.metrics["files_changed"] == 2
    assert codex.metrics["files_changed"] == 1


def test_reads_available_atif_and_agent_context_telemetry(grouped_policy):
    trajectory = load_trajectory(FIXTURES / "Valid_Claude.json")
    atif = trajectory_metrics(trajectory, grouped_policy)
    context = trajectory_metrics(
        trajectory,
        grouped_policy,
        agent_context=AgentContext(
            n_input_tokens=500,
            n_output_tokens=80,
            n_cache_tokens=125,
            cost_usd=0.02,
            metadata={"reasoning_tokens": 40, "agent_seconds": 12.5},
        ),
        verifier_seconds=1.25,
    )

    assert atif.metrics["prompt_tokens"] == 120
    assert atif.metrics["completion_tokens"] == 30
    assert atif.metrics["cached_tokens"] == 20
    assert atif.metrics["cost_usd"] == 0.001
    assert context.metrics["prompt_tokens"] == 500
    assert context.metrics["completion_tokens"] == 80
    assert context.metrics["reasoning_tokens"] == 40
    assert context.metrics["cached_tokens"] == 125
    assert context.metrics["cost_usd"] == 0.02
    assert context.metrics["agent_seconds"] == 12.5
    assert context.metrics["verifier_seconds"] == 1.25


def test_grouped_premature_fixture_reports_one_premature_suite(grouped_policy):
    report = trajectory_metrics(
        load_trajectory(FIXTURES / "Grouped_Premature.json"), grouped_policy
    )

    assert report.metrics["comprehensive_tests"] == 1
    assert report.metrics["targeted_tests"] == 1
    assert report.metrics["premature_comprehensive_tests"] == 1
    assert report.metrics["files_changed"] == 1


def test_failed_comprehensive_run_before_a_fix_is_diagnostic(grouped_policy):
    report = trajectory_metrics(
        load_trajectory(FIXTURES / "Grouped_Diagnostic_Failure.json"), grouped_policy
    )

    assert report.metrics["comprehensive_tests"] == 2
    assert report.metrics["premature_comprehensive_tests"] == 0
    assert report.metrics["files_changed"] == 2


def test_unknown_mutation_keeps_dependent_churn_metrics_null(grouped_policy):
    report = trajectory_metrics(
        load_trajectory(FIXTURES / "Unknown_Mutation.json"), grouped_policy
    )

    assert report.metrics["files_changed"] is None
    assert report.metrics["premature_comprehensive_tests"] is None
    assert report.metrics["duplicate_successful_commands"] is None


def test_compound_gate_then_late_mutation_is_premature(grouped_policy):
    report = trajectory_metrics(
        load_trajectory(FIXTURES / "Compound_Late_Mutation.json"), grouped_policy
    )

    assert report.metrics["premature_comprehensive_tests"] == 1


def test_duplicate_successful_normalized_command_is_counted(grouped_policy):
    report = trajectory_metrics(
        load_trajectory(FIXTURES / "Duplicate_Success.json"), grouped_policy
    )

    assert report.metrics["targeted_tests"] == 2
    assert report.metrics["duplicate_successful_commands"] == 1


def test_missing_provider_telemetry_stays_null(grouped_policy):
    report = trajectory_metrics(load_trajectory(FIXTURES / "Valid_Codex.json"), grouped_policy)

    assert report.metrics["prompt_tokens"] is None
    assert report.metrics["completion_tokens"] is None
    assert report.metrics["reasoning_tokens"] is None
    assert report.metrics["cached_tokens"] is None
    assert report.metrics["cost_usd"] is None
    assert report.metrics["agent_seconds"] is None
    assert report.metrics["verifier_seconds"] is None
    assert report.classifier_schema == "1"
    assert report.task_policy_digest.startswith("sha256:")
