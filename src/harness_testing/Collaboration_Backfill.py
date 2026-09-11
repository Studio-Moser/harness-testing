"""Retrospectively recover public collaboration evidence from retained ATIF."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from harness_testing.Collaboration_Quality import (
    calculate_communication_metrics,
    validate_visible_transcript,
)
from harness_testing.Communication_Contracts import load_communication_contract
from harness_testing.Run_Reports import load_run_report, run_report_id, validate_run_report

_LIMITATION = (
    "Collaboration transcript was retrospectively reconstructed from the retained "
    "root ATIF trajectory and evaluated with the current communication contract."
)


def _sha256(contents: bytes) -> str:
    return "sha256:" + hashlib.sha256(contents).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("ATIF transcript message has no timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("ATIF transcript message has an invalid timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("ATIF transcript message timestamp has no timezone")
    return parsed.astimezone(UTC)


def extract_atif_transcript(
    document: object, task_instruction: str, *, verified_missing_task: bool = False
) -> list[dict]:
    """Select the actual task turn and root-visible ATIF agent messages."""
    if not isinstance(document, dict) or not isinstance(document.get("steps"), list):
        raise ValueError("retained ATIF trajectory is invalid")
    instruction = task_instruction.strip()
    steps = document["steps"]
    first_agent = next(
        (
            index
            for index, step in enumerate(steps)
            if isinstance(step, dict) and step.get("source") == "agent"
        ),
        None,
    )
    if first_agent is None:
        raise ValueError("retained ATIF trajectory has no agent messages")
    matches = [
        index
        for index, step in enumerate(steps[:first_agent])
        if isinstance(step, dict)
        and step.get("source") == "user"
        and isinstance(step.get("message"), str)
        and step["message"].strip() == instruction
    ]
    if len(matches) > 1 or (not matches and not verified_missing_task):
        raise ValueError("ATIF task instruction does not match the frozen instruction")
    task_index = matches[0] if matches else first_agent
    visible = [
        step
        for step in steps[task_index:]
        if isinstance(step, dict)
        and step.get("source") in {"user", "agent"}
        and isinstance(step.get("message"), str)
        and step["message"].strip()
    ]
    if not matches:
        preceding = [step for step in steps[:first_agent] if isinstance(step, dict)]
        if not preceding:
            raise ValueError("retained ATIF trajectory has no task timing evidence")
        visible.insert(
            0,
            {
                "source": "user",
                "message": instruction,
                "timestamp": preceding[-1].get("timestamp"),
            },
        )
    agent_positions = [index for index, step in enumerate(visible) if step["source"] == "agent"]
    if not agent_positions:
        raise ValueError("retained ATIF trajectory has no visible agent response")
    final_positions = {agent_positions[-1]}
    final_positions.update(
        index
        for index in agent_positions
        if index + 1 < len(visible) and visible[index + 1]["source"] == "user"
    )
    started = _timestamp(visible[0].get("timestamp"))
    transcript = []
    for index, step in enumerate(visible):
        role = "assistant" if step["source"] == "agent" else "user"
        transcript.append(
            {
                "ordinal": len(transcript) + 1,
                "role": role,
                "kind": "final"
                if role == "assistant" and index in final_positions
                else "progress"
                if role == "assistant"
                else "user",
                "content": step["message"].strip(),
                "elapsed_seconds": round(
                    (_timestamp(step.get("timestamp")) - started).total_seconds(), 3
                ),
            }
        )
    return validate_visible_transcript(transcript)


def _job_for_trial(report: dict, trial: dict) -> dict:
    contender = trial["contender_id"].removeprefix("sha256:")
    expected_arm = "V" + contender[:16]
    matches = [
        job
        for job in report.get("jobs", [])
        if job.get("arm") == expected_arm and job.get("task") == trial.get("task_id")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"retrospective collaboration job mapping is ambiguous: {trial['trial_id']}"
        )
    return matches[0]


def _trial_evidence_paths(jobs_dir: Path, job: dict) -> tuple[Path, Path]:
    name = job.get("name")
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("retrospective collaboration job name is unsafe")
    matches = sorted((jobs_dir / name).glob("*/agent/trajectory.json"))
    if len(matches) != 1:
        raise ValueError(f"expected one retained ATIF trajectory for {name}")
    requests = matches[0].with_name("Native_Requests.jsonl")
    if not requests.is_file():
        raise ValueError(f"retained native requests are missing for {name}")
    return matches[0], requests


def _verify_native_instruction(path: Path, instruction: str) -> bytes:
    contents = path.read_bytes()
    matches = 0
    for line in contents.splitlines():
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("retained native requests are unreadable") from error
        if not isinstance(event, dict) or event.get("method") != "turn/start":
            continue
        inputs = event.get("params", {}).get("input", [])
        if any(
            isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
            and item["text"].strip() == instruction
            for item in inputs
        ):
            matches += 1
    if matches != 1:
        raise ValueError("native task instruction does not match the frozen instruction")
    return contents


def backfill_collaboration(
    root: Path,
    report_path: Path,
    jobs_dir: Path,
    contract_path: Path,
    instruction_path: Path,
) -> dict:
    """Write an immutable superseding report from retained root ATIF messages."""
    root = root.resolve()
    report_path = report_path.resolve()
    jobs_dir = jobs_dir.resolve()
    report = load_run_report(root, report_path)
    trials = report.get("experiment", {}).get("trials", [])
    if not trials or any("collaboration" in trial for trial in trials):
        raise ValueError("collaboration backfill requires trials without collaboration evidence")
    task_ids = {trial.get("task_id") for trial in trials}
    if len(task_ids) != 1:
        raise ValueError("one collaboration backfill must contain exactly one task")
    contract_path = contract_path.resolve()
    instruction_path = instruction_path.resolve()
    frozen = load_communication_contract(contract_path)
    try:
        instruction_bytes = instruction_path.read_bytes()
        instruction = instruction_bytes.decode().strip()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError("retrospective task instruction is unreadable") from error
    if not instruction:
        raise ValueError("retrospective task instruction is empty")

    revised = copy.deepcopy(report)
    provenance = []
    for source_trial, revised_trial in zip(trials, revised["experiment"]["trials"], strict=True):
        job = _job_for_trial(report, source_trial)
        trajectory_path, requests_path = _trial_evidence_paths(jobs_dir, job)
        trajectory_bytes = trajectory_path.read_bytes()
        try:
            trajectory = json.loads(trajectory_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"retained ATIF trajectory is unreadable: {job['name']}") from error
        requests_bytes = _verify_native_instruction(requests_path, instruction)
        transcript = extract_atif_transcript(
            trajectory,
            instruction,
            verified_missing_task=True,
        )
        usage = source_trial.get("model_usage", [])
        outputs = [row.get("output_tokens") for row in usage if isinstance(row, dict)]
        output_tokens = (
            sum(outputs) if outputs and all(type(value) is int for value in outputs) else None
        )
        revised_trial["collaboration"] = {
            "status": "complete",
            "reasons": [],
            "contract_digest": frozen["digest"],
            "contract": frozen["contract"],
            "transcript": transcript,
            "metrics": calculate_communication_metrics(
                transcript,
                frozen["contract"],
                task_text=instruction,
                model_output_tokens=output_tokens,
            ),
        }
        provenance.append(
            {
                "trial_id": source_trial["trial_id"],
                "job_name": job["name"],
                "trajectory_path": str(trajectory_path),
                "trajectory_digest": _sha256(trajectory_bytes),
                "native_requests_path": str(requests_path),
                "native_requests_digest": _sha256(requests_bytes),
                "transcript_digest": _sha256(_canonical(transcript)),
            }
        )

    limitations = revised["experiment"]["comparison"]["limitations"]
    if _LIMITATION not in limitations:
        limitations.append(_LIMITATION)
    revised["experiment"]["supersedes_report_id"] = report["report_id"]
    revised["updated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    revised["report_id"] = run_report_id(revised)
    errors = validate_run_report(root, revised)
    if errors:
        raise ValueError("retrospective collaboration report is invalid: " + "; ".join(errors))

    source_bytes = report_path.read_bytes()
    contract_bytes = contract_path.read_bytes()
    unsigned = {
        "schema_version": "1",
        "source": {
            "report_path": str(report_path),
            "report_id": report["report_id"],
            "report_digest": _sha256(source_bytes),
        },
        "contract": {
            "path": str(contract_path),
            "digest": _sha256(contract_bytes),
        },
        "instruction": {
            "path": str(instruction_path),
            "digest": _sha256(instruction_bytes),
        },
        "trials": provenance,
    }
    plan_id = _sha256(_canonical(unsigned))
    plan = {"plan_id": plan_id, **unsigned}
    directory = root / "runs/collaboration-backfill" / plan_id.removeprefix("sha256:")
    directory.mkdir(parents=True, exist_ok=True)
    plan_path = directory / "Plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError("collaboration backfill plan conflicts with retained evidence")
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    (directory / "Source Report.json").write_bytes(source_bytes)
    (directory / "Communication Contract.json").write_bytes(contract_bytes)
    (directory / "Task Instruction.md").write_bytes(instruction_bytes)

    revised_path = directory / "Revised Report.json"
    if revised_path.exists():
        retained = json.loads(revised_path.read_text())
        errors = validate_run_report(root, retained)
        supersedes = retained.get("experiment", {}).get("supersedes_report_id")
        if errors or supersedes != report["report_id"]:
            raise ValueError("retained retrospective collaboration report is invalid")
        evidence = root / "runs/evidence" / f"{retained['report_id'].removeprefix('sha256:')}.json"
        retained_contents = json.dumps(retained, indent=2, sort_keys=True) + "\n"
        if evidence.exists() and evidence.read_text() != retained_contents:
            raise ValueError(
                "retrospective collaboration report identity conflicts with retained evidence"
            )
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(retained_contents)
        return {"status": "accepted", "plan_id": plan_id, "plan": plan_path, "report": evidence}

    evidence = root / "runs/evidence" / f"{revised['report_id'].removeprefix('sha256:')}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    contents = json.dumps(revised, indent=2, sort_keys=True) + "\n"
    if evidence.exists() and evidence.read_text() != contents:
        raise ValueError(
            "retrospective collaboration report identity conflicts with retained evidence"
        )
    evidence.write_text(contents)
    revised_path.write_text(contents)
    return {"status": "accepted", "plan_id": plan_id, "plan": plan_path, "report": evidence}
