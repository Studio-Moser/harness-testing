"""Identity-blinded collaboration grading and personal A/B calibration."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets
from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from jsonschema import Draft202012Validator

from harness_testing.Experiment_Reports import _price_usage
from harness_testing.Public_Safety import public_safety_errors
from harness_testing.Run_Reports import load_run_report, run_report_id, validate_run_report

_MINIMUM_CALIBRATION_LABELS = 15


def calibration_is_ready(label_count: int) -> bool:
    """Return whether personal labels are numerous enough to drive the verdict."""
    return label_count >= _MINIMUM_CALIBRATION_LABELS


def _sha256(contents: bytes) -> str:
    return "sha256:" + hashlib.sha256(contents).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _read(path: Path, description: str) -> tuple[dict, bytes]:
    try:
        contents = path.read_bytes()
        value = json.loads(contents)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be an object")
    return value, contents


def _validate(root: Path, schema_name: str, value: object) -> None:
    schema, _ = _read(root / "policy" / schema_name, f"{schema_name} schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.path))
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.path)) or "$"
        raise ValueError(f"{schema_name}: {path}: {error.message}")


def _write_plan(root: Path, lane: str, unsigned: dict, packets: list[tuple[str, dict]]) -> dict:
    plan_id = _sha256(_canonical(unsigned))
    plan = {"plan_id": plan_id, **unsigned}
    directory = root / "runs" / lane / plan_id.removeprefix("sha256:")
    plan_path = directory / "Plan.json"
    if directory.exists():
        existing, _ = _read(plan_path, f"{lane} plan")
        if existing != plan:
            raise ValueError(f"{lane} plan identity conflicts with retained evidence")
    else:
        (directory / "Packets").mkdir(parents=True)
        plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        for packet_id, packet in packets:
            (directory / "Packets" / f"{packet_id}.json").write_text(
                json.dumps(packet, indent=2, sort_keys=True) + "\n"
            )
    return {
        "status": "accepted",
        "plan_id": plan_id,
        "plan": plan_path,
        "packets": [directory / "Packets" / f"{packet_id}.json" for packet_id, _ in packets],
    }


def _eligible_trials(report: dict) -> list[dict]:
    return [
        trial
        for trial in report.get("experiment", {}).get("trials", [])
        if isinstance(trial, dict)
        and trial.get("collaboration", {}).get("status") == "complete"
        and trial["collaboration"].get("metrics") is not None
    ]


def prepare_grading(root: Path, report_path: Path, protocol_path: Path) -> dict:
    """Freeze randomized packets that contain no contender or model identity."""
    root = root.resolve()
    report = load_run_report(root, report_path.resolve())
    protocol, protocol_bytes = _read(protocol_path.resolve(), "collaboration grading protocol")
    _validate(root, "Collaboration Grading Protocol.schema.json", protocol)
    trials = _eligible_trials(report)
    if not trials:
        raise ValueError("collaboration grading requires complete transcript evidence")
    protocol_id = _sha256(protocol_bytes)
    prepared = []
    for trial in trials:
        collaboration = trial["collaboration"]
        packet_id = "collaboration-" + secrets.token_hex(12)
        task_path = root / "tasks" / "workflow" / trial["task_id"] / "Comparison Instruction.md"
        packet = {
            "schema_version": "1",
            "packet_id": packet_id,
            "task": {
                "instruction": task_path.read_text(),
                "scenario": collaboration["contract"]["scenario"],
                "outcome": {
                    "status": trial["status"],
                    "correctness": trial["correctness"],
                    "protected_state": trial["protected_state"],
                },
            },
            "communication_contract": collaboration["contract"],
            "transcript": collaboration["transcript"],
            "grading": {
                "protocol_id": protocol_id,
                "rubric_version": protocol["rubric_version"],
                "instruction": protocol["instruction"],
                "dimensions": protocol["dimensions"],
            },
        }
        packet_bytes = json.dumps(packet, indent=2, sort_keys=True).encode() + b"\n"
        prepared.append((packet_id, packet, trial["trial_id"], _sha256(packet_bytes)))
    secrets.SystemRandom().shuffle(prepared)
    source_bytes = report_path.resolve().read_bytes()
    unsigned = {
        "schema_version": "1",
        "source": {
            "report_path": str(report_path.resolve()),
            "report_id": report["report_id"],
            "report_digest": _sha256(source_bytes),
        },
        "protocol": {
            "path": str(protocol_path.resolve()),
            "protocol_id": protocol_id,
            "protocol_digest": _sha256(protocol_bytes),
            "rubric_version": protocol["rubric_version"],
            "dimensions": protocol["dimensions"],
            "time_budget_seconds": protocol["time_budget_seconds"],
        },
        "conditions": protocol["grader"],
        "packets": [
            {"packet_id": packet_id, "trial_id": trial_id, "packet_digest": digest}
            for packet_id, _, trial_id, digest in prepared
        ],
    }
    result = _write_plan(
        root,
        "collaboration",
        unsigned,
        [(packet_id, packet) for packet_id, packet, _, _ in prepared],
    )
    result["plan"].parent.joinpath("Source Report.json").write_bytes(source_bytes)
    return result


def _verified_plan(root: Path, path: Path, lane: str) -> tuple[dict, Path]:
    plan, _ = _read(path.resolve(), f"{lane} plan")
    unsigned = dict(plan)
    plan_id = unsigned.pop("plan_id", None)
    if plan_id != _sha256(_canonical(unsigned)):
        raise ValueError(f"{lane} plan identity does not match its content")
    directory = path.resolve().parent
    if not directory.is_relative_to((root / "runs" / lane).resolve()):
        raise ValueError(f"{lane} plan is outside its evidence directory")
    return plan, directory


def _source_report(root: Path, plan: dict, directory: Path) -> tuple[dict, Path]:
    source = plan["source"]
    path = directory / "Source Report.json"
    report, contents = _read(path, "frozen source report")
    if (
        _sha256(contents) != source["report_digest"]
        or report.get("report_id") != source["report_id"]
    ):
        raise ValueError("frozen source report changed after preparation")
    if validate_run_report(root, report):
        raise ValueError("frozen source report is invalid")
    for packet in plan["packets"]:
        packet_id = packet.get("packet_id", packet.get("pair_id"))
        packet_path = directory / "Packets" / f"{packet_id}.json"
        if _sha256(packet_path.read_bytes()) != packet["packet_digest"]:
            raise ValueError("collaboration packet changed after preparation")
    return report, Path(source["report_path"])


def _grade_summary(root: Path, result: dict, plan: dict) -> dict:
    conditions = plan["conditions"]
    if result["conditions"] != conditions:
        raise ValueError("grader conditions do not match the frozen protocol")
    names = [row["name"] for row in result["dimensions"]]
    completed = result["status"] == "completed"
    if completed and (
        names != plan["protocol"]["dimensions"] or result["would_work_again"] is None
    ):
        raise ValueError("completed grade must score every dimension in protocol order")
    if not completed and (result["dimensions"] or result["would_work_again"] is not None):
        raise ValueError("incomplete grade cannot carry judgments")
    duration = result["duration_seconds"]
    if completed and (duration is None or duration > plan["protocol"]["time_budget_seconds"]):
        raise ValueError("completed grade requires duration within the frozen budget")
    usage = result["model_usage"]
    expected_provider = {"codex": "openai", "claude": "anthropic"}.get(
        conditions["provider"], conditions["provider"]
    )
    if any(
        row["provider"] != expected_provider or row["model"] != conditions["model"] for row in usage
    ):
        raise ValueError("grader usage identity does not match the frozen protocol")
    complete_usage = (
        result["usage_complete"]
        and bool(usage)
        and all(
            all(
                type(row[field]) is int
                for field in (
                    "input_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                    "output_tokens",
                )
            )
            for row in usage
        )
    )
    cost, pricing_digest = _price_usage(root, usage)
    return {
        "status": result["status"],
        "protocol_id": plan["protocol"]["protocol_id"],
        "rubric_version": plan["protocol"]["rubric_version"],
        "dimensions": result["dimensions"],
        "would_work_again": result["would_work_again"],
        "duration_seconds": duration,
        "usage_complete": complete_usage,
        "model_usage": usage,
        "cost_usd": cost if complete_usage else None,
        "pricing_digest": pricing_digest,
    }


def _write_revised_report(
    root: Path,
    revised: dict,
    source: dict,
    source_path: Path,
    directory: Path,
    results_bytes: bytes,
    lane: str,
) -> Path:
    revised["experiment"]["supersedes_report_id"] = source["report_id"]
    revised["updated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    revised["report_id"] = run_report_id(revised)
    errors = (*public_safety_errors(revised), *validate_run_report(root, revised))
    if errors:
        raise ValueError(
            f"collaboration report is not public-safe: {'; '.join(dict.fromkeys(errors))}"
        )
    contents = json.dumps(revised, indent=2, sort_keys=True) + "\n"
    evidence = root / "runs" / "evidence" / f"{revised['report_id'].removeprefix('sha256:')}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(contents)
    (directory / "Imported Results.json").write_bytes(results_bytes)
    if source_path.name == "Run_Report.json" and source_path.is_relative_to(
        root / "runs" / "generated"
    ):
        temporary = source_path.with_name(f".Run_Report.{lane}.tmp")
        temporary.write_text(contents)
        os.replace(temporary, source_path)
    return evidence


def record_grading(root: Path, plan_path: Path, results_path: Path) -> dict:
    """Validate returned blinded grades and attach them to a superseding report."""
    root = root.resolve()
    plan, directory = _verified_plan(root, plan_path, "collaboration")
    source, source_path = _source_report(root, plan, directory)
    results, results_bytes = _read(results_path.resolve(), "collaboration grading results")
    _validate(root, "Collaboration Grading Results.schema.json", results)
    if (
        results["plan_id"] != plan["plan_id"]
        or results["protocol_id"] != plan["protocol"]["protocol_id"]
    ):
        raise ValueError("grading results do not match the frozen plan")
    planned = {row["packet_id"]: row for row in plan["packets"]}
    returned = {row["packet_id"]: row for row in results["results"]}
    if len(returned) != len(results["results"]) or set(returned) != set(planned):
        raise ValueError("grading results must cover every packet exactly once")
    sessions = [row["session_id"] for row in results["results"]]
    if len(set(sessions)) != len(sessions):
        raise ValueError("each collaboration packet requires a distinct fresh session")
    summaries = {
        planned[packet_id]["trial_id"]: _grade_summary(root, returned[packet_id], plan)
        for packet_id in planned
    }
    revised = copy.deepcopy(source)
    for trial in revised["experiment"]["trials"]:
        if trial["trial_id"] in summaries:
            trial["collaboration"]["grade"] = summaries[trial["trial_id"]]
    costs = [row["cost_usd"] for row in summaries.values()]
    revised["experiment"]["collaboration_evaluation"] = {
        "plan_id": plan["plan_id"],
        "protocol_id": plan["protocol"]["protocol_id"],
        "rubric_version": plan["protocol"]["rubric_version"],
        "source_report_id": source["report_id"],
        "results_digest": _sha256(results_bytes),
        "evaluation_cost_usd": sum(costs)
        if costs and all(cost is not None for cost in costs)
        else None,
    }
    evidence = _write_revised_report(
        root, revised, source, source_path, directory, results_bytes, "collaboration"
    )
    return {"status": "accepted", "report": evidence, "report_id": revised["report_id"]}


def prepare_calibration(root: Path, report_path: Path) -> dict:
    """Create same-scenario A/B packets while keeping identities in the private plan."""
    root = root.resolve()
    report = load_run_report(root, report_path.resolve())
    by_slot = defaultdict(list)
    for trial in _eligible_trials(report):
        key = (
            trial["task_id"],
            trial["attempt"],
            trial["collaboration"]["contract"]["scenario"],
        )
        by_slot[key].append(trial)
    prepared = []
    for (_, _, scenario), trials in sorted(by_slot.items()):
        for left, right in combinations(trials, 2):
            if left["contender_id"] == right["contender_id"]:
                continue
            sides = [left, right]
            secrets.SystemRandom().shuffle(sides)
            pair_id = "pair-" + secrets.token_hex(12)
            packet = {
                "schema_version": "1",
                "pair_id": pair_id,
                "scenario": scenario,
                "question": "Which assistant would you rather work with?",
                "A": sides[0]["collaboration"]["transcript"],
                "B": sides[1]["collaboration"]["transcript"],
            }
            prepared.append((pair_id, packet, sides[0]["trial_id"], sides[1]["trial_id"]))
    if not prepared:
        raise ValueError("calibration requires two contenders with the same scenario")
    secrets.SystemRandom().shuffle(prepared)
    source_bytes = report_path.resolve().read_bytes()
    unsigned = {
        "schema_version": "1",
        "source": {
            "report_path": str(report_path.resolve()),
            "report_id": report["report_id"],
            "report_digest": _sha256(source_bytes),
        },
        "packets": [
            {
                "pair_id": pair_id,
                "a_trial_id": a,
                "b_trial_id": b,
                "packet_digest": _sha256(
                    json.dumps(packet, indent=2, sort_keys=True).encode() + b"\n"
                ),
            }
            for pair_id, packet, a, b in prepared
        ],
    }
    result = _write_plan(
        root, "calibration", unsigned, [(p, packet) for p, packet, _, _ in prepared]
    )
    result["plan"].parent.joinpath("Source Report.json").write_bytes(source_bytes)
    return result


def _automated_preference(left: dict, right: dict) -> str | None:
    grades = [
        left.get("collaboration", {}).get("grade"),
        right.get("collaboration", {}).get("grade"),
    ]
    if not all(isinstance(grade, dict) and grade.get("status") == "completed" for grade in grades):
        return None
    choices = [grade["would_work_again"] for grade in grades]
    if choices[0] != choices[1]:
        return left["trial_id"] if choices[0] else right["trial_id"]
    averages = [
        sum(row["score"] for row in grade["dimensions"]) / len(grade["dimensions"])
        for grade in grades
    ]
    if averages[0] == averages[1]:
        return None
    return left["trial_id"] if averages[0] > averages[1] else right["trial_id"]


def record_calibration(root: Path, plan_path: Path, labels_path: Path) -> dict:
    """Map blinded preferences back to contenders and record grader agreement."""
    root = root.resolve()
    plan, directory = _verified_plan(root, plan_path, "calibration")
    source, source_path = _source_report(root, plan, directory)
    labels, label_bytes = _read(labels_path.resolve(), "collaboration calibration labels")
    _validate(root, "Collaboration Calibration Labels.schema.json", labels)
    if labels["plan_id"] != plan["plan_id"]:
        raise ValueError("calibration labels do not match the frozen plan")
    planned = {row["pair_id"]: row for row in plan["packets"]}
    returned = {row["pair_id"]: row for row in labels["labels"]}
    if len(returned) != len(labels["labels"]) or set(returned) != set(planned):
        raise ValueError("calibration labels must cover every pair exactly once")
    trials = {row["trial_id"]: row for row in source["experiment"]["trials"]}
    public = []
    for pair_id, mapping in planned.items():
        left, right = trials[mapping["a_trial_id"]], trials[mapping["b_trial_id"]]
        preferred = left if returned[pair_id]["preferred"] == "A" else right
        other = right if preferred is left else left
        predicted = _automated_preference(left, right)
        public.append(
            {
                "pair_id": pair_id,
                "scenario": left["collaboration"]["contract"]["scenario"],
                "preferred_contender_id": preferred["contender_id"],
                "other_contender_id": other["contender_id"],
                "annoyance_reason": returned[pair_id]["annoyance_reason"],
                "grader_agreement": None
                if predicted is None
                else predicted == preferred["trial_id"],
            }
        )
    revised = copy.deepcopy(source)
    revised["experiment"]["collaboration_calibration"] = {
        "schema_version": "1",
        "plan_id": plan["plan_id"],
        "labels_digest": _sha256(label_bytes),
        "labels": public,
        "calibrated": calibration_is_ready(len(public)),
    }
    evidence = _write_revised_report(
        root, revised, source, source_path, directory, label_bytes, "calibration"
    )
    return {"status": "accepted", "report": evidence, "report_id": revised["report_id"]}
