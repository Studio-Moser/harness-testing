import json
import os
import subprocess
from pathlib import Path

import pytest

from harness_testing.Submission import capture_submission, submission_problem


def git(repo, *args, **kwargs):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, **kwargs
    ).stdout


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "Tracked.txt").write_text("base\n")
    (path / ".gitignore").write_text("ignored/\n.worktrees/\n")
    git(path, "add", ".")
    git(path, "commit", "-qm", "base")
    return path, git(path, "rev-parse", "HEAD").decode().strip()


def capture(tmp_path, repo, base):
    trial = tmp_path / "trial"
    patch = trial / "artifacts/logs/artifacts/model.patch"
    result = capture_submission(repo, base, patch, trial / "agent/Submission")
    return result, patch


def apply_snapshot(tmp_path, repo, base, patch):
    clone = tmp_path / "verification"
    git(repo, "clone", "-q", "--no-hardlinks", str(repo), str(clone))
    git(clone, "checkout", "--detach", base)
    git(clone, "apply", "--binary", str(patch))
    return clone


@pytest.mark.parametrize("mode", ["committed", "staged", "unstaged", "linked"])
def test_captures_actual_tree_without_changing_git_state(tmp_path, repo, mode):
    primary, base = repo
    work = primary
    if mode == "linked":
        work = primary / ".worktrees/Feature with spaces"
        git(primary, "worktree", "add", "-qb", "feature", str(work))
    (work / "Tracked.txt").write_text("changed\n")
    (work / "New é\tfile.txt").write_text("new\n")
    (work / "Binary.bin").write_bytes(bytes(range(256)))
    (work / "Executable.sh").write_text("#!/bin/sh\n")
    (work / "Executable.sh").chmod(0o755)
    (work / "ignored").mkdir()
    (work / "ignored/private.txt").write_text("not a submission\n")
    if mode in {"committed", "staged"}:
        git(work, "add", ".")
    if mode == "committed":
        git(work, "commit", "-qm", "change")
        (work / "Tracked.txt").write_text("changed again\n")
    before = git(work, "status", "--porcelain=v1", "-z")
    index = Path(os.fsdecode(git(work, "rev-parse", "--git-path", "index").strip()))
    index = work / index
    index_bytes = index.read_bytes()
    head = git(work, "rev-parse", "HEAD")
    record, patch = capture(tmp_path, primary, base)
    assert record["status"] == "captured", record
    assert git(work, "rev-parse", "HEAD") == head
    assert index.read_bytes() == index_bytes
    assert git(work, "status", "--porcelain=v1", "-z") == before
    target = apply_snapshot(tmp_path, primary, base, patch)
    for name in ["Tracked.txt", "New é\tfile.txt", "Binary.bin", "Executable.sh"]:
        assert (target / name).read_bytes() == (work / name).read_bytes()
    assert (target / "Executable.sh").stat().st_mode & 0o111
    assert not (target / "ignored").exists()


def test_deletions_and_symlinks_are_captured_without_dereferencing(tmp_path, repo):
    primary, base = repo
    (primary / "Tracked.txt").unlink()
    (primary / "Link").symlink_to(tmp_path / "missing-private-file")
    record, patch = capture(tmp_path, primary, base)
    assert record["status"] == "captured"
    target = apply_snapshot(tmp_path, primary, base, patch)
    assert not (target / "Tracked.txt").exists()
    assert (target / "Link").is_symlink()
    assert os.readlink(target / "Link") == os.readlink(primary / "Link")


def test_ambiguous_worktrees_keep_candidates_but_never_an_empty_submission(tmp_path, repo):
    primary, base = repo
    other = tmp_path / "other"
    git(primary, "worktree", "add", "-qb", "feature", str(other))
    (primary / "Tracked.txt").write_text("first\n")
    (other / "Tracked.txt").write_text("second\n")
    record, patch = capture(tmp_path, primary, base)
    assert record["status"] == "failed"
    assert record["reason"] == "submission_ambiguous_worktrees"
    assert not patch.exists()
    assert len(record["candidates"]) == 2
    assert all(
        (tmp_path / "trial/agent/Submission" / c["patch"]).is_file() for c in record["candidates"]
    )


def test_identical_worktrees_and_genuine_noop_are_unambiguous(tmp_path, repo):
    primary, base = repo
    record, patch = capture(tmp_path, primary, base)
    assert record["status"] == "captured" and patch.read_bytes() == b""
    other = tmp_path / "other"
    git(primary, "worktree", "add", "-qb", "feature", str(other))
    for work in (primary, other):
        (work / "Tracked.txt").write_text("same\n")
    record, patch = capture(tmp_path, primary, base)
    assert record["status"] == "captured" and b"+same" in patch.read_bytes()


def test_snapshot_does_not_execute_clean_filters_or_modify_source_objects(tmp_path, repo):
    primary, base = repo
    (primary / ".gitattributes").write_text("*.txt filter=evil diff=evil\n")
    marker = tmp_path / "filter-ran"
    git(primary, "config", "filter.evil.clean", f"touch '{marker}'; cat")
    git(primary, "config", "diff.external", f"touch '{marker}'")
    git(primary, "config", "diff.evil.textconv", f"touch '{marker}'")
    (primary / "Tracked.txt").write_text("raw\n")
    objects = sorted((primary / ".git/objects").rglob("*"))
    record, patch = capture(tmp_path, primary, base)
    assert record["status"] == "captured" and b"+raw" in patch.read_bytes()
    assert not marker.exists()
    assert sorted((primary / ".git/objects").rglob("*")) == objects


def test_receipt_rejects_missing_failed_or_overwritten_patch_and_preserves_legacy(tmp_path, repo):
    primary, base = repo
    task = tmp_path / "task"
    task.mkdir()
    assert submission_problem(task, None) is None
    (task / "Submission Contract.json").write_text(
        json.dumps(
            {
                "protocol": "worktree-snapshot-v1",
                "base_commit": base,
            }
        )
    )
    assert submission_problem(task, None) == "submission_capture_missing"
    record, patch = capture(tmp_path, primary, base)
    trial = tmp_path / "trial"
    assert submission_problem(task, trial) is None
    patch.write_text("overwritten")
    assert submission_problem(task, trial) == "submission_patch_mismatch"
    record["status"] = "failed"
    (trial / "agent/Submission/Submission.json").write_text(json.dumps(record))
    assert submission_problem(task, trial) == "submission_capture_failed"


@pytest.mark.parametrize("status", ["completed", "timeout"])
@pytest.mark.parametrize("broken", [None, "missing", "overwritten", "failed", "candidate"])
def test_report_does_not_score_a_broken_capture_as_noop(tmp_path, repo, status, broken):
    from harness_testing.Experiment_Reports import _safe_trial

    primary, base = repo
    task = tmp_path / "task"
    task.mkdir()
    (task / "Submission Contract.json").write_text(
        json.dumps(
            {
                "protocol": "worktree-snapshot-v1",
                "base_commit": base,
            }
        )
    )
    record, patch = capture(tmp_path, primary, base)
    trial = tmp_path / "trial"
    receipt = trial / "agent/Submission/Submission.json"
    if broken == "missing":
        receipt.unlink()
    elif broken == "overwritten":
        patch.write_text("wrong patch")
    elif broken == "failed":
        record["status"] = "failed"
        receipt.write_text(json.dumps(record))
    elif broken == "candidate":
        (trial / "agent/Submission/Candidate-1.patch").write_text("altered candidate")
    (trial / "agent/Trial_Evidence.json").write_text(json.dumps({"status": status}))
    (trial / "verifier").mkdir()
    (trial / "verifier/reward.json").write_text('{"reward": 1}')
    result = _safe_trial(
        Path(__file__).parents[2],
        "task",
        "contender",
        1,
        trial,
        task_variant="deepswe",
        task_path=task,
    )
    assert result["status"] == (
        "infrastructure_failure" if broken and status == "completed" else status
    )
    assert result["correctness"] is (None if broken else True)
    assert bool(result["incomplete_reasons"]) is bool(broken)


def test_missing_native_capture_cannot_certify_a_verifier_reward(tmp_path):
    from harness_testing.Experiment_Reports import _safe_trial

    task = tmp_path / "task"
    task.mkdir()
    (task / "Submission Contract.json").write_text(
        json.dumps(
            {
                "protocol": "worktree-snapshot-v1",
                "base_commit": "a" * 40,
            }
        )
    )
    trial = tmp_path / "trial"
    (trial / "verifier").mkdir(parents=True)
    (trial / "verifier/reward.json").write_text('{"reward": 1}')
    result = _safe_trial(
        Path(__file__).parents[2],
        "task",
        "contender",
        1,
        trial,
        task_variant="deepswe",
        task_path=task,
    )
    assert result["status"] == "infrastructure_failure"
    assert result["correctness"] is None
    assert "submission_capture_missing" in result["incomplete_reasons"]


@pytest.fixture
def submodule_repo(tmp_path, repo):
    primary, _ = repo
    source = tmp_path / "dependency"
    git(primary, "clone", "-q", str(primary), str(source))
    git(
        primary,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(source),
        "vendor/Dependency with spaces",
    )
    git(primary, "commit", "-qam", "submodule baseline")
    return primary, git(primary, "rev-parse", "HEAD").decode().strip()


@pytest.mark.parametrize("initialized", [True, False])
def test_unchanged_gitlinks_survive_snapshot_without_source_mutation(
    tmp_path,
    submodule_repo,
    initialized,
):
    primary, base = submodule_repo
    if not initialized:
        git(primary, "submodule", "deinit", "-f", "--all")
    (primary / "Tracked.txt").write_text("changed\n")
    before = git(primary, "status", "--porcelain=v1", "-z")
    index = (primary / ".git/index").read_bytes()
    record, patch = capture(tmp_path, primary, base)
    assert record["status"] == "captured", record
    assert b"+changed" in patch.read_bytes()
    assert b"vendor/Dependency" not in patch.read_bytes()
    assert git(primary, "status", "--porcelain=v1", "-z") == before
    assert (primary / ".git/index").read_bytes() == index
    target = apply_snapshot(tmp_path, primary, base, patch)
    assert git(target, "ls-files", "--stage", "vendor") == git(
        primary,
        "ls-files",
        "--stage",
        "vendor",
    )


@pytest.mark.parametrize("change", ["dirty", "untracked", "commit", "staged", "removed", "symlink"])
def test_submodule_changes_fail_closed_instead_of_disappearing(tmp_path, submodule_repo, change):
    primary, base = submodule_repo
    submodule = primary / "vendor/Dependency with spaces"
    if change == "removed":
        git(primary, "rm", "-q", "-f", "vendor/Dependency with spaces")
    elif change == "symlink":
        git(primary, "submodule", "deinit", "-f", "--all")
        submodule.rmdir()
        submodule.symlink_to(tmp_path / "dependency", target_is_directory=True)
    else:
        (submodule / ("New.txt" if change == "untracked" else "Tracked.txt")).write_text("dirty\n")
        if change in {"commit", "staged"}:
            git(
                submodule,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qam",
                "changed",
            )
        if change == "staged":
            git(primary, "add", "vendor")
    record, patch = capture(tmp_path, primary, base)
    assert record["reason"] == "submission_submodule_changed", record
    assert not patch.exists()
