import copy
import json
import shutil
from pathlib import Path

import pytest

from harness_testing.Collaboration_Backfill import (
    backfill_collaboration,
    extract_atif_transcript,
)
from harness_testing.Run_Reports import load_run_report, run_report_id

ROOT = Path(__file__).parents[2]


def _steps(instruction="Implement the substantial feature.", *, include_task=True):
    user_steps = [
        {
            "step_id": 2,
            "timestamp": "2026-09-10T20:00:01Z",
            "source": "user",
            "message": "Injected runtime context",
        }
    ]
    if include_task:
        user_steps.append(
            {
                "step_id": 3,
                "timestamp": "2026-09-10T20:00:02Z",
                "source": "user",
                "message": instruction,
            }
        )
    return {
        "schema_version": "1.0.0",
        "session_id": "private-session",
        "agent": {},
        "final_metrics": {},
        "steps": [
            {
                "step_id": 1,
                "timestamp": "2026-09-10T20:00:00Z",
                "source": "system",
                "message": "System instructions",
            },
            *user_steps,
            {
                "step_id": 4,
                "timestamp": "2026-09-10T20:00:05Z",
                "source": "agent",
                "message": "I found the existing implementation and am updating it.",
                "tool_calls": [{}],
            },
            {
                "step_id": 5,
                "timestamp": "2026-09-10T20:00:09Z",
                "source": "agent",
                "message": "Implemented and tested the feature.",
            },
        ],
    }


def _prepared_backfill(tmp_path):
    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    shutil.copy(ROOT / "Versions.toml", tmp_path / "Versions.toml")
    report = json.loads((ROOT / "tests/Fixtures/Run_Reports/Comparison.json").read_text())
    contender = report["experiment"]["contenders"][0]
    trial = copy.deepcopy(report["experiment"]["trials"][0])
    trial.update(task_id="research-feature", contender_id=contender["id"], attempt=1)
    trial["model_usage"] = [
        {
            "provider": "openai",
            "model": "gpt-6-astra",
            "input_tokens": 100,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 20,
        }
    ]
    report["experiment"]["trials"] = [trial]
    job = copy.deepcopy(report["jobs"][0])
    job.update(
        name="research-job",
        arm="V" + contender["id"].removeprefix("sha256:")[:16],
        task="research-feature",
    )
    report["jobs"] = [job]
    report["report_id"] = run_report_id(report)
    report_path = tmp_path / "Source Report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    instruction = tmp_path / "Instruction.md"
    instruction.write_text("Implement the substantial feature.\n")
    contract = ROOT / "tasks/workflow/react-saved-view-feature/Communication Contract.json"
    trajectory = tmp_path / "jobs/raw/research-job/research-feature__abc/agent/trajectory.json"
    trajectory.parent.mkdir(parents=True)
    trajectory.write_text(json.dumps(_steps(include_task=False)))
    (trajectory.parent / "Native_Requests.jsonl").write_text(
        json.dumps(
            {
                "id": 1,
                "method": "turn/start",
                "params": {
                    "input": [{"type": "text", "text": "Implement the substantial feature.\n"}]
                },
            }
        )
        + "\n"
    )
    return report_path, tmp_path / "jobs/raw", contract, instruction


def test_atif_backfill_keeps_only_the_actual_user_conversation():
    transcript = extract_atif_transcript(_steps(), "Implement the substantial feature.")

    assert [row["role"] for row in transcript] == ["user", "assistant", "assistant"]
    assert [row["kind"] for row in transcript] == ["user", "progress", "final"]
    assert transcript[0]["content"] == "Implement the substantial feature."
    assert transcript[-1]["elapsed_seconds"] == 7


def test_atif_backfill_rejects_a_different_task_instruction():
    with pytest.raises(ValueError, match="task instruction does not match"):
        extract_atif_transcript(_steps(), "A different task")


def test_backfill_writes_an_immutable_superseding_report(tmp_path):
    report_path, jobs_dir, contract, instruction = _prepared_backfill(tmp_path)
    source_bytes = report_path.read_bytes()

    outcome = backfill_collaboration(
        tmp_path,
        report_path,
        jobs_dir,
        contract,
        instruction,
    )

    assert report_path.read_bytes() == source_bytes
    revised = load_run_report(tmp_path, outcome["report"])
    collaboration = revised["experiment"]["trials"][0]["collaboration"]
    assert revised["experiment"]["supersedes_report_id"] != revised["report_id"]
    assert collaboration["status"] == "complete"
    assert collaboration["metrics"]["assistant_message_count"] == 2
    assert collaboration["metrics"]["communication_to_model_output_ratio"] is not None
    assert any(
        "retrospectively reconstructed" in row
        for row in revised["experiment"]["comparison"]["limitations"]
    )
    plan = json.loads(outcome["plan"].read_text())
    assert plan["trials"][0]["trajectory_digest"].startswith("sha256:")


def test_backfill_reuses_the_report_for_identical_retained_evidence(tmp_path):
    report_path, jobs_dir, contract, instruction = _prepared_backfill(tmp_path)

    first = backfill_collaboration(tmp_path, report_path, jobs_dir, contract, instruction)
    second = backfill_collaboration(tmp_path, report_path, jobs_dir, contract, instruction)

    assert second == first
    assert len(list((tmp_path / "runs/evidence").glob("*.json"))) == 1
