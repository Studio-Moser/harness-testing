"""Model-free snapshots of research submissions, without changing agents' Git state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

PROTOCOL = "worktree-snapshot-v1"


def submission_problem(task: Path, trial: Path | None) -> str | None:
    """Require new-contract receipts; historical tasks retain their old contract."""
    contract = task / "Submission Contract.json"
    if not contract.is_file():
        return None
    if trial is None:
        return "submission_capture_missing"
    try:
        expected = json.loads(contract.read_text())
        receipt = json.loads((trial / "agent/Submission/Submission.json").read_text())
        if expected != {"protocol": PROTOCOL, "base_commit": receipt["base_commit"]}:
            return "submission_capture_invalid"
        if receipt["protocol"] != PROTOCOL or receipt["status"] != "captured":
            return "submission_capture_failed"
        candidates = receipt["candidates"]
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 32:
            return "submission_capture_invalid"
        changed = set()
        for index, candidate in enumerate(candidates):
            if candidate["patch"] != f"Candidate-{index + 1}.patch":
                return "submission_capture_invalid"
            content = (trial / "agent/Submission" / candidate["patch"]).read_bytes()
            digest = "sha256:" + hashlib.sha256(content).hexdigest()
            if candidate["digest"] != digest or candidate["bytes"] != len(content):
                return "submission_capture_invalid"
            if content:
                changed.add(digest)
        selected = next(iter(changed), "sha256:" + hashlib.sha256(b"").hexdigest())
        if len(changed) > 1 or receipt["patch_digest"] != selected:
            return "submission_capture_invalid"
        patch = trial / "artifacts/logs/artifacts/model.patch"
        digest = "sha256:" + hashlib.sha256(patch.read_bytes()).hexdigest()
        if digest != receipt["patch_digest"]:
            return "submission_patch_mismatch"
    except (OSError, ValueError, KeyError, TypeError):
        return "submission_capture_missing"
    return None


def _git(worktree, *args, env=None, data=None):
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-C", str(worktree), *args],
        input=data,
        capture_output=True,
        check=True,
        timeout=30,
        env=env,
    ).stdout


def _snapshot(worktree, base, worktrees, scratch):
    # A private object store and index avoid staging, committing, clean filters,
    # or changing any object/index/ref in the agent's repository.
    objects = scratch / "objects"
    objects.mkdir()
    original_objects = _git(worktree, "rev-parse", "--git-path", "objects").decode().strip()
    original_objects = (worktree / original_objects).resolve()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_INDEX_FILE=str(scratch / "index"),
        GIT_OBJECT_DIRECTORY=str(objects),
        GIT_ALTERNATE_OBJECT_DIRECTORIES=str(original_objects),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    names = set(
        _git(worktree, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")
    ) - {b""}
    # A gitlink is a commit pointer, not a file to hash or a directory to recurse.
    # Preserve unchanged submodules; patches cannot transport dirty submodule trees.
    base_links = {}
    for entry in _git(worktree, "ls-tree", "-rz", base).split(b"\0"):
        if entry.startswith(b"160000 "):
            metadata, name = entry.split(b"\t", 1)
            base_links[name] = metadata.split()[2]
    links = {}
    for entry in _git(worktree, "ls-files", "--stage", "-z").split(b"\0"):
        if entry.startswith(b"160000 "):
            metadata, name = entry.split(b"\t", 1)
            _, digest, stage = metadata.split()
            if stage != b"0":
                raise ValueError("submission_submodule_changed")
            links[name] = digest
    if links != base_links:
        raise ValueError("submission_submodule_changed")
    if len(names) > 100_000:
        raise ValueError("submission_snapshot_limit")
    paths, entries, size = [], [], 0
    for name in sorted(names):
        relative = Path(os.fsdecode(name))
        if relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts:
            raise ValueError("submission_unsafe_path")
        path = worktree / relative
        # An unignored nested linked worktree is not a file in its parent's submission.
        if any(path == other for other in worktrees if other != worktree):
            continue
        if any(parent.is_symlink() for parent in path.parents if parent != worktree):
            raise ValueError("submission_unsafe_path")
        if name in links:
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise ValueError("submission_submodule_changed")
            if _git(
                worktree,
                "diff-files",
                "--raw",
                "--no-ext-diff",
                "--no-textconv",
                "--ignore-submodules=none",
                "--",
                os.fsdecode(name),
            ):
                raise ValueError("submission_submodule_changed")
            continue
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue  # Tracked deletion: leave the file out of the snapshot.
        if stat.S_ISLNK(mode):
            mode = "120000"
            content = os.fsencode(os.readlink(path))
            path = scratch / f"link-{len(entries)}"
            path.write_bytes(content)
        elif stat.S_ISREG(mode):
            mode = "100755" if mode & 0o111 else "100644"
        else:
            raise ValueError("submission_unsupported_file")
        size += path.stat().st_size
        if size > 256 * 1024 * 1024:
            raise ValueError("submission_snapshot_limit")
        # Git's --stdin-paths accepts C-quoted paths, including tabs/newlines and
        # arbitrary filename bytes. JSON's Unicode escapes are not Git quoting.
        quoted = (
            b'"'
            + b"".join(
                bytes([byte])
                if 32 <= byte < 127 and byte not in (34, 92)
                else f"\\{byte:03o}".encode()
                for byte in os.fsencode(path)
            )
            + b'"\n'
        )
        paths.append(quoted)
        entries.append((mode.encode(), name))
    hashes = _git(
        worktree,
        "hash-object",
        "--no-filters",
        "-w",
        "--stdin-paths",
        env=env,
        data=b"".join(paths),
    ).splitlines()
    if len(hashes) != len(entries):
        raise ValueError("submission_snapshot_failed")
    _git(worktree, "read-tree", "--empty", env=env)
    _git(
        worktree,
        "update-index",
        "-z",
        "--index-info",
        env=env,
        data=b"".join(
            mode + b" " + digest + b"\t" + name + b"\0"
            for (mode, name), digest in zip(entries, hashes, strict=True)
        )
        + b"".join(
            b"160000 " + digest + b"\t" + name + b"\0" for name, digest in sorted(links.items())
        ),
    )
    return _git(
        worktree,
        "diff",
        "--cached",
        "--binary",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        base,
        "--",
        env=env,
    )


def capture_submission(workspace: Path, base: str, destination: Path, evidence: Path) -> dict:
    """Retain all candidates; grade only a unique changed tree (or a genuine no-op)."""
    record = {"protocol": PROTOCOL, "base_commit": base, "status": "failed", "candidates": []}
    evidence.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Never allow a stale/partial patch to masquerade as this capture's output.
    destination.unlink(missing_ok=True)
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", base):
            raise ValueError("submission_invalid_base")
        workspace = workspace.resolve(strict=True)
        if _git(workspace, "cat-file", "-t", base).strip() != b"commit":
            raise ValueError("submission_invalid_base")
        common = (
            workspace / os.fsdecode(_git(workspace, "rev-parse", "--git-common-dir").strip())
        ).resolve()
        listing = _git(workspace, "worktree", "list", "--porcelain", "-z")
        worktrees = []
        for block in listing.split(b"\0\0"):
            fields = block.split(b"\0")
            if not block or any(field.startswith(b"prunable") for field in fields):
                continue
            name = next((field[9:] for field in fields if field.startswith(b"worktree ")), None)
            if name is None:
                raise ValueError("submission_invalid_worktree")
            path = Path(os.fsdecode(name)).resolve(strict=True)
            actual_common = (
                path / os.fsdecode(_git(path, "rev-parse", "--git-common-dir").strip())
            ).resolve()
            if actual_common != common or path in worktrees:
                raise ValueError("submission_invalid_worktree")
            worktrees.append(path)
        if workspace not in worktrees or len(worktrees) > 32:
            raise ValueError("submission_invalid_worktree")
        patches = {}
        for index, worktree in enumerate(worktrees):
            with tempfile.TemporaryDirectory(prefix="Harness_Submission_") as temporary:
                patch = _snapshot(worktree, base, worktrees, Path(temporary))
            digest = "sha256:" + hashlib.sha256(patch).hexdigest()
            name = f"Candidate-{index + 1}.patch"
            (evidence / name).write_bytes(patch)
            record["candidates"].append(
                {"worktree": str(worktree), "patch": name, "digest": digest, "bytes": len(patch)}
            )
            if patch:
                patches[digest] = patch
        if len(patches) > 1:
            raise ValueError("submission_ambiguous_worktrees")
        patch = next(iter(patches.values()), b"")
        destination.write_bytes(patch)
        record.update(status="captured", patch_digest="sha256:" + hashlib.sha256(patch).hexdigest())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, ValueError) else "submission_capture_failed"
        record["reason"] = (
            reason if reason.startswith("submission_") else "submission_capture_failed"
        )
    (evidence / "Submission.json").write_text(json.dumps(record, indent=2) + "\n")
    return record
