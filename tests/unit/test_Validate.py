import re
import shutil
from pathlib import Path

import yaml
from test_Config import VALID_TASK

import harness_testing.Validate as Validate
from harness_testing.CLI import main
from harness_testing.Validate import (
    find_sensitive_keys,
    validate_collaboration_policy,
    validate_markdown_links,
    validate_repository,
    validate_task_paths,
    validate_versions_file,
    validate_workflow_files,
)

REPOSITORY_ROOT = Path(__file__).parents[2]


def test_collaboration_policy_and_opus_example_are_valid():
    assert validate_collaboration_policy(REPOSITORY_ROOT) == ()


def test_collaboration_policy_requires_each_workflow_task_contract(tmp_path):
    shutil.copytree(REPOSITORY_ROOT / "policy", tmp_path / "policy")
    examples = tmp_path / "runs" / "examples"
    examples.mkdir(parents=True)
    shutil.copy(
        REPOSITORY_ROOT / "runs/examples/Opus Personality Comparison.json", examples
    )
    task = tmp_path / "tasks" / "workflow" / "missing-contract"
    task.mkdir(parents=True)
    (task / "task.toml").write_text("schema_version = '1.4'\n")

    failures = validate_collaboration_policy(tmp_path)

    assert any("Communication Contract.json" in str(failure) for failure in failures)


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


def test_workflow_fixture_requires_a_deterministic_git_baseline(tmp_path):
    source = REPOSITORY_ROOT / "tasks/workflow/react-saved-view-feature"
    task_root = tmp_path / source.name
    shutil.copytree(source, task_root)
    dockerfile_path = task_root / "environment/Dockerfile"
    dockerfile_path.write_text(
        dockerfile_path.read_text().replace(
            "git init --quiet --initial-branch=main",
            "true",
        )
    )
    task_path = task_root / "task.toml"
    fixture_digest = Validate._fixture_digest(task_root / "environment")
    task_path.write_text(
        re.sub(
            r'fixture_digest = "sha256:[0-9a-f]{64}"',
            f'fixture_digest = "{fixture_digest}"',
            task_path.read_text(),
            count=1,
        )
    )

    failures = Validate._validate_benchmark_task_assets(
        task_path,
        Validate.load_task(task_path, expected_schema="1.4"),
    )

    assert any(
        failure.message == "workflow fixture must create a deterministic Git baseline"
        for failure in failures
    )


def test_workflow_fixture_requires_git_excludes_at_the_canonical_path(tmp_path):
    source = REPOSITORY_ROOT / "tasks/workflow/react-saved-view-feature"
    task_root = tmp_path / source.name
    shutil.copytree(source, task_root)
    dockerfile_path = task_root / "environment/Dockerfile"
    dockerfile_path.write_text(
        dockerfile_path.read_text().replace(
            "> .git/info/exclude",
            "> /tmp/fixture-exclude",
        )
    )
    task_path = task_root / "task.toml"
    fixture_digest = Validate._fixture_digest(task_root / "environment")
    task_path.write_text(
        re.sub(
            r'fixture_digest = "sha256:[0-9a-f]{64}"',
            f'fixture_digest = "{fixture_digest}"',
            task_path.read_text(),
            count=1,
        )
    )

    failures = Validate._validate_benchmark_task_assets(
        task_path,
        Validate.load_task(task_path, expected_schema="1.4"),
    )

    assert any(
        failure.message == "workflow fixture must create a deterministic Git baseline"
        for failure in failures
    )


def test_workflow_fixture_requires_all_source_to_be_staged(tmp_path):
    source = REPOSITORY_ROOT / "tasks/workflow/react-saved-view-feature"
    task_root = tmp_path / source.name
    shutil.copytree(source, task_root)
    dockerfile_path = task_root / "environment/Dockerfile"
    dockerfile_path.write_text(
        dockerfile_path.read_text().replace(
            "git add --all",
            "git add package.json",
        )
    )
    task_path = task_root / "task.toml"
    fixture_digest = Validate._fixture_digest(task_root / "environment")
    task_path.write_text(
        re.sub(
            r'fixture_digest = "sha256:[0-9a-f]{64}"',
            f'fixture_digest = "{fixture_digest}"',
            task_path.read_text(),
            count=1,
        )
    )

    failures = Validate._validate_benchmark_task_assets(
        task_path,
        Validate.load_task(task_path, expected_schema="1.4"),
    )

    assert any(
        failure.message == "workflow fixture must create a deterministic Git baseline"
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


def test_validate_workflow_cancels_superseded_runs():
    workflow = yaml.safe_load(
        (REPOSITORY_ROOT / ".github" / "workflows" / "Validate.yml").read_text()
    )

    assert workflow["concurrency"] == {
        "group": "${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": True,
    }


