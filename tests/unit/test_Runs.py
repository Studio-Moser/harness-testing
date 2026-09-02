import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from harbor.skills import resolve_skills

import harness_testing.Runs as Runs
from harness_testing.Config import load_job, load_versions
from harness_testing.Materialize import (
    _ARM_LAYERS,
    DEEPSWE_TASK_IDS,
    MaterializedDeepSWE,
    _canonical_json,
    _file_digests,
    _resolve_source_trees,
    _sha256_bytes,
    _tree_digest,
)
from harness_testing.Runs import (
    RunCell,
    _verify_generated_inputs,
    compile_run,
    verify_manifest_document,
)
from harness_testing.Skill_Evaluation import SkillEvaluation

REPOSITORY_ROOT = Path(__file__).parents[2]
PROFILE_TEXT = """\
schema_version = "1"

[profiles.smoke]
attempts = 1
agent_timeout_seconds = 900
concurrency = 1
packs = ["workflow"]
max_sessions = 16
estimated_input_tokens_per_session = 1000000
estimated_output_tokens_per_session = 100000

[profiles.calibration]
attempts = 2
agent_timeout_seconds = 900
concurrency = 1
packs = ["workflow"]
max_sessions = 64
estimated_input_tokens_per_session = 1000000
estimated_output_tokens_per_session = 100000

[profiles.research]
attempts = 1
agent_timeout_seconds = 3600
concurrency = 1
packs = ["research"]
max_sessions = 24
estimated_input_tokens_per_session = 2000000
estimated_output_tokens_per_session = 200000
"""


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _cell(
    provider: str,
    arm: str,
    role: str,
    digest_character: str,
    harness_commit: str | None = None,
) -> RunCell:
    model = "claude-sonnet-4-6" if provider == "claude" else "gpt-5.6-terra"
    return RunCell(
        label=f"{provider}-{arm}-{role}",
        provider=provider,
        arm=arm,
        role=role,
        model=model,
        effort="high",
        harness_commit=harness_commit,
        bundle_digest=_digest(digest_character),
    )


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


@pytest.fixture(scope="session")
def source_repositories(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, tuple[Path, str]]:
    root = tmp_path_factory.mktemp("run-source-repositories")
    superpowers = _git_repository(
        root / "superpowers",
        {
            ".claude-plugin/marketplace.json": json.dumps(
                {
                    "name": "superpowers-dev",
                    "plugins": [
                        {
                            "name": "superpowers",
                            "version": "6.3.0",
                            "source": "./",
                        }
                    ],
                }
            ),
            ".claude-plugin/plugin.json": json.dumps(
                {"name": "superpowers", "version": "6.3.0"}
            ),
            ".agents/plugins/marketplace.json": json.dumps(
                {
                    "name": "superpowers-dev",
                    "plugins": [
                        {
                            "name": "superpowers",
                            "source": {"source": "url", "url": "./"},
                        }
                    ],
                }
            ),
            ".codex-plugin/plugin.json": json.dumps(
                {
                    "name": "superpowers",
                    "version": "6.3.0",
                    "skills": "./skills/",
                }
            ),
            "hooks/hooks.json": "{}\n",
            "skills/using-superpowers/SKILL.md": "# Use Superpowers\n",
        },
    )
    harness = _git_repository(
        root / "harness",
        {
            ".claude-plugin/marketplace.json": json.dumps(
                {
                    "name": "studio-moser",
                    "plugins": [
                        {
                            "name": "harness",
                            "version": "0.8.7",
                            "source": "./plugins/harness",
                        }
                    ],
                }
            ),
            "plugins/harness/.claude-plugin/plugin.json": json.dumps(
                {"name": "harness", "version": "0.8.7"}
            ),
            "plugins/harness/skills/execute/SKILL.md": "# Execute\n",
            "plugins/harness/templates/AGENTS_Baseline.md": (
                "# Benchmark baseline\n"
            ),
            "plugins/harness/references/harness-contract.md": "# Contract\n",
            "plugins/harness/scripts/resolve-route.py": "#!/usr/bin/env python3\n",
        },
    )
    return {"Superpowers": superpowers, "Studio Harness": harness}


@pytest.fixture
def run_root(
    tmp_path: Path,
    source_repositories: dict[str, tuple[Path, str]],
) -> Path:
    superpowers, superpowers_commit = source_repositories["Superpowers"]
    harness, harness_commit = source_repositories["Studio Harness"]
    versions = (REPOSITORY_ROOT / "Versions.toml").read_text()
    versions = versions.replace(
        """[[sources]]
name = "Superpowers"
url = "https://github.com/obra/superpowers.git"
version = "6.3.0"
commit = "b36e0829c6d0140e93cfef2ca599b1b07d4a7797"
""",
        f"""[[sources]]
name = "Superpowers"
url = {json.dumps(str(superpowers))}
version = "6.3.0"
commit = "{superpowers_commit}"
""",
    )
    versions = versions.replace(
        """[[sources]]
name = "Studio Harness"
url = "https://github.com/Studio-Moser/skills-n-stuff.git"
version = "0.8.7"
commit = "a0fec5021b442c4db2a8889b3a722d838f66e117"
""",
        f"""[[sources]]
name = "Studio Harness"
url = {json.dumps(str(harness))}
version = "0.8.7"
commit = "{harness_commit}"
""",
    )
    (tmp_path / "Versions.toml").write_text(versions)
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "Profiles.toml").write_text(PROFILE_TEXT)
    (tmp_path / "tasks" / "workflow" / "task-one").mkdir(parents=True)
    (tmp_path / "tasks" / "workflow" / "task-two").mkdir()
    (tmp_path / "tasks" / "workflow" / "task-one" / "instruction.md").write_text(
        "task one\n"
    )
    (tmp_path / "tasks" / "workflow" / "task-two" / "instruction.md").write_text(
        "task two\n"
    )
    for task_id in ("task-one", "task-two"):
        (tmp_path / "tasks" / "workflow" / task_id / "task.toml").write_text(
            'schema_version = "1.4"\n'
        )
    for relative in (
        "images/Node_Agent.Dockerfile",
        "images/Verifier.Dockerfile",
        "src/harness_testing/Claude_Agent.py",
        "src/harness_testing/Codex_Agent.py",
        "src/harness_testing/__init__.py",
        "src/harness_testing/Contract_Criteria.py",
        "src/harness_testing/Contract_Stub_Server.py",
        "src/harness_testing/Harness_Result.py",
        "src/harness_testing/Harness_Result.schema.json",
        "src/harness_testing/Skill_Evaluation.py",
        "src/harness_testing/Trajectory_Events.py",
        "src/harness_testing/Workflow_Criteria.py",
    ):
        source = REPOSITORY_ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return tmp_path


def _add_bundle(root: Path, cell: RunCell, *, skill_name: str | None = None) -> Path:
    versions = load_versions(root / "Versions.toml")
    pins = {
        str(source["name"]): source for source in versions.get("sources", [])
    }
    source_overrides = {}
    if cell.harness_commit is not None:
        harness_pin = pins["Studio Harness"]
        object.__setattr__(cell, "harness_commit", str(harness_pin["commit"]))
        source_overrides["Studio Harness"] = (
            str(harness_pin["url"]),
            cell.harness_commit,
        )
    layers = _ARM_LAYERS[cell.arm]
    source_trees = _resolve_source_trees(root, layers, source_overrides)
    path = (
        root
        / "arms"
        / "materialized"
        / cell.provider
        / cell.arm
        / cell.bundle_digest.removeprefix("sha256:")
    )
    path.mkdir(parents=True, exist_ok=True)
    sources = [
        {
            "name": source.name,
            "url": source.url,
            "version": source.version,
            "commit": source.commit,
            "source_tree_digest": source.digest,
        }
        for source in source_trees
    ]
    delivery_surfaces = []
    for layer in layers:
        plugin_version = "6.3.0" if layer == "Superpowers" else "0.8.7"
        if cell.provider == "claude":
            plugin = "superpowers" if layer == "Superpowers" else "harness"
            relative = Path("claude") / "plugins" / plugin
            provider_path = f"/harness-arm/{relative.as_posix()}"
            surface = "claude-plugin-dir"
        else:
            marketplace = "superpowers-dev" if layer == "Superpowers" else "studio-moser"
            plugin = "superpowers" if layer == "Superpowers" else "harness"
            version = plugin_version
            relative = (
                Path("codex")
                / "provider-home"
                / "plugins"
                / "cache"
                / marketplace
                / plugin
                / version
            )
            provider_path = f"/harness-arm/{relative.as_posix()}"
            surface = "codex-plugin"
        (path / relative).mkdir(parents=True, exist_ok=True)
        (path / relative / "skills").mkdir(exist_ok=True)
        plugin_skill_name = (
            "using-superpowers" if layer == "Superpowers" else "execute"
        )
        skill = path / relative / "skills" / plugin_skill_name
        skill.mkdir()
        (skill / "SKILL.md").write_text(f"# {plugin_skill_name}\n")
        if cell.provider == "claude":
            manifest = path / relative / ".claude-plugin"
            manifest.mkdir(exist_ok=True)
            (manifest / "plugin.json").write_text(
                json.dumps({"name": plugin, "version": plugin_version})
                + "\n"
            )
            if layer == "Superpowers":
                (path / relative / "hooks").mkdir(exist_ok=True)
        if layer == "Studio Harness":
            template = path / relative / "templates" / "AGENTS_Baseline.md"
            template.parent.mkdir(exist_ok=True)
            template.write_text("# Benchmark baseline\n")
            instruction = path / "project" / (
                "CLAUDE.md" if cell.provider == "claude" else "AGENTS.md"
            )
            instruction.parent.mkdir(exist_ok=True)
            instruction.write_text("# Benchmark baseline\n")
        if cell.provider == "codex":
            manifest = path / relative / ".codex-plugin"
            manifest.mkdir(exist_ok=True)
            (manifest / "plugin.json").write_text(
                json.dumps({"name": plugin, "version": version}) + "\n"
            )
        delivery_surfaces.append(
            {
                "layer": layer,
                "surface": surface,
                "path": provider_path,
                "capabilities": (
                    ["skills", "hooks"]
                    if cell.provider == "claude"
                    and layer == "Superpowers"
                    else ["skills"]
                ),
            }
        )
    if cell.provider == "codex" and layers:
        provider_home = path / "codex" / "provider-home"
        marketplaces = {
            surface["path"].split("/")[-3] for surface in delivery_surfaces
        }
        for marketplace in marketplaces:
            (provider_home / "marketplaces" / marketplace).mkdir(parents=True)
        sections = []
        for surface in delivery_surfaces:
            marketplace, plugin, _ = surface["path"].rsplit("/", 3)[-3:]
            sections.extend(
                (
                    f"[marketplaces.{marketplace}]",
                    'source_type = "local"',
                    (
                        'source = "/harness-arm/codex/provider-home/marketplaces/'
                        f'{marketplace}"'
                    ),
                    "",
                    f'[plugins."{plugin}@{marketplace}"]',
                    "enabled = true",
                    "",
                )
            )
        (provider_home / "config.toml").write_text("\n".join(sections))
    if skill_name is not None:
        skill = path / "skills" / skill_name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# Dev task\n")
    provenance: dict[str, object] = {
        "provider": cell.provider,
        "arm": cell.arm,
        "layers": list(layers),
        "sources": sources,
        "delivery_surfaces": delivery_surfaces,
        "generated_file_digests": _file_digests(path),
        "materializer_schema": "3",
    }
    digest = _sha256_bytes(_canonical_json(provenance))
    object.__setattr__(cell, "bundle_digest", digest)
    provenance["bundle_digest"] = digest
    (path / "Provenance.json").write_text(json.dumps(provenance) + "\n")
    destination = path.parent / digest.removeprefix("sha256:")
    if destination.exists():
        shutil.rmtree(path)
        return destination
    path.rename(destination)
    return destination


def _reseal_bundle(cell: RunCell, bundle: Path) -> Path:
    provenance_path = bundle / "Provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance.pop("bundle_digest")
    provenance["generated_file_digests"] = _file_digests(bundle)
    digest = _sha256_bytes(_canonical_json(provenance))
    object.__setattr__(cell, "bundle_digest", digest)
    provenance["bundle_digest"] = digest
    provenance_path.write_text(json.dumps(provenance) + "\n")
    destination = bundle.parent / digest.removeprefix("sha256:")
    bundle.rename(destination)
    return destination


def _claude_cells() -> tuple[RunCell, ...]:
    return (
        _cell("claude", "A0", "candidate", "0"),
        _cell("claude", "A1", "candidate", "1"),
        _cell("claude", "A2", "candidate", "2", "2" * 40),
        _cell("claude", "A3", "candidate", "3", "3" * 40),
    )


def _compile_claude_matrix(root: Path, task_ids: tuple[str, ...] = ("task-one",)):
    cells = _claude_cells()
    for cell in cells:
        _add_bundle(root, cell)
    return compile_run(
        root,
        profile="calibration",
        billing_mode="api",
        cells=cells,
        task_ids=task_ids,
        max_sessions=4 * len(task_ids),
        max_budget_usd=Decimal("100"),
        attempts=1,
    )


def _paired_cells(root: Path) -> tuple[RunCell, RunCell]:
    baseline = _cell(
        "claude",
        "A2",
        "baseline",
        "a",
        "1" * 40,
    )
    candidate = _cell(
        "claude",
        "A2",
        "candidate",
        "b",
        "2" * 40,
    )
    _add_bundle(root, baseline)
    _add_bundle(root, candidate)
    return baseline, candidate


def _compile_pair(root: Path, **overrides):
    baseline, candidate = _paired_cells(root)
    arguments = {
        "root": root,
        "profile": "smoke",
        "cells": (candidate, baseline),
        "task_ids": ("task-one", "task-two"),
        "max_sessions": 4,
        "max_budget_usd": Decimal("100"),
        "billing_mode": "api",
    }
    arguments.update(overrides)
    return compile_run(**arguments)


def _benchmark_plugins(arm: str) -> list[str]:
    return {
        "A0": [],
        "A1": ["superpowers"],
        "A2": ["harness"],
        "A3": ["superpowers", "harness"],
    }[arm]


def _benchmark_skills(arm: str) -> list[str]:
    return {
        "A0": [],
        "A1": ["superpowers:using-superpowers"],
        "A2": ["harness:execute"],
        "A3": ["superpowers:using-superpowers", "harness:execute"],
    }[arm]


def _codex_inventory_record(plugin: str) -> dict[str, object]:
    marketplace = "superpowers-dev" if plugin == "superpowers" else "studio-moser"
    version = "6.3.0" if plugin == "superpowers" else "0.8.7"
    return {
        "name": plugin,
        "pluginId": f"{plugin}@{marketplace}",
        "marketplaceName": marketplace,
        "version": version,
        "enabled": True,
        "installed": True,
    }


def _write_completed_job(
    root: Path,
    cell: RunCell,
    job_name: str,
    *,
    plugins: list[object] | None = None,
    skills: list[object] | None = None,
    reward: float = 1.0,
    exception_info: object = None,
    include_exception_info: bool = True,
    attempts: int = 1,
    skill_invoked: bool = False,
) -> None:
    job = root / "jobs" / "raw" / job_name
    job.mkdir(parents=True)
    (job / "result.json").write_text(
        json.dumps(
            {
                "n_total_trials": attempts,
                "stats": {
                    "n_completed_trials": attempts,
                    "n_errored_trials": 0,
                    "n_running_trials": 0,
                    "n_pending_trials": 0,
                    "n_cancelled_trials": 0,
                }
            }
        )
        + "\n"
    )
    expected_plugins = _benchmark_plugins(cell.arm)
    for attempt in range(1, attempts + 1):
        trial = job / f"trial-{attempt}"
        agent = trial / "agent"
        verifier = trial / "verifier"
        agent.mkdir(parents=True)
        verifier.mkdir()
        trial_result = {
            "verifier_result": {"rewards": {"reward": reward}},
        }
        if include_exception_info:
            trial_result["exception_info"] = exception_info
        (trial / "result.json").write_text(json.dumps(trial_result) + "\n")
        (verifier / "reward.json").write_text(
            json.dumps({"reward": reward}) + "\n"
        )
        if cell.provider == "claude":
            event = {
                "type": "system",
                "subtype": "init",
                "plugins": plugins if plugins is not None else expected_plugins,
                "skills": skills if skills is not None else _benchmark_skills(cell.arm),
            }
            (agent / "claude-code.txt").write_text(json.dumps(event) + "\n")
        else:
            installed = (
                plugins
                if plugins is not None
                else [_codex_inventory_record(plugin) for plugin in expected_plugins]
            )
            (agent / "plugin-inventory.json").write_text(
                json.dumps(
                    {
                        "installed": installed,
                        "available": [
                            {
                                "name": "provider-builtin",
                                "pluginId": "provider-builtin@provider",
                            }
                        ],
                    }
                )
                + "\n"
            )
        if skill_invoked and cell.provider == "claude":
            call = {
                "tool_call_id": f"skill-{attempt}",
                "function_name": "Skill",
                "arguments": {"skill": "harness:execute"},
            }
        elif skill_invoked:
            call = {
                "tool_call_id": f"skill-{attempt}",
                "function_name": "shell",
                "arguments": {
                    "cmd": (
                        "sed -n '1,220p' /harness-arm/codex/provider-home/"
                        "plugins/cache/studio-moser/harness/0.8.7/skills/"
                        "execute/SKILL.md"
                    )
                },
            }
        else:
            call = None
        (agent / "trajectory.json").write_text(
            json.dumps(
                {
                    "schema_version": "ATIF-v1.7",
                    "steps": [
                        {
                            "step_id": 1,
                            "source": "agent",
                            "message": "",
                            "tool_calls": [] if call is None else [call],
                        }
                    ],
                }
            )
            + "\n"
        )


@pytest.mark.parametrize(
    "cell",
    (
        _cell("claude", "A3", "candidate", "a", "a" * 40),
        _cell("codex", "A3", "candidate", "b", "b" * 40),
    ),
    ids=("claude", "codex"),
)
def test_completed_job_delivery_accepts_expected_plugins_and_skill_directories(
    run_root: Path,
    cell: RunCell,
):
    _add_bundle(run_root, cell)
    if cell.provider == "claude":
        plugins: list[object] = [
            {"name": "provider-builtin"},
            {"name": "superpowers@superpowers-dev"},
            "harness@studio-moser",
        ]
        skills: list[object] = [
            "provider:built-in",
            "superpowers:using-superpowers",
            "harness:execute",
        ]
    else:
        plugins = [
            {
                "name": "provider-builtin",
                "pluginId": "provider-builtin@provider",
                "marketplaceName": "provider",
                "version": "1.0.0",
                "enabled": True,
                "installed": True,
            },
            _codex_inventory_record("superpowers"),
            _codex_inventory_record("harness"),
        ]
        skills = []
    _write_completed_job(
        run_root,
        cell,
        "valid-delivery",
        plugins=plugins,
        skills=skills,
    )

    assert Runs._completed_job_errors(
        run_root,
        cell,
        "valid-delivery",
        frozenset({"superpowers:using-superpowers", "harness:execute"}),
    ) == ()


def test_completed_job_delivery_rejects_a0_benchmark_contamination(run_root: Path):
    cell = _cell("claude", "A0", "baseline", "a")
    _add_bundle(run_root, cell)
    _write_completed_job(
        run_root,
        cell,
        "contaminated-delivery",
        plugins=["provider-builtin", "superpowers@superpowers-dev"],
        skills=["provider:built-in", "superpowers:using-superpowers"],
    )

    errors = Runs._completed_job_errors(
        run_root,
        cell,
        "contaminated-delivery",
        frozenset({"superpowers:using-superpowers", "harness:execute"}),
    )

    assert any("plugin" in error and "superpowers" in error for error in errors)
    assert any("skill" in error and "superpowers:using-superpowers" in error for error in errors)


def test_completed_job_delivery_rejects_missing_expected_a2_plugin(run_root: Path):
    cell = _cell("claude", "A2", "candidate", "a", "a" * 40)
    _add_bundle(run_root, cell)
    _write_completed_job(run_root, cell, "missing-delivery", plugins=[])

    errors = Runs._completed_job_errors(
        run_root,
        cell,
        "missing-delivery",
        frozenset({"harness:execute"}),
    )

    assert any("plugin" in error and "harness" in error for error in errors)


def test_completed_job_delivery_rejects_unselected_benchmark_skill_namespace(
    run_root: Path,
):
    baseline = _cell("claude", "A0", "baseline", "a")
    harness = _cell("claude", "A2", "candidate", "b", "b" * 40)
    for cell in (baseline, harness):
        _add_bundle(run_root, cell)
    benchmark_skill_names = Runs._benchmark_skill_names(
        run_root,
        (baseline, harness),
    )
    assert benchmark_skill_names == frozenset({"harness:execute"})
    _write_completed_job(
        run_root,
        baseline,
        "unselected-skill-delivery",
        skills=["provider:built-in", "superpowers:using-superpowers"],
    )

    errors = Runs._completed_job_errors(
        run_root,
        baseline,
        "unselected-skill-delivery",
        benchmark_skill_names,
    )

    assert any(
        "skill" in error and "superpowers:using-superpowers" in error
        for error in errors
    )


def test_completed_job_delivery_rejects_blank_benchmark_plugin_marketplace(
    run_root: Path,
):
    cell = _cell("claude", "A1", "candidate", "a")
    _add_bundle(run_root, cell)
    benchmark_skill_names = Runs._benchmark_skill_names(run_root, (cell,))
    _write_completed_job(
        run_root,
        cell,
        "blank-marketplace-delivery",
        plugins=["provider-builtin", "superpowers@"],
    )

    errors = Runs._completed_job_errors(
        run_root,
        cell,
        "blank-marketplace-delivery",
        benchmark_skill_names,
    )

    assert any("malformed benchmark plugin" in error for error in errors)


def test_completed_job_delivery_rejects_codex_a0_benchmark_contamination(
    run_root: Path,
):
    cell = _cell("codex", "A0", "baseline", "a")
    _add_bundle(run_root, cell)
    _write_completed_job(
        run_root,
        cell,
        "codex-contaminated-delivery",
        plugins=[_codex_inventory_record("harness")],
    )

    errors = Runs._completed_job_errors(
        run_root,
        cell,
        "codex-contaminated-delivery",
        frozenset(),
    )

    assert any("plugin" in error and "harness" in error for error in errors)


def test_completed_job_correctness_zero_passes_infrastructure(run_root: Path):
    cell = _cell("codex", "A0", "baseline", "a")
    _add_bundle(run_root, cell)
    _write_completed_job(run_root, cell, "correctness-zero", reward=0.0)

    assert Runs._completed_job_errors(
        run_root,
        cell,
        "correctness-zero",
        frozenset(),
    ) == ()


def test_completed_job_delivery_accepts_one_trial_per_attempt(run_root: Path):
    cell = _cell("codex", "A0", "baseline", "a")
    _add_bundle(run_root, cell)
    _write_completed_job(run_root, cell, "two-attempts", attempts=2)

    assert Runs._completed_job_errors(
        run_root,
        cell,
        "two-attempts",
        frozenset(),
    ) == ()


def test_completed_job_delivery_rejects_trial_exception(run_root: Path):
    cell = _cell("claude", "A0", "baseline", "a")
    _add_bundle(run_root, cell)
    _write_completed_job(
        run_root,
        cell,
        "exception-delivery",
        exception_info={"exception_type": "TimeoutError", "exception_message": "timed out"},
    )

    errors = Runs._completed_job_errors(
        run_root,
        cell,
        "exception-delivery",
        frozenset(),
    )

    assert any("trial exception" in error for error in errors)


def test_completed_job_delivery_rejects_missing_exception_evidence(run_root: Path):
    cell = _cell("codex", "A0", "baseline", "a")
    _add_bundle(run_root, cell)
    _write_completed_job(
        run_root,
        cell,
        "missing-exception-evidence",
        include_exception_info=False,
    )

    errors = Runs._completed_job_errors(
        run_root,
        cell,
        "missing-exception-evidence",
        Runs._benchmark_skill_names(run_root, (cell,)),
    )

    assert any("exception" in error and "missing" in error for error in errors)


def test_completed_job_delivery_rejects_malformed_benchmark_evidence_with_a_cap(
    run_root: Path,
):
    cell = _cell("claude", "A0", "baseline", "a")
    _add_bundle(run_root, cell)
    _write_completed_job(
        run_root,
        cell,
        "malformed-delivery",
        plugins=[{"display": "superpowers"} for _ in range(20)],
        skills=["provider:built-in"],
    )

    errors = Runs._completed_job_errors(
        run_root,
        cell,
        "malformed-delivery",
        frozenset({"superpowers:using-superpowers"}),
    )

    assert errors == tuple(
        "malformed-delivery: "
        f"Claude plugin entry {index} has malformed benchmark plugin evidence"
        for index in range(12)
    )


def test_completed_job_delivery_rejects_ambiguous_benchmark_evidence(
    run_root: Path,
):
    cell = _cell("claude", "A1", "candidate", "a")
    _add_bundle(run_root, cell)
    _write_completed_job(
        run_root,
        cell,
        "ambiguous-delivery",
        plugins=["superpowers", {"name": "superpowers@superpowers-dev"}],
    )

    errors = Runs._completed_job_errors(
        run_root,
        cell,
        "ambiguous-delivery",
        frozenset({"superpowers:using-superpowers"}),
    )

    assert any("ambiguous benchmark plugin superpowers" in error for error in errors)


def _stub_execution_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Runs, "validate_repository", lambda root: ())
    monkeypatch.setattr(Runs, "dockerfile_policy_errors", lambda root: ())
    monkeypatch.setattr(Runs, "require_current_image", lambda root, image: None)


def test_delivery_canary_stops_before_the_second_task(
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest = _compile_pair(run_root)
    _stub_execution_preflight(monkeypatch)
    calls: list[str] = []
    real_run = subprocess.run

    def fake_run(command, **kwargs):
        if tuple(command[:3]) != (sys.executable, "-m", "harbor.cli.main"):
            return real_run(command, **kwargs)
        job = load_job(Path(command[-1]))
        index = len(calls)
        calls.append(job.job_name)
        cell = manifest.cells[index % len(manifest.cells)]
        _write_completed_job(
            run_root,
            cell,
            job.job_name,
            plugins=[] if index == 1 else None,
        )

    monkeypatch.setattr(Runs.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="delivery canary failed"):
        Runs.execute_run(run_root, manifest.path, manifest.digest)

    assert calls == [
        load_job(manifest.path.parent / path).job_name
        for path in manifest.harbor_config_paths[:2]
    ]


def test_delivery_canary_correctness_zero_runs_every_task(
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest = _compile_pair(run_root)
    _stub_execution_preflight(monkeypatch)
    calls: list[str] = []
    real_run = subprocess.run

    def fake_run(command, **kwargs):
        if tuple(command[:3]) != (sys.executable, "-m", "harbor.cli.main"):
            return real_run(command, **kwargs)
        job = load_job(Path(command[-1]))
        index = len(calls)
        calls.append(job.job_name)
        cell = manifest.cells[index % len(manifest.cells)]
        _write_completed_job(run_root, cell, job.job_name, reward=0.0)

    monkeypatch.setattr(Runs.subprocess, "run", fake_run)

    Runs.execute_run(run_root, manifest.path, manifest.digest)

    assert calls == [
        load_job(manifest.path.parent / path).job_name
        for path in manifest.harbor_config_paths
    ]


def test_delivery_failure_after_canary_stops_immediately(
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest = _compile_pair(run_root)
    _stub_execution_preflight(monkeypatch)
    calls: list[str] = []
    real_run = subprocess.run

    def fake_run(command, **kwargs):
        if tuple(command[:3]) != (sys.executable, "-m", "harbor.cli.main"):
            return real_run(command, **kwargs)
        job = load_job(Path(command[-1]))
        index = len(calls)
        calls.append(job.job_name)
        cell = manifest.cells[index % len(manifest.cells)]
        _write_completed_job(
            run_root,
            cell,
            job.job_name,
            plugins=[] if index == 2 else None,
        )

    monkeypatch.setattr(Runs.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="job delivery failed"):
        Runs.execute_run(run_root, manifest.path, manifest.digest)

    assert calls == [
        load_job(manifest.path.parent / path).job_name
        for path in manifest.harbor_config_paths[:3]
    ]


def test_discovery_execution_writes_one_safe_observation_per_trial(
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cell = _cell("codex", "A2", "candidate", "a", "a" * 40)
    _add_bundle(run_root, cell)
    manifest = compile_run(
        run_root,
        profile="smoke",
        billing_mode="api",
        cells=(cell,),
        task_ids=("task-one",),
        max_sessions=5,
        max_budget_usd=Decimal("100"),
        attempts=5,
        skill_evaluation=SkillEvaluation("discovery", "harness:execute"),
    )
    _stub_execution_preflight(monkeypatch)
    real_run = subprocess.run

    def fake_run(command, **kwargs):
        if tuple(command[:3]) != (sys.executable, "-m", "harbor.cli.main"):
            return real_run(command, **kwargs)
        job = load_job(Path(command[-1]))
        _write_completed_job(
            run_root,
            cell,
            job.job_name,
            attempts=5,
            skill_invoked=True,
        )

    monkeypatch.setattr(Runs.subprocess, "run", fake_run)

    Runs.execute_run(run_root, manifest.path, manifest.digest)

    report = json.loads((manifest.path.parent / "Skill_Evaluation.json").read_text())
    assert report["aggregate"] == {
        "numerator": 5,
        "denominator": 5,
        "rate": 1.0,
    }
    assert len(report["trials"]) == 5
    assert {trial["invocation"] for trial in report["trials"]} == {"implicit"}


def test_generated_claude_jobs_follow_exact_arm_delivery_provenance(
    run_root: Path,
):
    manifest = _compile_claude_matrix(run_root)
    agents = [
        load_job(manifest.path.parent / path).agents[0]
        for path in manifest.harbor_config_paths
    ]
    a0_agent, a1_agent, a2_agent, a3_agent = agents

    assert a0_agent.import_path == "harness_testing.Claude_Agent:HarnessClaude"
    assert "plugin_dirs" not in a0_agent.kwargs
    assert a1_agent.kwargs["plugin_dirs"] == [
        "/harness-arm/claude/plugins/superpowers"
    ]
    assert a2_agent.kwargs["plugin_dirs"] == [
        "/harness-arm/claude/plugins/harness"
    ]
    assert a3_agent.kwargs["plugin_dirs"] == [
        "/harness-arm/claude/plugins/superpowers",
        "/harness-arm/claude/plugins/harness",
    ]
    assert all(agent.env == {} and agent.skills == [] for agent in agents)


def test_capability_manifest_round_trip_and_job_kwargs(run_root: Path):
    claude = _cell("claude", "A2", "candidate", "a", "a" * 40)
    codex = _cell("codex", "A2", "candidate", "b", "b" * 40)
    for cell in (claude, codex):
        _add_bundle(run_root, cell)
    evaluation = SkillEvaluation("capability", "harness:execute")

    manifest = compile_run(
        run_root,
        profile="smoke",
        billing_mode="subscription",
        cells=(claude, codex),
        task_ids=("task-one",),
        max_sessions=2,
        max_budget_usd=Decimal("0"),
        skill_evaluation=evaluation,
    )

    assert manifest.skill_evaluation == evaluation
    assert Runs.load_manifest(manifest.path).skill_evaluation == evaluation
    assert manifest.to_dict()["skill_evaluation"] == {
        "mode": "capability",
        "name": "harness:execute",
    }
    for path in manifest.harbor_config_paths:
        assert load_job(manifest.path.parent / path).agents[0].kwargs[
            "skill_invocation"
        ] == "harness:execute"
    assert "Skill evaluation: capability harness:execute" in Runs.format_plan(manifest)


def test_discovery_requires_five_attempts_and_keeps_job_prompt_unmodified(
    run_root: Path,
):
    cell = _cell("claude", "A2", "candidate", "a", "a" * 40)
    _add_bundle(run_root, cell)
    evaluation = SkillEvaluation("discovery", "harness:execute")

    with pytest.raises(ValueError, match="discovery.*five"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=4,
            max_budget_usd=Decimal("100"),
            attempts=4,
            skill_evaluation=evaluation,
        )

    manifest = compile_run(
        run_root,
        profile="smoke",
        billing_mode="api",
        cells=(cell,),
        task_ids=("task-one",),
        max_sessions=5,
        max_budget_usd=Decimal("100"),
        attempts=5,
        skill_evaluation=evaluation,
    )
    agent = load_job(
        manifest.path.parent / manifest.harbor_config_paths[0]
    ).agents[0]
    assert "skill_invocation" not in agent.kwargs


def test_skill_evaluation_rejects_a_skill_absent_from_any_selected_arm(
    run_root: Path,
):
    cell = _cell("codex", "A1", "candidate", "a")
    _add_bundle(run_root, cell)

    with pytest.raises(ValueError, match="does not expose skill harness:execute"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
            skill_evaluation=SkillEvaluation("capability", "harness:execute"),
        )


@pytest.mark.parametrize(
    ("description", "mutate"),
    [
        (
            "outside-provider-path",
            lambda provenance, bundle: provenance["delivery_surfaces"][0].update(
                {"path": "/outside/claude/plugins/superpowers"}
            ),
        ),
        (
            "wrong-layer-order",
            lambda provenance, bundle: provenance.update(
                {"layers": ["Studio Harness", "Superpowers"]}
            ),
        ),
        (
            "extra-a0-layer",
            lambda provenance, bundle: provenance.update(
                {
                    "layers": ["Superpowers"],
                    "delivery_surfaces": [
                        {
                            "layer": "Superpowers",
                            "surface": "claude-plugin-dir",
                            "path": "/harness-arm/claude/plugins/superpowers",
                            "capabilities": ["skills"],
                        }
                    ],
                }
            ),
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_delivery_provenance_rejects_invalid_arm_claims(
    run_root: Path, description: str, mutate
):
    arm = "A3" if description != "extra-a0-layer" else "A0"
    harness_commit = "a" * 40 if arm == "A3" else None
    cell = _cell("claude", arm, "candidate", "a", harness_commit)
    bundle = _add_bundle(run_root, cell)
    provenance_path = bundle / "Provenance.json"
    provenance = json.loads(provenance_path.read_text())
    mutate(provenance, bundle)
    provenance_path.write_text(json.dumps(provenance) + "\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="delivery"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_missing_host_directory(run_root: Path):
    cell = _cell("claude", "A1", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    shutil.rmtree(bundle / "claude" / "plugins" / "superpowers")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="delivery"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_unclaimed_a0_plugin(run_root: Path):
    cell = _cell("claude", "A0", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    (bundle / "claude" / "plugins" / "superpowers").mkdir(parents=True)
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="contamination"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_duplicate_targets(run_root: Path):
    cell = _cell("claude", "A3", "candidate", "a", "a" * 40)
    bundle = _add_bundle(run_root, cell)
    provenance_path = bundle / "Provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["delivery_surfaces"][1]["path"] = provenance["delivery_surfaces"][0][
        "path"
    ]
    shutil.rmtree(bundle / "claude" / "plugins" / "harness")
    provenance_path.write_text(json.dumps(provenance) + "\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="duplicate|canonical"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_renamed_in_root_path(run_root: Path):
    cell = _cell("claude", "A1", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    source = bundle / "claude" / "plugins" / "superpowers"
    renamed = source.with_name("renamed")
    source.rename(renamed)
    provenance_path = bundle / "Provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["delivery_surfaces"][0]["path"] = "/harness-arm/claude/plugins/renamed"
    provenance_path.write_text(json.dumps(provenance) + "\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="canonical"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


@pytest.mark.parametrize("capabilities", ([], None), ids=("wrong", "missing"))
def test_delivery_provenance_rejects_wrong_capabilities(
    run_root: Path, capabilities: object
):
    cell = _cell("claude", "A1", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    provenance_path = bundle / "Provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["delivery_surfaces"][0]["capabilities"] = capabilities
    provenance_path.write_text(json.dumps(provenance) + "\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="capabilities"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_codex_a0_provider_home(run_root: Path):
    cell = _cell("codex", "A0", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    provider_home = bundle / "codex" / "provider-home"
    provider_home.mkdir(parents=True)
    (provider_home / "config.toml").write_text("[marketplaces.injected]\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="Codex delivery contamination"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_renamed_codex_marketplace(run_root: Path):
    cell = _cell("codex", "A1", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    provider_home = bundle / "codex" / "provider-home"
    (provider_home / "plugins" / "cache" / "superpowers-dev").rename(
        provider_home / "plugins" / "cache" / "forged-marketplace"
    )
    (provider_home / "marketplaces" / "superpowers-dev").rename(
        provider_home / "marketplaces" / "forged-marketplace"
    )
    config_path = provider_home / "config.toml"
    config_path.write_text(
        config_path.read_text().replace("superpowers-dev", "forged-marketplace")
    )
    provenance_path = bundle / "Provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["delivery_surfaces"][0]["path"] = provenance["delivery_surfaces"][
        0
    ]["path"].replace("superpowers-dev", "forged-marketplace")
    provenance_path.write_text(json.dumps(provenance) + "\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="canonical"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_renamed_codex_version(run_root: Path):
    cell = _cell("codex", "A1", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    plugin = (
        bundle
        / "codex"
        / "provider-home"
        / "plugins"
        / "cache"
        / "superpowers-dev"
        / "superpowers"
    )
    version = plugin / "6.3.0"
    forged = plugin / "9.9.9"
    version.rename(forged)
    manifest_path = forged / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = "9.9.9"
    manifest_path.write_text(json.dumps(manifest) + "\n")
    provenance_path = bundle / "Provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["delivery_surfaces"][0]["path"] = provenance["delivery_surfaces"][
        0
    ]["path"].replace("6.3.0", "9.9.9")
    provenance_path.write_text(json.dumps(provenance) + "\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="canonical"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_unclaimed_project_instruction(run_root: Path):
    cell = _cell("claude", "A1", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    project = bundle / "project"
    project.mkdir()
    (project / "CLAUDE.md").write_text("unclaimed\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="project instruction"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_requires_harness_project_instruction(run_root: Path):
    cell = _cell("claude", "A2", "candidate", "a", "a" * 40)
    bundle = _add_bundle(run_root, cell)
    shutil.rmtree(bundle / "project")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="project instruction"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_coherently_edited_harness_instruction(
    run_root: Path,
):
    cell = _cell("claude", "A2", "candidate", "a", "a" * 40)
    bundle = _add_bundle(run_root, cell)
    template = (
        bundle
        / "claude"
        / "plugins"
        / "harness"
        / "templates"
        / "AGENTS_Baseline.md"
    )
    instruction = bundle / "project" / "CLAUDE.md"
    template.write_text("# Forged baseline\n")
    instruction.write_text("# Forged baseline\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="pinned Harness source"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_poisoned_reused_source_cache(
    run_root: Path,
):
    versions_path = run_root / "Versions.toml"
    versions = load_versions(versions_path)
    harness_repository = Path(
        next(
            source["url"]
            for source in versions["sources"]
            if source["name"] == "Studio Harness"
        )
    )
    versions_path.write_text(
        versions_path.read_text().replace(
            f"url = {json.dumps(str(harness_repository))}",
            f"url = {json.dumps(harness_repository.as_uri())}",
            1,
        )
    )
    cell = _cell("claude", "A2", "candidate", "a", "a" * 40)
    bundle = _add_bundle(run_root, cell)
    versions = load_versions(versions_path)
    harness_pin = next(
        source
        for source in versions["sources"]
        if source["name"] == "Studio Harness"
    )
    cached_source = _resolve_source_trees(
        run_root,
        _ARM_LAYERS[cell.arm],
        {
            "Studio Harness": (
                str(harness_pin["url"]),
                cell.harness_commit,
            )
        },
    )[0]
    forged_instruction = "# Forged cached baseline\n"
    (
        cached_source.path
        / "plugins"
        / "harness"
        / "templates"
        / "AGENTS_Baseline.md"
    ).write_text(forged_instruction)
    (
        bundle
        / "claude"
        / "plugins"
        / "harness"
        / "templates"
        / "AGENTS_Baseline.md"
    ).write_text(forged_instruction)
    (bundle / "project" / "CLAUDE.md").write_text(forged_instruction)
    provenance_path = bundle / "Provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["sources"][0]["source_tree_digest"] = _tree_digest(
        cached_source.path
    )
    provenance_path.write_text(json.dumps(provenance) + "\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="pinned source"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_rehashed_uninspected_plugin_payload(
    run_root: Path,
):
    cell = _cell("claude", "A1", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    payload_relative = (
        Path("claude")
        / "plugins"
        / "superpowers"
        / "skills"
        / "payload"
        / "SKILL.md"
    )
    payload = bundle / payload_relative
    payload.parent.mkdir()
    payload.write_text("# Approved payload\n")
    bundle = _reseal_bundle(cell, bundle)

    payload = bundle / payload_relative
    payload.write_text("# Replaced payload\n")
    provenance_path = bundle / "Provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["generated_file_digests"] = _file_digests(bundle)
    provenance_path.write_text(json.dumps(provenance) + "\n")

    with pytest.raises(ValueError, match="provenance digest"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


@pytest.mark.parametrize("component", ("arms", "provider", "arm", "bundle"))
def test_delivery_provenance_rejects_symlinked_materialized_ancestor(
    run_root: Path, component: str
):
    cell = _cell("claude", "A0", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    materialized = run_root / "arms" / "materialized"
    targets = {
        "arms": run_root / "arms",
        "provider": materialized / cell.provider,
        "arm": materialized / cell.provider / cell.arm,
        "bundle": bundle,
    }
    target = targets[component]
    escaped = run_root / "escaped" / component
    escaped.parent.mkdir(exist_ok=True)
    target.rename(escaped)
    target.symlink_to(escaped, target_is_directory=True)

    with pytest.raises(ValueError, match="materialized arm.*symlink"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_symlinked_provenance(run_root: Path):
    cell = _cell("claude", "A0", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    provenance = bundle / "Provenance.json"
    alias = bundle / "Provenance.alias.json"
    provenance.rename(alias)
    provenance.symlink_to(alias.name)

    with pytest.raises(ValueError, match="provenance.*symlink"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_symlinked_claude_plugin_manifest(run_root: Path):
    cell = _cell("claude", "A1", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    plugin = bundle / "claude" / "plugins" / "superpowers"
    manifest = plugin / ".claude-plugin" / "plugin.json"
    alias = plugin / "plugin-alias.json"
    alias.write_text(manifest.read_text())
    manifest.unlink()
    manifest.symlink_to("../plugin-alias.json")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="symlink"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_delivery_provenance_rejects_symlinked_codex_config(run_root: Path):
    cell = _cell("codex", "A1", "candidate", "a")
    bundle = _add_bundle(run_root, cell)
    config = bundle / "codex" / "provider-home" / "config.toml"
    alias = bundle / "config-alias.toml"
    alias.write_text(config.read_text())
    config.unlink()
    config.symlink_to(alias)
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="symlink"):
        compile_run(
            run_root,
            profile="smoke",
            billing_mode="api",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
        )


def test_generated_claude_plugin_seed_environment_is_rejected(run_root: Path):
    manifest = _compile_claude_matrix(run_root)
    relative_path = manifest.harbor_config_paths[0]
    path = manifest.path.parent / relative_path
    document = yaml.safe_load(path.read_text())
    document["agents"][0]["env"] = {
        "CLAUDE_CODE_PLUGIN_SEED_DIR": "/harness-arm/claude/plugin-seed"
    }
    text = yaml.safe_dump(document, sort_keys=False)
    path.write_text(text)
    manifest.provenance["harbor_config_digests"][relative_path] = Runs._sha256(
        text.encode()
    )

    with pytest.raises(ValueError, match="plugin seed"):
        _verify_generated_inputs(run_root, manifest)


def test_manifest_binds_selected_custom_agent_adapters(run_root: Path):
    claude = _cell("claude", "A0", "baseline", "a")
    codex = _cell("codex", "A0", "candidate", "b")
    for cell in (claude, codex):
        _add_bundle(run_root, cell)
    manifest = compile_run(
        run_root,
        profile="smoke",
        billing_mode="api",
        cells=(claude, codex),
        task_ids=("task-one",),
        max_sessions=2,
        max_budget_usd=Decimal("100"),
    )

    assert set(manifest.provenance["agent_adapter_digests"]) == {"claude", "codex"}
    adapter = run_root / "src" / "harness_testing" / "Claude_Agent.py"
    adapter.write_text("changed after approval\n")
    with pytest.raises(ValueError, match="agent adapter digest mismatch"):
        _verify_generated_inputs(run_root, manifest)


def test_single_provider_manifest_binds_both_custom_agent_adapters(run_root: Path):
    cell = _cell("claude", "A0", "candidate", "a")
    _add_bundle(run_root, cell)
    manifest = compile_run(
        run_root,
        profile="smoke",
        billing_mode="api",
        cells=(cell,),
        task_ids=("task-one",),
        max_sessions=1,
        max_budget_usd=Decimal("100"),
    )

    assert set(manifest.provenance["agent_adapter_digests"]) == {"claude", "codex"}
    adapter = run_root / "src" / "harness_testing" / "Codex_Agent.py"
    adapter.write_text("changed after approval\n")
    with pytest.raises(ValueError, match="agent adapter digest mismatch"):
        _verify_generated_inputs(run_root, manifest)


def test_manifest_binds_shared_skill_invocation_adapter_code(run_root: Path):
    cell = _cell("codex", "A2", "candidate", "a", "a" * 40)
    _add_bundle(run_root, cell)
    manifest = compile_run(
        run_root,
        profile="smoke",
        billing_mode="api",
        cells=(cell,),
        task_ids=("task-one",),
        max_sessions=1,
        max_budget_usd=Decimal("100"),
        skill_evaluation=SkillEvaluation("capability", "harness:execute"),
    )

    shared = run_root / "src" / "harness_testing" / "Skill_Evaluation.py"
    shared.write_text("changed after approval\n")

    with pytest.raises(ValueError, match="agent adapter digest mismatch"):
        _verify_generated_inputs(run_root, manifest)


def test_static_job_verification_uses_task_major_cell_order(run_root: Path):
    manifest = _compile_claude_matrix(run_root)
    reordered = replace(
        manifest,
        harbor_config_paths=tuple(reversed(manifest.harbor_config_paths)),
    )

    with pytest.raises(ValueError, match="order mismatch"):
        _verify_generated_inputs(run_root, reordered)


def test_static_job_verification_restarts_cells_for_each_task(run_root: Path):
    manifest = _compile_claude_matrix(run_root, ("task-one", "task-two"))
    paths = list(manifest.harbor_config_paths)
    paths[4], paths[5] = paths[5], paths[4]
    reordered = replace(manifest, harbor_config_paths=tuple(paths))

    with pytest.raises(ValueError, match="order mismatch"):
        _verify_generated_inputs(run_root, reordered)


def test_explicit_task_resolves_to_a_unique_pack_outside_profile_defaults(
    run_root: Path,
):
    task = run_root / "tasks" / "contract" / "contract-task"
    task.mkdir(parents=True)
    (task / "instruction.md").write_text("contract task\n")
    (task / "task.toml").write_text('schema_version = "1.4"\n')
    cell = _cell("codex", "A0", "baseline", "a")
    _add_bundle(run_root, cell)

    manifest = compile_run(
        run_root,
        profile="smoke",
        billing_mode="subscription",
        cells=(cell,),
        task_ids=("contract-task",),
        max_sessions=1,
        max_budget_usd=Decimal("0"),
    )

    assert set(manifest.provenance["task_digests"]) == {"contract/contract-task"}
    config = yaml.safe_load(
        (manifest.path.parent / manifest.harbor_config_paths[0]).read_text()
    )
    assert config["datasets"][0]["path"] == "tasks/contract"


@pytest.mark.parametrize(
    ("profile_packs", "task_packs", "expected"),
    (
        (("workflow",), ("contract", "workflow"), "workflow"),
        (("workflow",), (), None),
        (("contract", "workflow"), ("contract", "workflow"), None),
    ),
    ids=("profile-precedence", "missing", "ambiguous"),
)
def test_task_pack_resolution_is_explicit_and_deterministic(
    run_root: Path,
    profile_packs: tuple[str, ...],
    task_packs: tuple[str, ...],
    expected: str | None,
):
    task_id = "resolution-task"
    for pack in task_packs:
        task = run_root / "tasks" / pack / task_id
        task.mkdir(parents=True)
        (task / "task.toml").write_text('schema_version = "1.4"\n')
    profile = replace(Runs._load_profile(run_root, "smoke"), packs=profile_packs)

    if expected is None:
        with pytest.raises(ValueError, match="does not resolve"):
            Runs._task_pack(run_root, profile, task_id)
    else:
        assert Runs._task_pack(run_root, profile, task_id) == expected


@pytest.mark.parametrize(
    "boundary",
    ("arbitrary-pack", "task-directory-symlink", "task-toml-symlink"),
)
def test_task_pack_rejects_untrusted_local_candidates(
    run_root: Path,
    tmp_path: Path,
    boundary: str,
):
    task_id = "untrusted-task"
    if boundary == "arbitrary-pack":
        task = run_root / "tasks" / "arbitrary" / task_id
        task.mkdir(parents=True)
        (task / "task.toml").write_text('schema_version = "1.4"\n')
    elif boundary == "task-directory-symlink":
        external = tmp_path / "external-task"
        external.mkdir()
        (external / "task.toml").write_text('schema_version = "1.4"\n')
        task = run_root / "tasks" / "contract" / task_id
        task.parent.mkdir()
        task.symlink_to(external, target_is_directory=True)
    else:
        external = tmp_path / "external-task.toml"
        external.write_text('schema_version = "1.4"\n')
        task = run_root / "tasks" / "contract" / task_id
        task.mkdir(parents=True)
        (task / "task.toml").symlink_to(external)
    profile = Runs._load_profile(run_root, "smoke")

    with pytest.raises(ValueError, match="does not resolve"):
        Runs._task_pack(run_root, profile, task_id)


def test_manifest_digest_is_canonical_and_stable(run_root: Path):
    first = _compile_pair(run_root)
    second = _compile_pair(run_root)

    assert first.digest == second.digest
    assert first.digest.startswith("sha256:")
    assert len(first.digest) == 71


def test_manifest_is_stable_across_python_hash_seeds(run_root: Path):
    cell = _cell("claude", "A0", "baseline", "a")
    _add_bundle(run_root, cell)
    script = """
import json
import sys
from decimal import Decimal
from pathlib import Path

import yaml

from harness_testing.Runs import RunCell, compile_run

root = Path(sys.argv[1])
cell = RunCell(**json.loads(sys.argv[2]))
manifest = compile_run(
    root,
    profile="smoke",
    billing_mode="api",
    cells=(cell,),
    task_ids=("task-one",),
    max_sessions=1,
    max_budget_usd=Decimal("100"),
)
job_bytes = []
retry = []
for relative_path in manifest.harbor_config_paths:
    path = manifest.path.parent / relative_path
    job_bytes.append(path.read_bytes().hex())
    retry.append(yaml.safe_load(path.read_text())["retry"])
print(json.dumps({
    "run_id": manifest.provenance["run_id"],
    "manifest_digest": manifest.digest,
    "job_bytes": job_bytes,
    "retry": retry,
}, sort_keys=True))
"""

    results = []
    for seed in ("1", "2"):
        completed = subprocess.run(
            (sys.executable, "-c", script, str(run_root), json.dumps(cell.to_dict())),
            check=True,
            cwd=REPOSITORY_ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
        )
        results.append(json.loads(completed.stdout))

    assert results[0] == results[1]
    for retry in results[0]["retry"]:
        assert retry["include_exceptions"] == sorted(retry["include_exceptions"])
        assert retry["exclude_exceptions"] == sorted(retry["exclude_exceptions"])


def test_job_names_use_a_stable_run_id_that_changes_with_inputs(run_root: Path):
    first = _compile_pair(run_root)
    repeated = _compile_pair(run_root)
    task = run_root / "tasks" / "workflow" / "task-one" / "instruction.md"
    task.write_text("changed task one\n")
    changed = _compile_pair(run_root)

    first_run_id = first.provenance["run_id"]
    assert first_run_id == repeated.provenance["run_id"]
    assert first_run_id != changed.provenance["run_id"]
    assert first_run_id.startswith("run-")

    for manifest in (first, repeated, changed):
        run_id = manifest.provenance["run_id"]
        for relative_path in manifest.harbor_config_paths:
            config = yaml.safe_load(
                (manifest.path.parent / relative_path).read_text()
            )
            assert config["job_name"].startswith(f"{run_id}-")


def test_changed_manifest_is_rejected(run_root: Path):
    manifest = _compile_pair(run_root)
    document = manifest.to_dict()
    document["max_sessions"] = 99

    with pytest.raises(ValueError, match="digest"):
        verify_manifest_document(document)


def test_manifest_digest_binds_every_selected_task_tree(run_root: Path):
    first = _compile_pair(run_root)
    task = run_root / "tasks" / "workflow" / "task-one" / "instruction.md"
    task.write_text("changed task one\n")
    second = _compile_pair(run_root)

    assert first.provenance["task_digests"]["workflow/task-one"] != second.provenance[
        "task_digests"
    ]["workflow/task-one"]
    assert first.digest != second.digest


def test_execution_rejects_task_drift_after_manifest_approval(run_root: Path):
    manifest = _compile_pair(run_root)
    task = run_root / "tasks" / "workflow" / "task-one" / "instruction.md"
    task.write_text("changed after approval\n")

    with pytest.raises(ValueError, match="task digest mismatch"):
        _verify_generated_inputs(run_root, manifest)


def test_execution_rejects_codex_adapter_drift_after_manifest_approval(
    run_root: Path,
):
    cell = _cell("codex", "A0", "baseline", "c")
    _add_bundle(run_root, cell)
    manifest = compile_run(
        run_root,
        profile="smoke",
        billing_mode="subscription",
        cells=(cell,),
        task_ids=("task-one",),
        max_sessions=1,
        max_budget_usd=Decimal("0"),
    )
    adapter = run_root / "src" / "harness_testing" / "Codex_Agent.py"
    adapter.write_text("changed after approval\n")

    with pytest.raises(ValueError, match="agent adapter digest mismatch"):
        _verify_generated_inputs(run_root, manifest)


def test_manifest_and_execution_bind_selected_image_inputs(run_root: Path):
    approved = _compile_pair(run_root)
    approved_images = approved.provenance["image_input_digests"]
    assert set(approved_images) == {"node", "verifier"}

    decoder = run_root / "src" / "harness_testing" / "Trajectory_Events.py"
    decoder.write_text("changed after approval\n")
    changed = _compile_pair(run_root)

    assert approved_images["verifier"] != changed.provenance[
        "image_input_digests"
    ]["verifier"]
    assert approved.digest != changed.digest
    with pytest.raises(ValueError, match="image input digest mismatch"):
        _verify_generated_inputs(run_root, approved)


def test_cell_provenance_must_match_provider_arm_and_candidate_commit(run_root: Path):
    cell = _cell("codex", "A2", "candidate", "c", "3" * 40)
    bundle = _add_bundle(run_root, cell)
    provenance_path = bundle / "Provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["provider"] = "claude"
    provenance_path.write_text(json.dumps(provenance) + "\n")
    _reseal_bundle(cell, bundle)

    with pytest.raises(ValueError, match="arm provenance"):
        compile_run(
            run_root,
            profile="smoke",
            cells=(cell,),
            task_ids=("task-one",),
            max_sessions=1,
            max_budget_usd=Decimal("100"),
            billing_mode="api",
        )


def test_session_and_budget_admission_limits_are_enforced(run_root: Path):
    with pytest.raises(ValueError, match="4 sessions.*max_sessions 3"):
        _compile_pair(run_root, max_sessions=3)

    with pytest.raises(ValueError, match="estimated budget"):
        _compile_pair(run_root, max_budget_usd=Decimal("1"))


def test_subscription_manifest_binds_codex_auth_and_cost_semantics(run_root: Path):
    baseline = _cell("codex", "A0", "baseline", "c")
    candidate = _cell("codex", "A2", "candidate", "d", "3" * 40)
    _add_bundle(run_root, baseline)
    candidate_bundle = _add_bundle(run_root, candidate, skill_name="dev-task")
    candidate_skills = candidate_bundle / "skills"

    manifest = compile_run(
        run_root,
        profile="smoke",
        billing_mode="subscription",
        cells=(candidate, baseline),
        task_ids=("task-one",),
        max_sessions=2,
        max_budget_usd=Decimal("0"),
    )

    assert manifest.billing_mode == "subscription"
    assert manifest.estimated_budget_usd == Decimal("0")
    assert manifest.max_budget_usd == Decimal("0")
    assert manifest.api_equivalent_cost_usd == Decimal("6.4")
    assert manifest.provenance["budget_enforcement"] == (
        "subscription-only-no-api-fallback"
    )
    assert manifest.provenance["subscription_selectors"] == {
        "codex": {"name": "CODEX_FORCE_AUTH_JSON", "value": "1"}
    }
    loaded = Runs.load_manifest(manifest.path)
    assert loaded.billing_mode == "subscription"
    assert loaded.api_equivalent_cost_usd == Decimal("6.4")
    report = Runs.format_plan(manifest)
    assert "Billing mode: subscription (no API-key fallback)" in report
    assert "Expected incremental cost: $0 / $0" in report
    assert "API-equivalent usage estimate: $6.4" in report
    for relative_path in manifest.harbor_config_paths:
        config_path = manifest.path.parent / relative_path
        job = yaml.safe_load(config_path.read_text())
        agent = job["agents"][0]
        assert agent["import_path"] == "harness_testing.Codex_Agent:HarnessCodex"
        assert "name" not in agent
        assert agent.get("env", {}) == {}
        assert agent["extra_allowed_hosts"] == ["chatgpt.com", "auth.openai.com"]
        assert "OPENAI_API_KEY" not in json.dumps(job)
        assert "CODEX_FORCE_AUTH_JSON" not in config_path.read_text()
        assert load_job(config_path).agents[0].env == {}
    candidate_config = next(
        manifest.path.parent / path
        for path in manifest.harbor_config_paths
        if "candidate" in path
    )
    candidate_agent = load_job(candidate_config).agents[0]
    assert candidate_agent.import_path == "harness_testing.Codex_Agent:HarnessCodex"
    assert candidate_agent.name is None
    assert candidate_agent.skills == [str(candidate_skills)]
    assert [resolved.name for resolved in resolve_skills(candidate_agent.skills)] == [
        "dev-task"
    ]


def test_subscription_selector_is_scoped_to_the_harbor_process(
    run_root: Path, monkeypatch: pytest.MonkeyPatch
):
    cell = _cell("codex", "A0", "baseline", "e")
    _add_bundle(run_root, cell)
    manifest = compile_run(
        run_root,
        profile="smoke",
        billing_mode="subscription",
        cells=(cell,),
        task_ids=("task-one",),
        max_sessions=1,
        max_budget_usd=Decimal("0"),
    )
    auth_path = run_root / "codex-auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                },
            }
        )
    )
    monkeypatch.setenv("CODEX_AUTH_JSON_PATH", str(auth_path))
    monkeypatch.delenv("CODEX_FORCE_AUTH_JSON", raising=False)
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Runs, "validate_repository", lambda root: ())
    monkeypatch.setattr(Runs, "dockerfile_policy_errors", lambda root: ())
    monkeypatch.setattr(Runs, "require_current_image", lambda root, image: None)
    monkeypatch.setattr(Runs, "_completed_job_errors", lambda *args: ())
    calls: list[dict[str, object]] = []

    def fake_run(command, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(Runs.subprocess, "run", fake_run)

    Runs.execute_run(run_root, manifest.path, manifest.digest)

    assert len(calls) == 1
    child_environment = calls[0]["env"]
    assert isinstance(child_environment, dict)
    assert child_environment["CODEX_FORCE_AUTH_JSON"] == "1"
    assert "CODEX_FORCE_AUTH_JSON" not in Runs.os.environ


def test_subscription_and_api_budget_rules_are_distinct(run_root: Path):
    with pytest.raises(ValueError, match="subscription.*zero"):
        _compile_pair(
            run_root,
            billing_mode="subscription",
            max_budget_usd=Decimal("1"),
        )

    with pytest.raises(ValueError, match="API.*positive"):
        _compile_pair(run_root, billing_mode="api", max_budget_usd=Decimal("0"))


def test_codex_subscription_preflight_requires_chatgpt_auth_without_api_fallback(
    tmp_path: Path,
):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    auth_path = codex_home / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                },
            }
        )
    )
    cells = (_cell("codex", "A0", "baseline", "e"),)

    Runs._verify_subscription_auth(cells, {}, tmp_path)

    with pytest.raises(ValueError, match="OPENAI_API_KEY must be unset"):
        Runs._verify_subscription_auth(
            cells,
            {"OPENAI_API_KEY": "must-not-be-printed"},
            tmp_path,
        )
    with pytest.raises(ValueError, match="OPENAI_BASE_URL must be unset"):
        Runs._verify_subscription_auth(
            cells,
            {"OPENAI_BASE_URL": "https://example.invalid/v1"},
            tmp_path,
        )

    auth_path.write_text(json.dumps({"auth_mode": "apikey", "tokens": {}}))
    with pytest.raises(ValueError, match="ChatGPT subscription auth"):
        Runs._verify_subscription_auth(cells, {}, tmp_path)

    auth_path.unlink()
    with pytest.raises(ValueError, match="Codex subscription credential is missing"):
        Runs._verify_subscription_auth(cells, {}, tmp_path)


def test_timeout_and_paired_concurrency_are_explicit(run_root: Path):
    with pytest.raises(ValueError, match="timeout"):
        _compile_pair(run_root, agent_timeout_seconds=0)

    with pytest.raises(ValueError, match="paired runs require concurrency 1"):
        _compile_pair(run_root, concurrency=2)


def test_non_calibration_profile_cannot_request_the_full_arm_matrix(run_root: Path):
    cells = tuple(
        _cell("codex", arm, "candidate", str(index + 1))
        for index, arm in enumerate(("A0", "A1", "A2", "A3"))
    )
    cells = tuple(
        replace(cell, harness_commit="3" * 40) if cell.arm in {"A2", "A3"} else cell
        for cell in cells
    )
    for cell in cells:
        _add_bundle(run_root, cell)

    with pytest.raises(ValueError, match="calibration"):
        compile_run(
            run_root,
            profile="smoke",
            cells=cells,
            task_ids=("task-one",),
            max_sessions=4,
            max_budget_usd=Decimal("100"),
            billing_mode="api",
        )


def test_generated_jobs_never_serialize_process_credentials(
    run_root: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-serialize-this")
    manifest = _compile_pair(run_root)
    manifest_directory = manifest.path.parent
    output = "\n".join(
        (manifest_directory / path).read_text() for path in manifest.harbor_config_paths
    )

    assert "do-not-serialize-this" not in output
    assert "ANTHROPIC_API_KEY" not in output


def test_each_job_has_one_arm_mount_and_pairs_alternate(run_root: Path):
    manifest = _compile_pair(run_root)

    assert [path.split("-")[2] for path in manifest.harbor_config_paths] == [
        "baseline",
        "candidate",
        "baseline",
        "candidate",
    ]
    for relative_path in manifest.harbor_config_paths:
        config_path = manifest.path.parent / relative_path
        raw = yaml.safe_load(config_path.read_text())
        arm_mounts = [
            mount
            for mount in raw["environment"]["mounts"]
            if mount["target"] == "/harness-arm"
        ]
        assert len(arm_mounts) == 1
        assert arm_mounts[0]["read_only"] is True


def test_every_generated_job_round_trips_through_harbor(run_root: Path):
    manifest = _compile_pair(run_root)

    jobs = [
        load_job(manifest.path.parent / path) for path in manifest.harbor_config_paths
    ]
    assert len(jobs) == 4
    assert all(job.n_concurrent_trials == 1 for job in jobs)
    assert all(job.agents[0].override_timeout_sec == 900 for job in jobs)


def test_research_profile_uses_only_the_materialized_deepswe_dataset(
    run_root: Path, monkeypatch: pytest.MonkeyPatch
):
    task_id = DEEPSWE_TASK_IDS[0]
    dataset_digest = _digest("f")
    dataset = (
        run_root
        / ".cache"
        / "deepswe"
        / "datasets"
        / dataset_digest.removeprefix("sha256:")
    )
    task = dataset / "tasks" / task_id
    task.mkdir(parents=True)
    (task / "instruction.md").write_text("DeepSWE research task\n")
    materialized = MaterializedDeepSWE(path=dataset, digest=dataset_digest)
    monkeypatch.setattr(Runs, "load_deepswe_dataset", lambda root: materialized)
    cell = _cell("codex", "A0", "baseline", "e")
    _add_bundle(run_root, cell)

    manifest = compile_run(
        run_root,
        profile="research",
        billing_mode="subscription",
        cells=(cell,),
        task_ids=(task_id,),
        max_sessions=1,
        max_budget_usd=Decimal("0"),
    )

    config = yaml.safe_load(
        (manifest.path.parent / manifest.harbor_config_paths[0]).read_text()
    )
    assert len(config["datasets"]) == 1
    assert config["datasets"][0]["path"] == str(
        dataset.relative_to(run_root) / "tasks"
    )
    assert config["datasets"][0]["task_names"] == [task_id]
    assert manifest.provenance["task_digests"] == {
        f"research/{task_id}": Runs._tree_digest(task)
    }
    assert manifest.provenance["deepswe_dataset_digest"] == dataset_digest
    assert manifest.provenance["image_input_digests"] == {}
    _verify_generated_inputs(run_root, manifest)

    monkeypatch.setattr(
        Runs,
        "load_deepswe_dataset",
        lambda root: MaterializedDeepSWE(path=dataset, digest=_digest("a")),
    )
    with pytest.raises(ValueError, match="DeepSWE dataset digest mismatch"):
        _verify_generated_inputs(run_root, manifest)
