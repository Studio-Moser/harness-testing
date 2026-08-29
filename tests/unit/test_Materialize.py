import json
import os
import subprocess
from pathlib import Path

import pytest

from harness_testing.CLI import main
from harness_testing.Materialize import (
    dockerfile_policy_errors,
    image_build_commands,
    materialize_arm,
)

REPOSITORY_ROOT = Path(__file__).parents[2]


def test_dockerfiles_use_pinned_images_and_install_only_pinned_tools():
    errors = dockerfile_policy_errors(REPOSITORY_ROOT)

    assert errors == ()


def test_image_build_commands_select_only_requested_images():
    commands = image_build_commands(REPOSITORY_ROOT, ("node", "verifier"))

    assert tuple(command.image for command in commands) == ("node", "verifier")
    assert all(
        command.arguments[:4] == ("docker", "buildx", "build", "--load")
        for command in commands
    )
    assert all("Rust_Agent.Dockerfile" not in command.arguments for command in commands)


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
            "plugins/harness/references/house-rules.md": "# House rules\n",
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
    assert project_instructions == "# Benchmark baseline\n\n# House rules\n"
    assert "PRIVATE PERSONAL INSTRUCTIONS" not in project_instructions


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
