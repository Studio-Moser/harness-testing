import json
from pathlib import Path

import pytest

from harness_testing.Comparison_Tasks import materialize_comparison_tasks


def test_variant_keeps_oracle_and_protection_but_changes_prompt(tmp_path):
    source = tmp_path / "tasks/workflow/fixture-task"
    (source / "tests").mkdir(parents=True)
    (source / "task.toml").write_text('version = "1.0"\n')
    (source / "instruction.md").write_text("Run the gate exactly once.")
    (source / "Comparison Instruction.md").write_text("Fix the requested behavior.")
    (source / "Scripted User.json").write_text(
        json.dumps({"schema_version": "1", "interaction_limit": 12, "facts": {}, "rules": []})
    )
    (source / "tests/Protected_Files.json").write_text('{"protected": true}')
    dataset = materialize_comparison_tasks(tmp_path, ["fixture-task"])
    assert (dataset / "fixture-task/instruction.md").read_text() == "Fix the requested behavior."
    assert (dataset / "fixture-task/tests/Protected_Files.json").read_bytes() == (
        source / "tests/Protected_Files.json"
    ).read_bytes()
    assert (source / "instruction.md").read_text() == "Run the gate exactly once."
    assert materialize_comparison_tasks(tmp_path, ["fixture-task"]) == dataset
    (source / "Comparison Instruction.md").write_text("Different request.")
    assert materialize_comparison_tasks(tmp_path, ["fixture-task"]) != dataset


def test_all_existing_comparison_tasks_have_frozen_valid_user_policy():
    from harness_testing.Scripted_User import validate_policy

    root = Path(__file__).parents[2]
    tasks = list((root / "tasks/workflow").glob("*/task.toml"))
    assert len(tasks) == 10
    for task in tasks:
        assert (task.parent / "Comparison Instruction.md").read_text().strip()
        validate_policy(json.loads((task.parent / "Scripted User.json").read_text()))


def test_traversal_and_nonworkflow_tasks_rejected(tmp_path):
    with pytest.raises(ValueError):
        materialize_comparison_tasks(tmp_path, ["../contract"])


def test_active_badge_prompt_delivers_explicit_test_file_boundary(tmp_path):
    import shutil

    from harness_testing.Workflow_Criteria import protected_files_intact

    task_id = "react-active-badge-count"
    source = Path(__file__).parents[2] / "tasks/workflow" / task_id
    copied = tmp_path / "tasks/workflow" / task_id
    shutil.copytree(source, copied)
    dataset = materialize_comparison_tasks(tmp_path, [task_id])
    task = dataset / task_id
    prompt = (task / "instruction.md").read_text()
    assert "Add regression coverage in a new test file" in prompt
    assert "Leave existing test files byte-for-byte unchanged" in prompt
    workspace = task / "environment"
    manifest = task / "tests/Protected_Files.json"
    assert protected_files_intact(workspace, manifest)
    (workspace / "src/domain/Active_Count.test.ts").write_text("// new regression coverage\n")
    assert protected_files_intact(workspace, manifest)
    existing = workspace / "src/App.test.tsx"
    existing.write_text(existing.read_text() + "\n// even additive edits are protected\n")
    assert not protected_files_intact(workspace, manifest)
