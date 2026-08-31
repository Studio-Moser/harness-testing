import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

import harness_testing.Materialize as Materialize
from harness_testing.CLI import main
from harness_testing.Materialize import (
    DEEPSWE_TASK_IDS,
    DeepSWEImageProvenance,
    deepswe_derived_dockerfile,
    deepswe_materialization_plan,
    dockerfile_policy_errors,
    format_deepswe_plan,
    image_build_commands,
    image_input_digest,
    load_deepswe_dataset,
    materialize_arm,
    materialize_deepswe,
)

REPOSITORY_ROOT = Path(__file__).parents[2]


def test_dockerfiles_use_pinned_images_and_install_only_pinned_tools():
    errors = dockerfile_policy_errors(REPOSITORY_ROOT)

    assert errors == ()


def test_base_image_context_excludes_local_and_benchmark_payloads():
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text().splitlines()

    assert set(dockerignore) >= {
        ".git",
        ".cache",
        ".venv",
        "arms/materialized",
        "runs/generated",
        "tasks",
        "tests",
    }


def test_verifier_image_carries_shared_workflow_support():
    dockerfile = (REPOSITORY_ROOT / "images" / "Verifier.Dockerfile").read_text()

    assert "src/harness_testing/Trajectory_Events.py" in dockerfile
    assert "src/harness_testing/Workflow_Criteria.py" in dockerfile


def test_image_build_commands_select_only_requested_images():
    commands = image_build_commands(REPOSITORY_ROOT, ("node", "verifier"))

    assert tuple(command.image for command in commands) == ("node", "verifier")
    assert all(
        command.arguments[:4] == ("docker", "buildx", "build", "--load")
        for command in commands
    )
    assert all("Rust_Agent.Dockerfile" not in command.arguments for command in commands)
    assert all(
        (
            "--label",
            "studio.moser.harness-testing.input-digest="
            f"{image_input_digest(REPOSITORY_ROOT, command.image)}",
        )
        in tuple(zip(command.arguments, command.arguments[1:], strict=False))
        for command in commands
    )


def test_verifier_image_digest_binds_the_shared_decoder(tmp_path: Path):
    (tmp_path / "images").mkdir()
    (tmp_path / "src" / "harness_testing").mkdir(parents=True)
    for relative in (
        "images/Verifier.Dockerfile",
        "src/harness_testing/__init__.py",
        "src/harness_testing/Contract_Criteria.py",
        "src/harness_testing/Contract_Stub_Server.py",
        "src/harness_testing/Trajectory_Events.py",
        "src/harness_testing/Workflow_Criteria.py",
    ):
        source = REPOSITORY_ROOT / relative
        destination = tmp_path / relative
        destination.write_bytes(source.read_bytes())
    first = image_input_digest(tmp_path, "verifier")
    (tmp_path / "src" / "harness_testing" / "Trajectory_Events.py").write_text(
        "changed\n"
    )

    assert image_input_digest(tmp_path, "verifier") != first

    criteria_first = image_input_digest(tmp_path, "verifier")
    (tmp_path / "src" / "harness_testing" / "Workflow_Criteria.py").write_text(
        "changed\n"
    )

    assert image_input_digest(tmp_path, "verifier") != criteria_first


def test_rust_image_recreates_global_cli_symlinks_after_copying_node_modules():
    dockerfile = (REPOSITORY_ROOT / "images" / "Rust_Agent.Dockerfile").read_text()

    assert (
        "ln -s ../lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe "
        "/usr/local/bin/claude" in dockerfile
    )
    assert (
        "ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex"
        in dockerfile
    )
    assert "COPY --from=agent-tools /usr/local/bin/codex" not in dockerfile


def test_rust_image_restores_cargo_for_login_shells():
    dockerfile = (REPOSITORY_ROOT / "images" / "Rust_Agent.Dockerfile").read_text()

    assert "/etc/profile.d/rust-path.sh" in dockerfile
    assert '${CARGO_HOME:-/usr/local/cargo}/bin:$PATH' in dockerfile


def test_image_build_without_selection_stops_before_docker(capsys):
    assert main(["images", "build"]) == 2

    output = capsys.readouterr()
    assert "No image selected" in output.err
    assert "Node_Agent.Dockerfile" in output.out
    assert "Rust_Agent.Dockerfile" in output.out
    assert "Verifier.Dockerfile" in output.out


def _git_repository(path: Path, files: dict[str, str]) -> tuple[Path, str]:
    path.mkdir()
    subprocess.run(("git", "init", "--quiet", path), check=True)
    subprocess.run(("git", "-C", path, "config", "user.name", "Harness Test"), check=True)
    subprocess.run(
        ("git", "-C", path, "config", "user.email", "harness@example.invalid"),
        check=True,
    )
    for relative_path, contents in files.items():
        destination = path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents)
    subprocess.run(("git", "-C", path, "add", "."), check=True)
    subprocess.run(("git", "-C", path, "commit", "--quiet", "-m", "fixture"), check=True)
    commit = subprocess.run(
        ("git", "-C", path, "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return path, commit


@pytest.fixture
def source_repositories(tmp_path: Path) -> dict[str, tuple[Path, str]]:
    superpowers_marketplace = {
        "name": "superpowers-dev",
        "plugins": [
            {
                "name": "superpowers",
                "version": "6.3.0",
                "source": "./",
            }
        ],
    }
    superpowers_codex_marketplace = {
        "name": "superpowers-dev",
        "plugins": [
            {
                "name": "superpowers",
                "source": {"source": "url", "url": "./"},
            }
        ],
    }
    superpowers = _git_repository(
        tmp_path / "superpowers",
        {
            ".claude-plugin/marketplace.json": json.dumps(superpowers_marketplace),
            ".claude-plugin/plugin.json": json.dumps(
                {"name": "superpowers", "version": "6.3.0"}
            ),
            ".agents/plugins/marketplace.json": json.dumps(
                superpowers_codex_marketplace
            ),
            ".codex-plugin/plugin.json": json.dumps(
                {
                    "name": "superpowers",
                    "version": "6.3.0",
                    "skills": "./skills/",
                    "hooks": {},
                }
            ),
            "hooks/hooks.json": "{}\n",
            "Provenance.json": '{"fixture": true}\n',
            "skills/using-superpowers/SKILL.md": "# Use Superpowers\n",
        },
    )
    harness_marketplace = {
        "name": "studio-moser",
        "plugins": [
            {
                "name": "harness",
                "version": "0.8.1",
                "source": "./plugins/harness",
            }
        ],
    }
    harness = _git_repository(
        tmp_path / "harness",
        {
            ".claude-plugin/marketplace.json": json.dumps(harness_marketplace),
            "plugins/harness/.claude-plugin/plugin.json": json.dumps(
                {"name": "harness", "version": "0.8.1"}
            ),
            "plugins/harness/skills/execute/SKILL.md": "# Execute\n",
            "plugins/harness/templates/AGENTS_Baseline.md": "# Benchmark baseline\n",
            "plugins/harness/references/harness-contract.md": "# Contract\n",
            "plugins/harness/references/house-rules.md": "# House rules\n",
            "plugins/harness/scripts/resolve-route.py": "#!/usr/bin/env python3\n",
        },
    )
    return {"Superpowers": superpowers, "Studio Harness": harness}


def test_materialization_requires_an_exact_commit(
    tmp_path: Path, source_repositories: dict[str, tuple[Path, str]]
):
    source, _ = source_repositories["Studio Harness"]

    with pytest.raises(ValueError, match="40-character lowercase commit"):
        materialize_arm(
            tmp_path,
            "codex",
            "A2",
            source_overrides={"Studio Harness": (source, "main")},
            native_cli=False,
        )


def test_materialization_rejects_a_dirty_candidate_source(
    tmp_path: Path, source_repositories: dict[str, tuple[Path, str]]
):
    source, commit = source_repositories["Studio Harness"]
    (source / "uncommitted.txt").write_text("candidate drift\n")

    with pytest.raises(ValueError, match="dirty"):
        materialize_arm(
            tmp_path,
            "claude",
            "A2",
            source_overrides={"Studio Harness": (source, commit)},
            native_cli=False,
        )


def test_materialization_is_content_addressed_and_repeatable(tmp_path: Path):
    first = materialize_arm(tmp_path, "codex", "A0", native_cli=False)
    second = materialize_arm(tmp_path, "codex", "A0", native_cli=False)

    assert first.digest == second.digest
    assert first.path == second.path
    assert first.path.name == first.digest.removeprefix("sha256:")
    assert not os.access(first.path / "Provenance.json", os.W_OK)


def test_materialization_uses_only_pinned_public_project_instructions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_repositories: dict[str, tuple[Path, str]],
):
    fake_home = tmp_path / "personal-home"
    fake_home.mkdir()
    (fake_home / "AGENTS.md").write_text("PRIVATE PERSONAL INSTRUCTIONS\n")
    monkeypatch.setenv("HOME", str(fake_home))

    bundle = materialize_arm(
        tmp_path,
        "codex",
        "A2",
        source_overrides={"Studio Harness": source_repositories["Studio Harness"]},
        native_cli=False,
    )

    project_instructions = (bundle.path / "project" / "AGENTS.md").read_text()
    assert project_instructions == "# Benchmark baseline\n"
    assert "PRIVATE PERSONAL INSTRUCTIONS" not in project_instructions


def test_codex_harness_materialization_preserves_plugin_companions(
    tmp_path: Path,
    source_repositories: dict[str, tuple[Path, str]],
):
    bundle = materialize_arm(
        tmp_path,
        "codex",
        "A2",
        source_overrides={"Studio Harness": source_repositories["Studio Harness"]},
        native_cli=False,
    )

    plugin = (
        bundle.path
        / "codex"
        / "provider-home"
        / "plugins"
        / "cache"
        / "studio-moser"
        / "harness"
        / "0.8.1"
    )
    assert (plugin / ".codex-plugin" / "plugin.json").is_file()
    assert (plugin / "skills" / "execute" / "SKILL.md").is_file()
    assert (plugin / "references" / "harness-contract.md").is_file()
    assert (plugin / "scripts" / "resolve-route.py").is_file()
    assert not (bundle.path / "skills").exists()
    marketplace = json.loads(
        (
            bundle.path
            / "codex"
            / "provider-home"
            / "marketplaces"
            / "studio-moser"
            / ".agents"
            / "plugins"
            / "marketplace.json"
        ).read_text()
    )
    assert marketplace["plugins"][0]["source"] == {
        "source": "local",
        "path": "./plugins/harness",
    }
    provenance = json.loads((bundle.path / "Provenance.json").read_text())
    assert provenance["materializer_schema"] == "2"
    assert provenance["delivery_surfaces"] == [
        {
            "layer": "Studio Harness",
            "surface": "codex-plugin",
            "capabilities": ["skills"],
        }
    ]


def test_codex_native_installer_creates_its_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    marketplace = tmp_path / "marketplace"
    plugin = marketplace / "plugins" / "harness"
    plugin.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run(arguments, **_kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(Materialize.subprocess, "run", fake_run)
    plugin_input = Materialize._PluginInput(
        layer="Studio Harness",
        marketplace="studio-moser",
        plugin="harness",
        version="0.8.1",
        path=marketplace,
        plugin_path=plugin,
    )

    Materialize._run_native_plugin_install(
        REPOSITORY_ROOT,
        "codex",
        (plugin_input,),
        tmp_path / "output",
    )

    assert "mkdir -p /output/home /output/provider-home" in calls[0][-1]


def test_provider_provenance_records_claude_hooks_but_codex_skills_only(
    tmp_path: Path, source_repositories: dict[str, tuple[Path, str]]
):
    claude = materialize_arm(
        tmp_path,
        "claude",
        "A1",
        source_overrides={"Superpowers": source_repositories["Superpowers"]},
        native_cli=False,
    )
    codex = materialize_arm(
        tmp_path,
        "codex",
        "A1",
        source_overrides={"Superpowers": source_repositories["Superpowers"]},
        native_cli=False,
    )

    claude_provenance = json.loads((claude.path / "Provenance.json").read_text())
    codex_provenance = json.loads((codex.path / "Provenance.json").read_text())
    assert claude_provenance["delivery_surfaces"][0]["capabilities"] == [
        "skills",
        "hooks",
    ]
    assert codex_provenance["delivery_surfaces"][0]["capabilities"] == ["skills"]
    assert any(
        path.endswith("/Provenance.json")
        for path in claude_provenance["generated_file_digests"]
    )
    assert (
        codex.path
        / "codex"
        / "provider-home"
        / "marketplaces"
        / "superpowers-dev"
        / ".agents"
        / "plugins"
        / "marketplace.json"
    ).is_file()


def _deepswe_files(images: dict[str, str]) -> dict[str, str]:
    files = {"README.md": "# DeepSWE fixture\n"}
    for index, task_id in enumerate((*DEEPSWE_TASK_IDS, "unselected-task"), 1):
        image = images.get(task_id, f"registry.invalid/{task_id}:v1.1")
        base_commit = str(index) * 40
        prefix = f"tasks/{task_id}"
        files.update(
            {
                f"{prefix}/instruction.md": f"Implement {task_id}.\n",
                f"{prefix}/pre_artifacts.sh": "#!/usr/bin/env bash\n",
                f"{prefix}/environment/Dockerfile": "FROM fixture:latest\n",
                f"{prefix}/solution/solution.patch": f"solution for {task_id}\n",
                f"{prefix}/solution/solve.sh": "#!/usr/bin/env bash\n",
                f"{prefix}/tests/Dockerfile": "FROM fixture-verifier:latest\n",
                f"{prefix}/tests/grader.py": "print('grade')\n",
                f"{prefix}/tests/test.sh": "#!/usr/bin/env bash\n",
                f"{prefix}/task.toml": (
                    'schema_version = "1.1"\n'
                    f'artifacts = ["/logs/artifacts/model.patch"]\n\n'
                    f'[task]\nname = "datacurve/{task_id}"\n\n'
                    f'[metadata]\ntask_id = "{task_id}"\n'
                    f'base_commit_hash = "{base_commit}"\n\n'
                    '[verifier]\nenvironment_mode = "separate"\n\n'
                    '[verifier.environment]\nallow_internet = false\n\n'
                    f'[environment]\ndocker_image = "{image}"\n'
                    'allow_internet = false\n'
                ),
            }
        )
    return files


def _deepswe_versions(source: Path, commit: str, images: dict[str, str]) -> str:
    tasks = "\n".join(
        (
            "[[deepswe.tasks]]\n"
            f'id = "{task_id}"\n'
            f'image = "{images[task_id]}"\n'
            f'digest = "sha256:{format(index, "x") * 64}"\n'
        )
        for index, task_id in enumerate(DEEPSWE_TASK_IDS, 1)
    )
    return f'''\
[repository]
schema_version = "0.1.0"

[[sources]]
name = "DeepSWE"
url = {json.dumps(str(source))}
version = "1.1"
commit = "{commit}"
redistribute = false

[deepswe]
schema_version = "1.1"
cache_path = ".cache/deepswe"
license_at_pin = "absent"
platform = "linux/amd64"

{tasks}
[[packages]]
name = "@anthropic-ai/claude-code"
version = "2.1.236"

[[packages]]
name = "@openai/codex"
version = "0.150.1"
'''


@pytest.fixture
def deepswe_fixture(tmp_path: Path) -> tuple[Path, Path, str, dict[str, str]]:
    images = {
        task_id: f"registry.invalid/{task_id}:v1.1"
        for task_id in DEEPSWE_TASK_IDS
    }
    source, commit = _git_repository(
        tmp_path / "deep-swe-source", _deepswe_files(images)
    )
    root, _ = _git_repository(
        tmp_path / "harness-testing",
        {
            ".gitignore": ".cache/\n",
            "Versions.toml": _deepswe_versions(source, commit, images),
        },
    )
    return root, source, commit, images


def _fake_deepswe_images(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str, str, str]]:
    calls: list[tuple[str, str, str, str]] = []
    image_ids: dict[str, str] = {}

    def fake_materialize(
        root: Path,
        task_id: str,
        original_image: str,
        original_manifest_digest: str,
        platform: str,
        base_commit: str,
        dockerfile_path: Path,
        verifier_context: Path,
        verifier_dockerfile_path: Path,
    ) -> DeepSWEImageProvenance:
        del root
        calls.append(
            (task_id, original_image, original_manifest_digest, platform)
        )
        dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
        dockerfile_path.write_text(
            f"FROM {original_image}\n# derived fixture for {task_id}\n"
        )
        verifier_dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
        verifier_dockerfile_path.write_text(
            f"FROM {original_image}@{original_manifest_digest}\n"
        )
        assert verifier_context.name == "tests"
        character = format(len(calls), "x")
        original_digest = f"sha256:{character * 64}"
        derived_character = format(len(calls) + 6, "x")
        derived_digest = f"sha256:{derived_character * 64}"
        derived_image = f"studio-moser/deepswe-{task_id}:{derived_character * 12}"
        verifier_image = f"{derived_image}-verifier"
        verifier_digest = f"sha256:{format(len(calls) + 12, 'x') * 64}"
        original_reference = f"{original_image}@{original_manifest_digest}"
        image_ids[original_reference] = original_digest
        image_ids[derived_image] = derived_digest
        image_ids[verifier_image] = verifier_digest
        return DeepSWEImageProvenance(
            original_image=original_image,
            original_image_reference=original_reference,
            original_manifest_digest=original_manifest_digest,
            original_image_digest=original_digest,
            derived_image=derived_image,
            derived_image_digest=derived_digest,
            verifier_image=verifier_image,
            verifier_image_digest=verifier_digest,
            platform=platform,
            starting_repository_commit=base_commit,
            starting_repository_digest=f"sha256:{'f' * 64}",
            starting_repository_files={"README.md": f"sha256:{'e' * 64}"},
        )

    monkeypatch.setattr(Materialize, "_materialize_deepswe_image", fake_materialize)
    monkeypatch.setattr(
        Materialize,
        "_inspect_image_id",
        lambda image: image_ids.get(image),
    )
    return calls


def test_deepswe_plan_is_manual_exact_and_has_no_side_effects(capsys):
    plan = deepswe_materialization_plan(REPOSITORY_ROOT)
    report = format_deepswe_plan(plan)

    assert plan.task_ids == DEEPSWE_TASK_IDS
    assert plan.commit == "8cae5984d5dd0ee37445beff0e928dc10c331116"
    assert plan.platform == "linux/amd64"
    assert "six pinned task directories" in report
    assert "linux/amd64" in report
    assert "@sha256:930ec9d5" in report
    assert "No model session" in report
    assert main(["deepswe", "materialize"]) == 2
    output = capsys.readouterr()
    assert "--confirm-download" in output.err
    assert DEEPSWE_TASK_IDS[0] in output.out


def test_deepswe_materialization_requires_confirmation(
    deepswe_fixture: tuple[Path, Path, str, dict[str, str]],
):
    root, source, commit, _ = deepswe_fixture

    with pytest.raises(ValueError, match="explicit --confirm-download"):
        materialize_deepswe(
            root,
            confirm_download=False,
            source_override=(source, commit),
        )
    assert not (root / ".cache" / "deepswe").exists()


def test_deepswe_materializes_only_the_pinned_cohort_with_separate_provenance(
    deepswe_fixture: tuple[Path, Path, str, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
):
    root, source, commit, images = deepswe_fixture
    calls = _fake_deepswe_images(monkeypatch)

    materialized = materialize_deepswe(
        root,
        confirm_download=True,
        source_override=(source, commit),
    )
    provenance = json.loads(materialized.provenance_path.read_text())

    assert [task_id for task_id, _, _, _ in calls] == list(DEEPSWE_TASK_IDS)
    assert {platform for _, _, _, platform in calls} == {"linux/amd64"}
    assert set(path.name for path in materialized.tasks_path.iterdir()) == set(
        DEEPSWE_TASK_IDS
    )
    assert not (materialized.tasks_path / "unselected-task").exists()
    assert materialized.digest == provenance["dataset_digest"]
    assert provenance["source"]["commit"] == commit
    assert provenance["redistribution"] == "forbidden"
    assert provenance["license_at_pin"] == "absent"
    for task in provenance["tasks"]:
        assert task["original_task_digest"] != task["wrapper_digest"]
        assert task["original_image"] == images[task["task_id"]]
        assert task["original_image_reference"].startswith(
            images[task["task_id"]] + "@sha256:"
        )
        assert task["platform"] == "linux/amd64"
        assert task["original_image_digest"] != task["derived_image_digest"]
        assert task["verifier_image_digest"] != task["derived_image_digest"]
        assert set(task["byte_manifests"]) == {
            "instruction",
            "metadata",
            "solution",
            "starting_repository",
            "verifier",
        }
        wrapper = materialized.tasks_path / task["task_id"]
        source_task = (
            root
            / ".cache"
            / "deepswe"
            / "source-trees"
            / commit
            / "tasks"
            / task["task_id"]
        )
        assert (wrapper / "instruction.md").read_bytes() == (
            source_task / "instruction.md"
        ).read_bytes()
        assert (wrapper / "solution" / "solution.patch").read_bytes() == (
            source_task / "solution" / "solution.patch"
        ).read_bytes()
        assert (wrapper / "tests" / "test.sh").read_bytes() == (
            source_task / "tests" / "test.sh"
        ).read_bytes()
        assert (wrapper / "tests" / "Dockerfile").read_bytes() == (
            source_task / "tests" / "Dockerfile"
        ).read_bytes()
        wrapper_config = tomllib.loads((wrapper / "task.toml").read_text())
        assert wrapper_config["environment"]["docker_image"] == task["derived_image"]
        assert (
            wrapper_config["verifier"]["environment"]["docker_image"]
            == task["verifier_image"]
        )


def test_deepswe_cache_reuse_validates_bytes_and_does_not_rebuild(
    deepswe_fixture: tuple[Path, Path, str, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
):
    root, source, commit, _ = deepswe_fixture
    calls = _fake_deepswe_images(monkeypatch)
    first = materialize_deepswe(
        root,
        confirm_download=True,
        source_override=(source, commit),
    )
    second = materialize_deepswe(
        root,
        confirm_download=True,
        source_override=(source, commit),
    )

    assert first == second
    assert len(calls) == 6
    assert load_deepswe_dataset(root) == first

    wrapper_instruction = (
        first.tasks_path / DEEPSWE_TASK_IDS[0] / "instruction.md"
    )
    wrapper_instruction.chmod(0o644)
    wrapper_instruction.write_text("changed cached wrapper\n")
    with pytest.raises(ValueError, match="dataset.*provenance"):
        load_deepswe_dataset(root)

    cached_instruction = (
        root
        / ".cache"
        / "deepswe"
        / "source-trees"
        / commit
        / "tasks"
        / DEEPSWE_TASK_IDS[0]
        / "instruction.md"
    )
    cached_instruction.chmod(0o644)
    cached_instruction.write_text("changed cached source\n")
    with pytest.raises(ValueError, match="source cache.*manifest"):
        materialize_deepswe(
            root,
            confirm_download=True,
            source_override=(source, commit),
        )


def test_deepswe_rejects_a_different_commit_and_a_publishable_cache(
    deepswe_fixture: tuple[Path, Path, str, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
):
    root, source, commit, _ = deepswe_fixture
    _fake_deepswe_images(monkeypatch)
    (source / "README.md").write_text("changed upstream\n")
    subprocess.run(("git", "-C", source, "add", "README.md"), check=True)
    subprocess.run(
        ("git", "-C", source, "commit", "--quiet", "-m", "changed"), check=True
    )
    changed_commit = subprocess.run(
        ("git", "-C", source, "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    with pytest.raises(ValueError, match="does not match the DeepSWE pin"):
        materialize_deepswe(
            root,
            confirm_download=True,
            source_override=(source, changed_commit),
        )

    assert changed_commit != commit
    (root / ".gitignore").write_text("runs/generated/\n")
    with pytest.raises(ValueError, match="must be ignored"):
        materialize_deepswe(
            root,
            confirm_download=True,
            source_override=(source, commit),
        )


def test_deepswe_derived_dockerfile_uses_pinned_clis_without_touching_app():
    dockerfile = deepswe_derived_dockerfile(
        REPOSITORY_ROOT,
        "registry.invalid/task@sha256:" + "a" * 64,
        "studio-moser/harness-testing-node:0.1.0",
        original_user="agent",
    )

    assert "npm install" not in dockerfile
    assert "/usr/local/lib/node_modules/@anthropic-ai/claude-code" in dockerfile
    assert "/usr/local/lib/node_modules/@openai/codex" in dockerfile
    assert "git -C /app status --porcelain" in dockerfile
    assert "USER agent" in dockerfile


def test_deepswe_agent_tools_build_matches_the_pinned_task_platform():
    arguments = Materialize._platform_agent_tools_build_arguments(
        REPOSITORY_ROOT, "linux/amd64"
    )

    assert ("--platform", "linux/amd64") in tuple(
        zip(arguments, arguments[1:], strict=False)
    )
    assert (
        "--tag",
        "studio-moser/harness-testing-node:0.1.0-linux-amd64",
    ) in tuple(zip(arguments, arguments[1:], strict=False))


def test_deepswe_verifier_dockerfile_pins_only_the_original_from_reference():
    original = (
        "# hidden verifier\n"
        "FROM registry.invalid/task:v1.1\n\n"
        "COPY test.sh /tests/test.sh\n"
    )
    immutable = "registry.invalid/task:v1.1@sha256:" + "a" * 64

    pinned = Materialize.deepswe_pinned_verifier_dockerfile(original, immutable)

    assert pinned == original.replace(
        "FROM registry.invalid/task:v1.1", f"FROM {immutable}"
    )
    with pytest.raises(ValueError, match="requires one base image"):
        Materialize.deepswe_pinned_verifier_dockerfile(
            original + "FROM registry.invalid/second:v1.1\n",
            immutable,
        )
