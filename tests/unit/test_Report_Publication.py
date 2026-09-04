import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import harness_testing.CLI as CLI
import harness_testing.Report_Publication as Report_Publication
from harness_testing.Report_Publication import (
    PublicationTarget,
    load_publication_target,
    pending_run_reports,
    publication_manifest_record,
    publish_run_reports,
)
from harness_testing.Run_Reports import run_report_id

REPOSITORY_ROOT = Path(__file__).parents[2]
RUN_REPORT_FIXTURE = REPOSITORY_ROOT / "tests" / "Fixtures" / "Run_Reports" / "Valid.json"
TEST_TARGET = PublicationTarget(
    repository="Studio-Moser/harness-testing",
    data_branch="dashboard-data",
    workflow="Publish_Pages.yml",
    code_ref="main",
)


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repository), *arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repository: Path, message: str) -> None:
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", message)


def _initialized_repositories(tmp_path: Path) -> tuple[Path, Path]:
    caller = tmp_path / "caller"
    caller.mkdir()
    _git(caller, "init", "--initial-branch=main")
    _git(caller, "config", "user.name", "Harness Test")
    _git(caller, "config", "user.email", "harness@example.invalid")
    (caller / ".gitignore").write_text("runs/history/\nruns/generated/\n")
    (caller / "Versions.toml").write_text(
        '[repository]\nschema_version = "0.3.0"\n'
    )
    (caller / "policy").mkdir()
    shutil.copyfile(
        REPOSITORY_ROOT / "policy" / "Run_Report.schema.json",
        caller / "policy" / "Run_Report.schema.json",
    )
    shutil.copyfile(
        REPOSITORY_ROOT / "policy" / "Dashboard_Publication.toml",
        caller / "policy" / "Dashboard_Publication.toml",
    )
    _commit(caller, "fixture caller")

    remote = tmp_path / "remote.git"
    subprocess.run(
        ("git", "init", "--bare", "--initial-branch=dashboard-data", str(remote)),
        check=True,
        capture_output=True,
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "--initial-branch=dashboard-data")
    _git(seed, "config", "user.name", "Harness Test")
    _git(seed, "config", "user.email", "harness@example.invalid")
    (seed / "README.md").write_text("# Dashboard data\n")
    _commit(seed, "bootstrap")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "origin", "dashboard-data")
    return caller, remote


def _write_report(
    caller: Path,
    index: int,
    *,
    run_id: str | None = None,
    updated_at: str | None = None,
) -> Path:
    document = json.loads(RUN_REPORT_FIXTURE.read_text())
    document["run_id"] = run_id or f"run-{index:020x}"
    document["manifest_digest"] = f"sha256:{index:064x}"
    document["jobs"][0]["name"] = f"published-job-{index}"
    if updated_at is not None:
        document["updated_at"] = updated_at
        document["finished_at"] = updated_at
    document["report_id"] = run_report_id(document)
    output = caller / "runs" / "history" / f"report-{index}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document) + "\n")
    return output


def _write_live_report(
    caller: Path,
    index: int,
    publication: dict[str, str] | None,
) -> Path:
    run_id = f"run-{index:020x}"
    provenance: dict[str, object] = {"run_id": run_id}
    if publication is not None:
        provenance["report_publication"] = publication
    manifest: dict[str, object] = {"provenance": provenance}
    manifest["digest"] = "sha256:" + hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    output = caller / "runs" / "generated" / f"live-{index}" / "Run_Report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    (output.parent / "Manifest.json").write_text(json.dumps(manifest) + "\n")

    document = json.loads(RUN_REPORT_FIXTURE.read_text())
    document["run_id"] = run_id
    document["manifest_digest"] = manifest["digest"]
    document["jobs"][0]["name"] = f"live-job-{index}"
    document["report_id"] = run_report_id(document)
    output.write_text(json.dumps(document) + "\n")
    return output


def _recording_runner(
    remote: Path,
    calls: list[tuple[str, ...]],
    dispatches: list[tuple[str, str]],
    *,
    fail_push: bool = False,
    conflict_once: bool = False,
    fail_dispatch: bool = False,
):
    conflict_pending = conflict_once

    def runner(arguments: tuple[str, ...], **kwargs: object):
        nonlocal conflict_pending
        command = tuple(arguments)
        calls.append(command)
        if command[:3] == ("gh", "auth", "status"):
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ("gh", "repo", "clone"):
            clone = (
                "git",
                "clone",
                "--quiet",
                "--branch",
                "dashboard-data",
                "--single-branch",
                str(remote),
                command[4],
            )
            return subprocess.run(clone, **kwargs)
        if command[:3] == ("gh", "workflow", "run"):
            if fail_dispatch:
                raise subprocess.CalledProcessError(
                    1,
                    command,
                    stderr="dispatch unavailable",
                )
            dispatches.append((command[3], command[-1]))
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "git" and "push" in command and fail_push:
            raise subprocess.CalledProcessError(
                1,
                command,
                stderr="push rejected",
            )
        if command[0] == "git" and "push" in command and conflict_pending:
            conflict_pending = False
            raise subprocess.CalledProcessError(
                1,
                command,
                stderr="[rejected] dashboard-data -> dashboard-data (fetch first)",
            )
        return subprocess.run(command, **kwargs)

    return runner


def test_publication_policy_loads_one_fixed_target():
    target = load_publication_target(REPOSITORY_ROOT)

    assert target == PublicationTarget(
        repository="Studio-Moser/harness-testing",
        data_branch="dashboard-data",
        workflow="Publish_Pages.yml",
        code_ref="main",
    )
    assert publication_manifest_record(target) == {
        "mode": "public",
        "repository": "Studio-Moser/harness-testing",
        "data_branch": "dashboard-data",
        "workflow": "Publish_Pages.yml",
        "code_ref": "main",
    }


@pytest.mark.parametrize(
    "replacement",
    [
        'repository = "not-a-repository"',
        'data_branch = "../dashboard-data"',
        'workflow = "../Publish_Pages.yml"',
        'code_ref = "feature/public-run-history"',
        'extra = "not-allowed"',
    ],
)
def test_publication_policy_rejects_untrusted_targets(
    tmp_path: Path,
    replacement: str,
):
    policy = tmp_path / "policy"
    policy.mkdir()
    text = (REPOSITORY_ROOT / "policy" / "Dashboard_Publication.toml").read_text()
    key = replacement.split(" =", 1)[0]
    if key == "extra":
        text += replacement + "\n"
    else:
        text = "\n".join(
            replacement if line.startswith(f"{key} =") else line
            for line in text.splitlines()
        )
    (policy / "Dashboard_Publication.toml").write_text(text + "\n")

    with pytest.raises(ValueError, match="publication policy"):
        load_publication_target(tmp_path)


def test_publish_batches_reports_without_dirtying_caller(tmp_path: Path):
    caller, remote = _initialized_repositories(tmp_path)
    report_paths = (_write_report(caller, 1), _write_report(caller, 2))
    calls: list[tuple[str, ...]] = []
    dispatches: list[tuple[str, str]] = []
    before = _git(caller, "status", "--porcelain")

    receipts = publish_run_reports(
        caller,
        report_paths,
        TEST_TARGET,
        runner=_recording_runner(remote, calls, dispatches),
    )

    assert len(receipts) == 2
    assert _git(caller, "status", "--porcelain") == before
    assert len(_git(remote, "rev-list", "dashboard-data").splitlines()) == 2
    assert dispatches == [("Publish_Pages.yml", "main")]
    assert not any("--force" in argument for command in calls for argument in command)
    assert pending_run_reports(caller) == ()


def test_older_report_cannot_replace_newer_remote_report(tmp_path: Path):
    caller, remote = _initialized_repositories(tmp_path)
    calls: list[tuple[str, ...]] = []
    dispatches: list[tuple[str, str]] = []
    runner = _recording_runner(remote, calls, dispatches)
    run_id = "run-aaaaaaaaaaaaaaaaaaaa"
    newer = _write_report(
        caller,
        1,
        run_id=run_id,
        updated_at="2026-09-04T20:00:00Z",
    )
    publish_run_reports(caller, (newer,), TEST_TARGET, runner=runner)
    older = _write_report(
        caller,
        2,
        run_id=run_id,
        updated_at="2026-09-03T20:00:00Z",
    )

    with pytest.raises(ValueError, match="older than published report"):
        publish_run_reports(caller, (older,), TEST_TARGET, runner=runner)


def test_failed_publish_leaves_report_pending(tmp_path: Path):
    caller, remote = _initialized_repositories(tmp_path)
    report_path = _write_report(caller, 1)
    calls: list[tuple[str, ...]] = []
    dispatches: list[tuple[str, str]] = []

    with pytest.raises(ValueError, match="could not publish"):
        publish_run_reports(
            caller,
            (report_path,),
            TEST_TARGET,
            runner=_recording_runner(
                remote,
                calls,
                dispatches,
                fail_push=True,
            ),
        )

    assert pending_run_reports(caller) == (report_path,)
    assert dispatches == []


def test_pending_reports_include_only_live_runs_bound_to_publication_target(
    tmp_path: Path,
):
    caller, _ = _initialized_repositories(tmp_path)
    public = _write_live_report(caller, 1, publication_manifest_record(TEST_TARGET))
    _write_live_report(caller, 2, {"mode": "local-only"})
    _write_live_report(caller, 3, None)

    assert pending_run_reports(caller) == (public,)


@pytest.mark.parametrize("publication", [None, {"mode": "local-only"}])
def test_publish_rejects_live_report_without_exact_publication_binding(
    tmp_path: Path,
    publication: dict[str, str] | None,
):
    caller, _ = _initialized_repositories(tmp_path)
    report = _write_live_report(caller, 1, publication)

    with pytest.raises(ValueError, match="publication binding"):
        publish_run_reports(caller, (report,), TEST_TARGET)


def test_filesystem_failure_is_reported_as_retryable_publication_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    caller, remote = _initialized_repositories(tmp_path)
    report = _write_report(caller, 1)
    calls: list[tuple[str, ...]] = []
    dispatches: list[tuple[str, str]] = []

    def fail_checkout(*args: object, **kwargs: object):
        raise OSError("filesystem unavailable")

    monkeypatch.setattr(Report_Publication, "_publish_once", fail_checkout)

    with pytest.raises(ValueError, match="local filesystem"):
        publish_run_reports(
            caller,
            (report,),
            TEST_TARGET,
            runner=_recording_runner(remote, calls, dispatches),
        )

    assert pending_run_reports(caller) == (report,)
    assert dispatches == []


def test_non_fast_forward_retries_with_one_fresh_clone(tmp_path: Path):
    caller, remote = _initialized_repositories(tmp_path)
    report_path = _write_report(caller, 1)
    calls: list[tuple[str, ...]] = []
    dispatches: list[tuple[str, str]] = []

    receipts = publish_run_reports(
        caller,
        (report_path,),
        TEST_TARGET,
        runner=_recording_runner(
            remote,
            calls,
            dispatches,
            conflict_once=True,
        ),
    )

    assert len(receipts) == 1
    assert sum(command[:3] == ("gh", "repo", "clone") for command in calls) == 2
    assert dispatches == [("Publish_Pages.yml", "main")]


def test_failed_workflow_dispatch_keeps_the_pushed_report_pending(tmp_path: Path):
    caller, remote = _initialized_repositories(tmp_path)
    report_path = _write_report(caller, 1)
    calls: list[tuple[str, ...]] = []
    dispatches: list[tuple[str, str]] = []

    with pytest.raises(ValueError, match="dispatch Pages workflow"):
        publish_run_reports(
            caller,
            (report_path,),
            TEST_TARGET,
            runner=_recording_runner(
                remote,
                calls,
                dispatches,
                fail_dispatch=True,
            ),
        )

    assert len(_git(remote, "rev-list", "dashboard-data").splitlines()) == 2
    assert pending_run_reports(caller) == (report_path,)


def test_report_sync_with_no_pending_reports_is_model_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    caller, _ = _initialized_repositories(tmp_path)
    monkeypatch.setattr(CLI, "_repository_root", lambda: caller)

    assert CLI.main(["report", "sync"]) == 0
    assert capsys.readouterr().out == "No public run reports are pending.\n"
