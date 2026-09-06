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
    assert len(tasks) == 9
    for task in tasks:
        assert (task.parent / "Comparison Instruction.md").read_text().strip()
        validate_policy(json.loads((task.parent / "Scripted User.json").read_text()))


def test_traversal_and_nonworkflow_tasks_rejected(tmp_path):
    with pytest.raises(ValueError):
        materialize_comparison_tasks(tmp_path, ["../contract"])
