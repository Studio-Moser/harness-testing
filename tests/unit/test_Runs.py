import json
import shutil
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from harbor.skills import resolve_skills

import harness_testing.Runs as Runs
from harness_testing.Config import load_job
from harness_testing.Materialize import DEEPSWE_TASK_IDS, MaterializedDeepSWE
from harness_testing.Runs import (
    RunCell,
    _verify_generated_inputs,
    compile_run,
    verify_manifest_document,
)

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


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    shutil.copy(REPOSITORY_ROOT / "Versions.toml", tmp_path / "Versions.toml")
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
    for relative in (
        "images/Node_Agent.Dockerfile",
        "images/Verifier.Dockerfile",
        "src/harness_testing/Codex_Agent.py",
        "src/harness_testing/__init__.py",
        "src/harness_testing/Contract_Criteria.py",
        "src/harness_testing/Contract_Stub_Server.py",
        "src/harness_testing/Trajectory_Events.py",
        "src/harness_testing/Workflow_Criteria.py",
    ):
        source = REPOSITORY_ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return tmp_path


def _add_bundle(root: Path, cell: RunCell) -> Path:
    path = (
        root
        / "arms"
        / "materialized"
        / cell.provider
        / cell.arm
        / cell.bundle_digest.removeprefix("sha256:")
    )
    path.mkdir(parents=True, exist_ok=True)
    sources = (
        [{"name": "Studio Harness", "commit": cell.harness_commit}]
        if cell.harness_commit
        else []
    )
    (path / "Provenance.json").write_text(
        json.dumps(
            {
                "provider": cell.provider,
                "arm": cell.arm,
                "sources": sources,
                "bundle_digest": cell.bundle_digest,
            }
        )
        + "\n"
    )
    return path


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


def test_manifest_digest_is_canonical_and_stable(run_root: Path):
    first = _compile_pair(run_root)
    second = _compile_pair(run_root)

    assert first.digest == second.digest
    assert first.digest.startswith("sha256:")
    assert len(first.digest) == 71


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
    candidate_bundle = _add_bundle(run_root, candidate)
    candidate_skills = candidate_bundle / "skills"
    skill = candidate_skills / "dev-task"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Dev task\n")

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
