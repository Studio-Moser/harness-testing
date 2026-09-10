import copy
import json
import shutil
from pathlib import Path

from harness_testing.Collaboration_Grading import (
    calibration_is_ready,
    prepare_calibration,
    prepare_grading,
    record_calibration,
    record_grading,
)
from harness_testing.Collaboration_Quality import calculate_communication_metrics
from harness_testing.Communication_Contracts import communication_contract_for_task
from harness_testing.Run_Reports import load_run_report, run_report_id

ROOT = Path(__file__).parents[2]


def test_personal_calibration_requires_fifteen_blinded_choices():
    assert calibration_is_ready(14) is False
    assert calibration_is_ready(15) is True


def prepared_root(tmp_path):
    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    shutil.copy(ROOT / "Versions.toml", tmp_path / "Versions.toml")
    task = "react-active-badge-count"
    target = tmp_path / "tasks/workflow" / task
    target.mkdir(parents=True)
    shutil.copy(ROOT / "tasks/workflow" / task / "Comparison Instruction.md", target)
    report = json.loads((ROOT / "tests/Fixtures/Run_Reports/Comparison.json").read_text())
    contenders = report["experiment"]["contenders"][:2]
    base = report["experiment"]["trials"][0]
    transcript = [
        {
            "ordinal": 1,
            "role": "user",
            "kind": "user",
            "content": "Fix the count.",
            "elapsed_seconds": 0,
        },
        {
            "ordinal": 2,
            "role": "assistant",
            "kind": "final",
            "content": "Fixed and tested.",
            "elapsed_seconds": 2,
        },
    ]
    frozen = communication_contract_for_task(ROOT, task)
    trials = []
    for index, contender in enumerate(contenders, start=1):
        trial = dict(base)
        trial.update(
            trial_id="sha256:" + str(index) * 64,
            task_id=task,
            contender_id=contender["id"],
            attempt=1,
        )
        trial["collaboration"] = {
            "status": "complete",
            "reasons": [],
            "contract_digest": frozen["digest"],
            "contract": frozen["contract"],
            "transcript": transcript,
            "metrics": calculate_communication_metrics(
                transcript, frozen["contract"], task_text="Fix the count.", model_output_tokens=10
            ),
        }
        trials.append(trial)
    report["experiment"]["trials"] = trials
    report["report_id"] = run_report_id(report)
    report_path = tmp_path / "Source.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return tmp_path, report_path, contenders


def test_grading_packets_are_identity_blind_and_results_attach_to_new_report(tmp_path):
    root, report_path, contenders = prepared_root(tmp_path)
    protocol_path = root / "policy/Collaboration Grading Protocol.json"
    outcome = prepare_grading(root, report_path, protocol_path)
    assert len(outcome["packets"]) == 2
    for path in outcome["packets"]:
        packet = json.loads(path.read_text())
        text = path.read_text()
        assert set(packet) == {
            "schema_version",
            "packet_id",
            "task",
            "communication_contract",
            "transcript",
            "grading",
        }
        assert all(
            contender["id"] not in text and contender["label"] not in text
            for contender in contenders
        )
        assert "gpt-" not in text and "claude" not in text.lower()

    plan = json.loads(outcome["plan"].read_text())
    protocol = json.loads(protocol_path.read_text())
    results = {
        "schema_version": "1",
        "plan_id": plan["plan_id"],
        "protocol_id": plan["protocol"]["protocol_id"],
        "results": [],
    }
    for index, packet in enumerate(plan["packets"], start=1):
        results["results"].append(
            {
                "packet_id": packet["packet_id"],
                "status": "completed",
                "conditions": protocol["grader"],
                "session_id": f"fresh-{index}",
                "fresh_session": True,
                "identity_blind": True,
                "duration_seconds": 10,
                "usage_complete": True,
                "model_usage": [
                    {
                        "provider": "openai",
                        "model": "gpt-6-astra",
                        "input_tokens": 100,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                        "output_tokens": 20,
                    }
                ],
                "dimensions": [
                    {"name": name, "score": 4, "rationale": "Direct and proportionate."}
                    for name in protocol["dimensions"]
                ],
                "would_work_again": index == 1,
            }
        )
    results_path = tmp_path / "Grades.json"
    results_path.write_text(json.dumps(results))
    imported = record_grading(root, outcome["plan"], results_path)
    report = load_run_report(root, imported["report"])
    assert report["experiment"]["supersedes_report_id"] != report["report_id"]
    assert (
        report["experiment"]["collaboration_evaluation"]["rubric_version"] == "tim-collaboration-v1"
    )
    assert all(
        trial["collaboration"]["grade"]["status"] == "completed"
        for trial in report["experiment"]["trials"]
    )


def test_calibration_pairs_same_scenario_blindly_and_records_preference(tmp_path):
    root, report_path, contenders = prepared_root(tmp_path)
    outcome = prepare_calibration(root, report_path)
    assert len(outcome["packets"]) == 1
    packet = json.loads(outcome["packets"][0].read_text())
    assert set(packet) == {"schema_version", "pair_id", "scenario", "question", "A", "B"}
    assert all(contender["id"] not in outcome["packets"][0].read_text() for contender in contenders)
    labels = {
        "schema_version": "1",
        "plan_id": outcome["plan_id"],
        "labels": [
            {
                "pair_id": packet["pair_id"],
                "preferred": "A",
                "annoyance_reason": "B repeated itself.",
            }
        ],
    }
    labels_path = tmp_path / "Labels.json"
    labels_path.write_text(json.dumps(labels))
    imported = record_calibration(root, outcome["plan"], labels_path)
    report = load_run_report(root, imported["report"])
    calibration = report["experiment"]["collaboration_calibration"]
    assert calibration["calibrated"] is False
    assert calibration["labels"][0]["annoyance_reason"] == "B repeated itself."
    assert calibration["labels"][0]["preferred_contender_id"] in {
        contender["id"] for contender in contenders
    }


def test_calibration_never_pairs_different_tasks_with_the_same_scenario(tmp_path):
    root, report_path, _ = prepared_root(tmp_path)
    report = json.loads(report_path.read_text())
    extra = copy.deepcopy(report["experiment"]["trials"][0])
    extra["trial_id"] = "sha256:" + "9" * 64
    extra["task_id"] = "another-small-change"
    report["experiment"]["trials"].append(extra)
    report["report_id"] = run_report_id(report)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    outcome = prepare_calibration(root, report_path)

    assert len(outcome["packets"]) == 1
