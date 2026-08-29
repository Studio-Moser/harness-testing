import copy
import json
from pathlib import Path

from test_Config import VALID_TASK

from harness_testing.CLI import main
from harness_testing.Results import compatibility_key, public_result_id
from harness_testing.Validate import (
    find_sensitive_keys,
    validate_public_results,
    validate_repository,
    validate_task_paths,
    validate_versions_file,
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
