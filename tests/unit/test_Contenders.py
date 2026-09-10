import json
import subprocess

import pytest

from harness_testing.Contenders import materialize_contender, validate_contender_bundle


def source_repository(path):
    for plugin in ("harness", "pm"):
        root = path / "plugins" / plugin
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin/plugin.json").write_text(
            json.dumps({"name": plugin, "version": "1.0.0"})
        )
        (root / "skills/execute").mkdir(parents=True)
        (root / "skills/execute/SKILL.md").write_text(
            f"---\nname: {plugin}-execute\ndescription: fixture\n---\nDo the task.\n"
        )
    (path / ".claude-plugin").mkdir()
    (path / ".claude-plugin/marketplace.json").write_text(
        json.dumps(
            {
                "name": "fixture",
                "plugins": [
                    {"name": name, "source": f"./plugins/{name}"} for name in ("harness", "pm")
                ],
            }
        )
    )
    for args in (
        ("init", "--quiet"),
        ("add", "."),
        (
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ),
    ):
        subprocess.run(["git", "-C", str(path), *args], check=True)
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def definition(source, commit):
    return {
        "family": "studio-moser",
        "label": "Full collection",
        "sources": [
            {"name": "Studio Moser", "kind": "collection", "source": str(source), "commit": commit}
        ],
        "rubric": {"mode": "disabled", "path": None},
        "startup_paths": [],
        "delivery_config": {},
    }


def test_all_collection_plugins_are_delivered_and_versioned(tmp_path):
    source = tmp_path / "source"
    commit = source_repository(source)
    bundle, contender = materialize_contender(
        tmp_path, "claude", definition(source, commit), native_cli=False
    )
    assert (bundle.path / "claude/plugins/harness/skills/execute/SKILL.md").is_file()
    assert (bundle.path / "claude/plugins/pm/skills/execute/SKILL.md").is_file()
    assert contender["family"] == "studio-moser"
    assert len(contender["id"]) == 71
    validate_contender_bundle(bundle.path, contender["id"], bundle.digest)
    changed = bundle.path / "claude/plugins/pm/skills/execute/SKILL.md"
    changed.chmod(0o644)
    changed.write_text("tampered")
    with pytest.raises(ValueError, match="contents"):
        validate_contender_bundle(bundle.path, contender["id"], bundle.digest)


def test_seed_rubric_is_rejected(tmp_path):
    source = tmp_path / "source"
    commit = source_repository(source)
    rubric = tmp_path / "Rubric.yml"
    rubric.write_text("seed: true\nrouting: {}\nmodels: []\n")
    contender = definition(source, commit)
    contender["rubric"] = {"mode": "enabled", "path": str(rubric)}
    with pytest.raises(ValueError, match="rubric"):
        materialize_contender(tmp_path, "claude", contender, native_cli=False)


def test_nothing_has_no_harness_instructions(tmp_path):
    contender = {
        "family": "nothing",
        "label": "Nothing",
        "sources": [],
        "startup_paths": [],
        "rubric": {"mode": "disabled", "path": None},
        "delivery_config": {},
    }
    bundle, _ = materialize_contender(tmp_path, "codex", contender, native_cli=False)
    assert not (bundle.path / "project").exists()


def test_personality_only_contender_freezes_startup_instructions(tmp_path):
    style = tmp_path / "House Style.md"
    style.write_text("Be concise and direct.\n")
    contender = {
        "family": "studio-personality",
        "label": "Studio personality only",
        "sources": [],
        "startup_paths": [str(style)],
        "rubric": {"mode": "disabled", "path": None},
        "delivery_config": {},
    }
    bundle, public = materialize_contender(tmp_path, "claude", contender, native_cli=False)
    assert (bundle.path / "project/CLAUDE.md").read_text() == "Be concise and direct.\n\n"
    assert public["family"] == "studio-personality"
    assert public["source_commits"] == []


def test_reviewed_rubric_accepts_numeric_taste_threshold(tmp_path):
    from harness_testing.Contenders import _rubric_bytes

    path = tmp_path / "Rubric.yml"
    content = (
        "reviewed: 2026-09-05\ncapabilities: {codex: true}\n"
        "routing: {default: 'fixture@high', taste_min: 9}\n"
        "models: [{name: fixture, effort: high, trust: routine, efficiency: 8}]\n"
    )
    path.write_text(content)
    assert _rubric_bytes({"rubric": {"mode": "enabled", "path": str(path)}}) == content.encode()
