import json
from pathlib import Path

import pytest

from harness_testing.Communication_Contracts import (
    communication_contract_for_task,
    load_communication_contract,
    load_scenario_catalog,
)


def contract():
    return {
        "schema_version": "1",
        "scenario": "small_clear_change",
        "expectations": {
            "initial_update": "optional",
            "progress_updates": {"minimum": 0, "maximum": 2, "require_new_information": True},
            "questions": {"minimum": 0, "maximum": 0},
            "approval_requests": {"minimum": 0, "maximum": 0},
            "final_answer_words": {"minimum": 1, "maximum": 140},
            "prompt_restatement": False,
        },
        "rubric": [
            "directness",
            "proportionality",
            "progress_usefulness",
            "autonomy",
            "candor",
            "warmth",
            "restraint",
            "completion_clarity",
        ],
    }


def test_contract_validation_is_strict_and_content_addressed(tmp_path):
    path = tmp_path / "Communication Contract.json"
    path.write_text(json.dumps(contract()))
    loaded = load_communication_contract(path)
    assert loaded["contract"]["scenario"] == "small_clear_change"
    assert loaded["digest"].startswith("sha256:")
    invalid = contract() | {"unknown": True}
    path.write_text(json.dumps(invalid))
    with pytest.raises(ValueError, match="communication contract"):
        load_communication_contract(path)


def test_every_comparison_task_has_a_valid_contract():
    root = Path(__file__).parents[2]
    tasks = sorted((root / "tasks/workflow").glob("*/task.toml"))
    assert len(tasks) == 10
    for task in tasks:
        loaded = communication_contract_for_task(root, task.parent.name)
        assert loaded["contract"]["schema_version"] == "1"


def test_catalog_freezes_all_ten_named_scenarios():
    root = Path(__file__).parents[2]
    catalog = load_scenario_catalog(root / "policy/Communication Scenarios.json")
    assert [row["id"] for row in catalog["scenarios"]] == [
        "simple_repository_question",
        "clear_small_edit",
        "ambiguous_feature",
        "mid_task_status",
        "user_correction",
        "technical_disagreement",
        "recoverable_failure",
        "authorized_routine_action",
        "consequential_action",
        "completed_implementation",
    ]
    assert all(row["contract"]["scenario"] == row["id"] for row in catalog["scenarios"])
