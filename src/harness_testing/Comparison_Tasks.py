"""Versioned neutral prompts over the existing protected development fixtures."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from harness_testing.Materialize import _tree_digest
from harness_testing.Scripted_User import validate_policy


def materialize_comparison_tasks(root: Path, task_ids: list[str]) -> Path:
    """Copy selected fixtures with neutral prompts; preserve every verifier byte."""
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
            source = root / "tasks" / "workflow" / task_id
            if not (source / "task.toml").is_file() or source.is_symlink():
                raise ValueError(f"not an existing development task: {task_id}")
            prompt = source / "Comparison Instruction.md"
            policy = source / "Scripted User.json"
            if not prompt.is_file() or not policy.is_file() or not prompt.read_text().strip():
                raise ValueError(f"comparison task inputs are missing: {task_id}")
            validate_policy(json.loads(policy.read_text()))
            target = dataset / task_id
            shutil.copytree(source, target, symlinks=True)
            (target / "instruction.md").write_bytes(prompt.read_bytes())
        digest = _tree_digest(dataset)
        destination = cache / digest.removeprefix("sha256:")
        if destination.exists():
            if _tree_digest(destination) != digest:
                raise ValueError("comparison dataset contents changed after materialization")
        else:
            dataset.rename(destination)
    return destination
