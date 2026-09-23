"""Versioned neutral prompts over the existing protected development fixtures."""

from __future__ import annotations

import json
import re
import shutil
import stat
import tempfile
import tomllib
from pathlib import Path

from harness_testing.Materialize import _tree_digest
from harness_testing.Scripted_User import validate_policy

_RESEARCH_SCRIPTED_USER_POLICY = {
    "schema_version": "1",
    "interaction_limit": 1,
    "facts": {
        "implementation": (
            "Proceed with implementation and verification within the original local task scope. "
            "This grants no publishing, deployment, additional spending, or broader authority."
        )
    },
    "rules": [
        {
            "id": "implementation-approval",
            "kind": "approval",
            "matcher": "local-development-approval",
            "fact": "implementation",
        }
    ],
}


def research_scripted_user_policy(task_ids: list[str]) -> dict:
    """Return bounded approval and task-specific authored clarification facts."""
    from harness_testing.Materialize import DEEPSWE_TASK_IDS

    if not task_ids or not set(task_ids) <= set(DEEPSWE_TASK_IDS):
        raise ValueError("DeepSWE comparison requires pinned catalog tasks")
    policy = json.loads(json.dumps(_RESEARCH_SCRIPTED_USER_POLICY))
    if task_ids == ["quill-shared-toolbar-focus"]:
        policy["facts"]["editor-removal"] = (
            "Removing an editor means removing its container from the DOM. "
            "Support that existing usage; do not add a new public destroy or lifecycle API. "
            "The remaining shared-toolbar behavior is as specified in the original task."
        )
        policy["rules"].append(
            {
                "id": "editor-removal",
                "kind": "clarification",
                "fact": "editor-removal",
                "pattern": (
                    r"(?is)(?=.*\b(?:remov\w*|destroy)\b)(?=.*\b(?:editor|quill)\b)"
                    r"(?=.*\b(?:DOM|destroy|lifecycle)\b)(?=.*\?).*"
                ),
            }
        )
    validate_policy(policy)
    return policy


def materialize_comparison_tasks(root: Path, task_ids: list[str]) -> Path:
    """Copy selected fixtures with neutral prompts; preserve every verifier byte."""
    return _materialize_tasks(root, task_ids)


def materialize_research_comparison_tasks(
    root: Path, source_tasks: Path, task_ids: list[str]
) -> Path:
    """Derive disclosed benchmark prompts without modifying the pinned research dataset."""
    from harness_testing.Materialize import DEEPSWE_TASK_IDS

    if not set(task_ids) <= set(DEEPSWE_TASK_IDS):
        raise ValueError("DeepSWE comparison requires pinned catalog tasks")
    return _materialize_tasks(root, task_ids, research_source=source_tasks)


def _materialize_tasks(
    root: Path, task_ids: list[str], *, research_source: Path | None = None
) -> Path:
    if not task_ids or len(set(task_ids)) != len(task_ids):
        raise ValueError("comparison tasks must be nonempty and unique")
    cache = root / ".cache" / "comparison-tasks"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as scratch:
        dataset = Path(scratch) / "tasks"
        dataset.mkdir()
        for task_id in sorted(task_ids):
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", task_id):
                raise ValueError("invalid comparison task ID")
            source = (research_source or root / "tasks" / "workflow") / task_id
            if not (source / "task.toml").is_file() or source.is_symlink():
                raise ValueError(f"not an existing development task: {task_id}")
            prompt = source / ("instruction.md" if research_source else "Comparison Instruction.md")
            policy = source / "Scripted User.json"
            if (
                not prompt.is_file()
                or not prompt.read_text().strip()
                or (research_source is None and not policy.is_file())
            ):
                raise ValueError(f"comparison task inputs are missing: {task_id}")
            if research_source is None:
                validate_policy(json.loads(policy.read_text()))
            target = dataset / task_id
            shutil.copytree(source, target, symlinks=True)
            instruction = (
                prompt.read_text().rstrip()
                + "\n\nExisting test files are read-only: leave them byte-for-byte unchanged, "
                "including when adding or strengthening assertions. If you write tests, "
                "put them in new, separate test files.\n"
            )
            if research_source is not None:
                instruction += (
                    "Do not add, delete, or change test-runner, package, dependency-lock, or build "
                    "configuration files or dotfiles, and do not add symlinks. "
                    "Run the existing checks without weakening or bypassing them.\n"
                    "Submission capture includes committed, staged, unstaged, and new non-ignored "
                    "files from this repository, including a linked worktree. Keep one uniquely "
                    "changed worktree at handoff; divergent changed worktrees are ambiguous and "
                    "cannot be graded. Work is also captured on interruption, but a timeout "
                    "remains a timeout, not successful completion.\n"
                )
                if task_id == "quill-shared-toolbar-focus":
                    instruction += (
                        "Environment setup: dependencies are preinstalled in /app/node_modules "
                        "and /app/packages/quill/node_modules. A Git linked worktree does not "
                        "include either directory; falling back to /app's root dependencies "
                        "resolves the wrong glob version. If you use a linked worktree, copy "
                        "both complete dependency directories to the same relative locations "
                        "inside it before running checks (cp -a /app/node_modules WORKTREE/; "
                        "cp -a /app/packages/quill/node_modules WORKTREE/packages/quill/). "
                        "Replace WORKTREE with your worktree path. Preserve existing dependency "
                        "symlinks in these ignored directories; do not add symlinks to submitted "
                        "source. Do not move dependencies out of /app or change manifests/locks. "
                        "Use the existing package scripts, such as npm run lint:tsc -w quill. "
                        "Headed browser checks need xvfb-run -a in this display-free container.\n"
                    )
            # Pinned research trees are read-only. Replace only the derived prompts;
            # never follow a copied prompt symlink back into the original dataset.
            target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
            if research_source is not None:
                from harness_testing.Submission import PROTOCOL

                base = tomllib.loads((source / "task.toml").read_text()).get("metadata", {}).get(
                    "base_commit_hash"
                )
                if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base):
                    raise ValueError("DeepSWE task has no exact base commit")
                contract = target / "Submission Contract.json"
                contract.unlink(missing_ok=True)
                contract.write_text(json.dumps({"protocol": PROTOCOL, "base_commit": base}) + "\n")
                # Native finalization captures after stopping the provider tree.
                # Do not let upstream's committed-/app-only hook overwrite it.
                hook = target / "pre_artifacts.sh"
                hook.unlink(missing_ok=True)
                hook.write_text("#!/bin/sh\nset -eu\ntest -f /logs/artifacts/model.patch\n")
                hook.chmod(0o755)
            for name in ("instruction.md", "Comparison Instruction.md"):
                derived_prompt = target / name
                derived_prompt.unlink(missing_ok=True)
                derived_prompt.write_text(instruction)
        digest = _tree_digest(dataset)
        destination = cache / digest.removeprefix("sha256:")
        if destination.exists():
            if _tree_digest(destination) != digest:
                raise ValueError("comparison dataset contents changed after materialization")
        else:
            dataset.rename(destination)
    return destination
