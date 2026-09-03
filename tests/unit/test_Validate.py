import copy
import json
import shutil
from pathlib import Path

from test_Config import VALID_TASK

import harness_testing.Validate as Validate
from harness_testing.CLI import main
from harness_testing.Results import compatibility_key, public_result_id
from harness_testing.Validate import (
    affected_validation_commands,
    find_sensitive_keys,
    validate_markdown_links,
    validate_public_results,
    validate_repository,
    validate_task_paths,
    validate_versions_file,
    validate_workflow_files,
)

REPOSITORY_ROOT = Path(__file__).parents[2]


def _write_task(root: Path, directory_name: str, package_name: str) -> Path:
    task_directory = root / directory_name
    task_directory.mkdir(parents=True)
    task_path = task_directory / "task.toml"
    task_path.write_text(VALID_TASK.replace("studio-moser/sample-task", package_name))
    return task_path


def test_task_validation_reports_duplicate_package_ids(tmp_path):
    first = _write_task(tmp_path, "first", "studio-moser/duplicate")
    second = _write_task(tmp_path, "second", "studio-moser/duplicate")

    failures = validate_task_paths([first, second], expected_schema="1.4")

    assert any("duplicate task package" in failure.message for failure in failures)


def test_version_validation_rejects_unpinned_git_source(tmp_path):
    versions_path = tmp_path / "Versions.toml"
    versions_path.write_text(
        '''
[repository]
schema_version = "0.1.0"

[[sources]]
name = "Mutable"
url = "https://github.com/example/mutable.git"
version = "1.0.0"
'''
    )

    failures = validate_versions_file(versions_path)

    assert any("full 40-character commit" in failure.message for failure in failures)
    assert any("image_version" in failure.message for failure in failures)


def test_sensitive_key_scan_rejects_credentials_without_rejecting_metrics():
    sensitive = {
        "agents": [{"env": {"ANTHROPIC_API_KEY": "secret-value"}}],
        "prompt_tokens": 120,
    }

    assert find_sensitive_keys(sensitive) == ("agents[0].env.ANTHROPIC_API_KEY",)


def test_task_validation_requires_separate_no_network_verifier(tmp_path):
    shared = _write_task(tmp_path, "shared", "studio-moser/shared").read_text()
    shared_path = tmp_path / "shared" / "task.toml"
    shared_path.write_text(
        shared.replace('environment_mode = "separate"', 'environment_mode = "shared"')
    )
    public = _write_task(tmp_path, "public", "studio-moser/public").read_text()
    public_path = tmp_path / "public" / "task.toml"
    public_path.write_text(
        public.replace(
            '[verifier]\nenvironment_mode = "separate"\nnetwork_mode = "no-network"',
            '[verifier]\nenvironment_mode = "separate"\nnetwork_mode = "public"',
        )
    )

    failures = validate_task_paths([shared_path, public_path], expected_schema="1.4")

    messages = [failure.message for failure in failures]
    assert any("separate verifier" in message for message in messages)
    assert any("verifier network_mode must be no-network" in message for message in messages)


def test_repository_static_validation_is_deterministic(capsys):
    assert validate_repository(REPOSITORY_ROOT) == ()

    assert main(["validate", "--static-only"]) == 0
    assert capsys.readouterr().out == "Static validation passed.\n"


def test_contract_expectation_validation_reports_public_schema_errors(tmp_path):
    source = REPOSITORY_ROOT / "tasks/contract/missing-required-executor"
    task_root = tmp_path / source.name
    shutil.copytree(source, task_root)
    expected_path = task_root / "tests/Expected.json"
    expected = json.loads(expected_path.read_text())
    expected["result"]["route"]["actual_model"] = ""
    expected_path.write_text(json.dumps(expected))

    failures = Validate._validate_benchmark_task_assets(
        task_root / "task.toml",
        Validate.load_task(task_root / "task.toml", expected_schema="1.4"),
    )

    assert any(
        failure.message
        == "invalid contract expectation: HarnessResult /route/actual_model: anyOf"
        for failure in failures
    )


def test_contract_scenario_rejects_reserved_public_schema_key(tmp_path):
    source = REPOSITORY_ROOT / "tasks/contract/missing-required-executor"
    task_root = tmp_path / source.name
    shutil.copytree(source, task_root)
    scenario_path = task_root / "environment/stub-server/Scenario.json"
    scenario = json.loads(scenario_path.read_text())
    scenario["contract"]["harness_result_schema"] = {}
    scenario_path.write_text(json.dumps(scenario))

    failures = Validate._validate_benchmark_task_assets(
        task_root / "task.toml",
        Validate.load_task(task_root / "task.toml", expected_schema="1.4"),
    )

    assert any(
        "invalid contract scenario: scenario contract reserves harness_result_schema"
        in failure.message
        for failure in failures
    )


def test_version_ledger_pins_the_python_mcp_sdk_used_by_computer_use():
    text = (REPOSITORY_ROOT / "Versions.toml").read_text()

    assert 'name = "mcp"\necosystem = "pypi"\nversion = "2.1.1"' in text


def test_version_validation_rejects_an_unpinned_deepswe_image(tmp_path):
    versions_path = tmp_path / "Versions.toml"
    versions_path.write_text(
        (REPOSITORY_ROOT / "Versions.toml")
        .read_text()
        .replace(
            "sha256:930ec9d5c14868da048c6cdd96a06dc394ec09b0b7b12a2cad2e63476a59c3e6",
            "mutable",
        )
    )

    failures = validate_versions_file(versions_path)

    assert any("invalid DeepSWE capability pin" in failure.message for failure in failures)


def test_public_result_validation_accepts_only_finalized_schema_valid_results(tmp_path):
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy" / "Public_Result.schema.json").write_bytes(
        (REPOSITORY_ROOT / "policy" / "Public_Result.schema.json").read_bytes()
    )
    results = tmp_path / "results"
    results.mkdir()
    valid = json.loads(
        (
            REPOSITORY_ROOT
            / "tests"
            / "Fixtures"
            / "Public_Results"
            / "Valid.json"
        ).read_text()
    )
    (results / "Valid.json").write_text(json.dumps(valid))

    assert validate_public_results(tmp_path) == ()

    partial = copy.deepcopy(valid)
    partial["run"]["finalized"] = False
    partial["review"]["partial"] = True
    partial["compatibility"]["key"] = compatibility_key(partial)
    partial["result_id"] = public_result_id(partial)
    (results / "Partial.json").write_text(json.dumps(partial))

    failures = validate_public_results(tmp_path)
    assert any("public results must be finalized" in failure.message for failure in failures)


def test_public_result_validation_rejects_an_invalid_schema(tmp_path):
    policy = tmp_path / "policy"
    policy.mkdir()
    (policy / "Public_Result.schema.json").write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"invalid"}'
    )

    failures = validate_public_results(tmp_path)

    assert len(failures) == 1
    assert "invalid public result schema" in failures[0].message


def test_affected_validation_keeps_docs_static_and_groups_policy_tests():
    assert affected_validation_commands(REPOSITORY_ROOT, [Path("docs/Runbook.md")]) == ()

    commands = affected_validation_commands(
        REPOSITORY_ROOT,
        [
            Path("src/harness_testing/Metrics.py"),
            Path("policy/Command_Classification.toml"),
        ],
    )

    pytest_commands = [command for command in commands if "pytest" in command]
    assert len(pytest_commands) == 1
    assert set(pytest_commands[0][4:]) == {
        "tests/unit/test_Metrics.py",
        "tests/unit/test_Results.py",
        "tests/unit/test_Validate.py",
    }


def test_affected_validation_routes_shared_trajectory_decoder_checks():
    commands = affected_validation_commands(
        REPOSITORY_ROOT,
        [Path("src/harness_testing/Trajectory_Events.py")],
    )

    assert commands == (
        (
            "uv",
            "run",
            "ruff",
            "check",
            "src/harness_testing/Trajectory_Events.py",
        ),
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "tests/unit/test_Codex_Agent.py",
            "tests/unit/test_Metrics.py",
            "tests/unit/test_Sentinel_Criteria.py",
            "tests/unit/test_Trajectory_Events.py",
            "tests/unit/test_Workflow_Criteria.py",
        ),
        ("uv", "run", "harness-test", "images", "build", "--verifier"),
        (
            "uv",
            "run",
            "harness-test",
            "task",
            "qa",
            "--pack",
            "workflow",
            "--all-cases",
        ),
    )


def test_affected_validation_runs_only_oracle_and_nop_for_one_changed_task():
    commands = affected_validation_commands(
        REPOSITORY_ROOT,
        [Path("tasks/workflow/react-accent-polish/instruction.md")],
    )

    assert commands == (
        (
            "uv",
            "run",
            "harness-test",
            "task",
            "qa",
            "--task",
            "react-accent-polish",
            "--case",
            "oracle",
        ),
        (
            "uv",
            "run",
            "harness-test",
            "task",
            "qa",
            "--task",
            "react-accent-polish",
            "--case",
            "nop",
        ),
    )


def test_affected_validation_routes_dashboard_images_and_core_schema_changes():
    dashboard = affected_validation_commands(
        REPOSITORY_ROOT, [Path("dashboard/src/index.md")]
    )
    assert dashboard == (
        ("npm", "ci", "--prefix", "dashboard", "--ignore-scripts"),
        ("npm", "--prefix", "dashboard", "test"),
        ("npm", "--prefix", "dashboard", "run", "build"),
    )

    image = affected_validation_commands(
        REPOSITORY_ROOT, [Path("images/Node_Agent.Dockerfile")]
    )
    assert ("uv", "run", "harness-test", "images", "build", "--node") in image

    core = affected_validation_commands(
        REPOSITORY_ROOT, [Path("src/harness_testing/Config.py")]
    )
    assert ("uv", "run", "pytest", "tests/unit", "-q") in core
    assert any(command[-2:] == ("workflow", "--all-cases") for command in core)
    assert any(command[-2:] == ("contract", "--all-cases") for command in core)

    result_schema = affected_validation_commands(
        REPOSITORY_ROOT,
        [Path("src/harness_testing/Harness_Result.schema.json")],
    )
    assert result_schema == (
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "tests/unit/test_Contract_Criteria.py",
            "tests/unit/test_Contract_Stub_Server.py",
            "tests/unit/test_Harness_Result.py",
            "tests/unit/test_Materialize.py",
            "tests/unit/test_Validate.py",
        ),
        ("uv", "run", "harness-test", "images", "build", "--verifier"),
    )


def test_markdown_validation_checks_local_links_without_network(
    tmp_path, monkeypatch
):
    good = tmp_path / "Good.md"
    target = tmp_path / "Target.md"
    broken = tmp_path / "Broken.md"
    target.write_text("# Target\n")
    good.write_text("[target](Target.md) [web](https://example.com)\n")
    broken.write_text("[missing](Missing.md)\n")
    monkeypatch.setattr(Validate, "_repository_files", lambda root: (good, target))
    assert validate_markdown_links(tmp_path) == ()

    monkeypatch.setattr(Validate, "_repository_files", lambda root: (broken,))
    failures = validate_markdown_links(tmp_path)
    assert len(failures) == 1
    assert "broken local Markdown link" in failures[0].message


def test_workflow_validation_requires_ledger_pins_and_no_provider_credentials(tmp_path):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "Bad.yml").write_text(
        """
name: Bad
on: push
jobs:
  bad:
    runs-on: ubuntu-latest
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    steps:
      - uses: actions/checkout@v4
"""
    )

    failures = validate_workflow_files(
        tmp_path, {"actions/checkout": "d23441a48e516b6c34aea4fa41551a30e30af803"}
    )

    assert any("provider credentials" in failure.message for failure in failures)
    assert any("requires a full commit" in failure.message for failure in failures)
