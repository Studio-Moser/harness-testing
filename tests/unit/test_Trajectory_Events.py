from harbor.models.trajectories.observation_result import ObservationResult

from harness_testing.Trajectory_Events import (
    component_successes,
    result_success,
    shell_mutation,
    split_shell,
)


def test_result_success_reads_pinned_claude_metadata_and_bracketed_failures():
    success = ObservationResult(
        source_call_id="claude-success",
        content="[stdout]\nall checks passed",
        extra={
            "tool_result_metadata": {
                "tool_use_result": {"stdout": "all checks passed", "exitCode": 0}
            }
        },
    )
    failure = ObservationResult(
        source_call_id="claude-failure",
        content="[stderr]\nfailed\n\n[exit_code] 1",
        extra={
            "tool_result_metadata": {
                "tool_use_result": {"stderr": "failed", "exitCode": 1}
            }
        },
    )

    assert result_success(success) is True
    assert result_success(failure) is False


def test_result_success_reads_codex_tool_metadata_from_the_step():
    result = ObservationResult(
        source_call_id="codex-success",
        content="completed",
    )
    step_extra = {
        "tool_call_details": {
            "codex-success": {"metadata": {"exit_code": 0}}
        }
    }

    assert result_success(result, step_extra=step_extra, call_id="codex-success") is True


def test_compound_shell_order_and_provable_success_are_preserved():
    components = split_shell("cd /app && npm run gate && printf x >> src/App.tsx")

    assert [component.command for component in components] == [
        "cd /app",
        "npm run gate",
        "printf x >> src/App.tsx",
    ]
    assert [component.operator_before for component in components] == [None, "&&", "&&"]
    assert component_successes(components, True) == (True, True, True)


def test_declared_shell_mutations_detect_redirection_tee_and_relevant_directories():
    mutation_patterns = (
        r"(^|\s)(?:sed\s+-i|perl\s+-pi|touch|mkdir|mv|cp|rm)\s",
        r"(?:>|>>|\btee\b)\s*\S+",
    )
    relevant_path_patterns = (
        r"(^|/)(?:src|app|lib|tests|crates|packages)(?:/|$)",
        r"\.(?:css|html|jsx?|json|py|rs|toml|tsx?|ya?ml)$",
    )

    assert shell_mutation(
        "printf x >> src/App.tsx", mutation_patterns, relevant_path_patterns
    )[0] == "relevant"
    assert shell_mutation(
        "tee src/index.css", mutation_patterns, relevant_path_patterns
    )[0] == "relevant"
    assert shell_mutation(
        "rm -rf src", mutation_patterns, relevant_path_patterns
    )[0] == "relevant"
