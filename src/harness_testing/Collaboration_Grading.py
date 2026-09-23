"""Identity-blinded collaboration grading of retained transcripts and work evidence."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from harness_testing.Experiment_Reports import _price_usage
from harness_testing.Public_Safety import public_safety_errors
from harness_testing.Quality import RUBRIC_VERSION
from harness_testing.Run_Reports import load_run_report, run_report_id, validate_run_report


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
    from harness_testing.Code_Reviews import retained_trials

    return [
        trial
        for trial in retained_trials(report)
        if isinstance(trial, dict)
        and trial.get("collaboration", {}).get("status") == "complete"
        and trial["collaboration"].get("metrics") is not None
    ]


def _task_instruction(root: Path, trial: dict) -> str:
    # The retained user turn is the instruction actually delivered, not today's task.
    del root
    for row in trial["collaboration"]["transcript"]:
        if row.get("role") == "user":
            return row["content"]
    raise ValueError("collaboration grading requires a visible task instruction")


def _work_evidence(root: Path, report: dict, trial: dict) -> dict:
    """Retain bounded work evidence, never hidden reasoning or raw tool responses."""
    from harness_testing.Code_Reviews import _manifest_for_report, _trial_inputs, _trial_job
    from harness_testing.Config import load_job

    try:
        manifest = _manifest_for_report(root, report)
        inputs = _trial_inputs(root, manifest, trial)
        config = root / "runs/generated" / manifest["digest"][7:] / _trial_job(manifest, trial)
        job = load_job(config)
        paths = list((root / "jobs/raw" / job.job_name).glob("*/agent/trajectory.json"))
        recovered = False
        if len(paths) == 1:
            contents = paths[0].read_bytes()
            trajectory = json.loads(contents)
        elif not paths:
            logs = list((root / "jobs/raw" / job.job_name).glob("*/agent/codex.txt"))
            if len(logs) != 1:
                raise ValueError("missing unique action evidence")
            trajectory, contents = _native_action_trajectory(logs[0].parent)
            recovered = True
        else:
            raise ValueError("ambiguous action evidence")
        actions = _action_evidence(trajectory)
        patch = inputs["patch"].decode()
        base_files = inputs["base_files"]
        base_limited = len(_canonical(base_files)) > 2_000_000
        patch_limited = len(patch) > 2_000_000 or base_limited
        actions_limited = len(actions) > 10_000
        limited = patch_limited or actions_limited
        evidence = {
            "status": "partial" if limited else "complete",
            "limitations": (["packet_limit_exceeded"] if limited else [])
            + (["actions_recovered_from_native_events"] if recovered else []),
            "unavailable_dimensions": sorted(
                ({"regression_coverage", "requirements_fit"} if patch_limited else set())
                | (
                    {"self_verification", "regression_coverage", "research_depth"}
                    if actions_limited
                    else set()
                )
            ),
            "final_patch": patch if len(patch) <= 200_000 else None,
            "patch_chunks": [
                patch[i : i + 100_000] for i in range(0, min(len(patch), 2_000_000), 100_000)
            ]
            if len(patch) > 200_000
            else [],
            "patch_characters": len(patch),
            "base_files": None if base_limited else base_files,
            "actions": actions if len(actions) <= 10_000 else actions[:5000] + actions[-5000:],
            "action_count": len(actions),
            "action_digest": _sha256(contents),
        }
        if inputs.get("visual_evidence") is not None:
            evidence["visual_evidence"] = inputs["visual_evidence"]
        return evidence
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "unavailable"}


def _native_action_trajectory(logs: Path) -> tuple[dict, bytes]:
    """Recover bounded single-root command histories, never fabricate missing child work."""
    evidence, _ = _read(logs / "Trial_Evidence.json", "native evidence")
    identity, _ = _read(logs / "Root_Identity.json", "root identity")
    root = evidence.get("root_session_id")
    if (
        evidence.get("status") != "completed" or evidence.get("child_count") != 0
        or not isinstance(root, str) or not root
        # Codex's startup identity is null before thread/start assigns the root.
        or identity["root_session_id"] not in {None, root}
        or [s["session_id"] for s in evidence.get("sessions", [])] != [root]
    ):
        raise ValueError("native recovery requires one complete retained root")
    contents = (logs / "codex.txt").read_bytes()
    started, completed, turns, finished = {}, {}, set(), set()
    for line in contents.splitlines():
        event = json.loads(line)
        method, params = event.get("method"), event.get("params", {})
        if method not in {"item/started", "item/completed", "turn/started", "turn/completed"}:
            continue
        if params.get("threadId") != root:
            raise ValueError("native history includes an unaccounted thread")
        if method.startswith("turn/"):
            turn = params["turn"]
            target = turns if method == "turn/started" else finished
            if turn["id"] in target or (
                method == "turn/completed" and turn.get("status") != "completed"
            ):
                raise ValueError("native history has invalid turn completion")
            target.add(turn["id"])
            continue
        item = params["item"]
        key = (params["turnId"], item["id"])
        target = started if method == "item/started" else completed
        if key in target:
            raise ValueError("native history has duplicate item records")
        target[key] = item
    if not turns or turns != finished or not started or started.keys() != completed.keys():
        raise ValueError("native history is incomplete")
    steps = []
    for key, initial in started.items():
        item = completed[key]
        if key[0] not in turns or initial["type"] != item["type"]:
            raise ValueError("native history item identity mismatch")
        if item["type"] in {"reasoning", "agentMessage", "userMessage"}:
            continue  # Never include hidden reasoning or unrelated raw event fields.
        # ponytail: command-only single-root recovery; add typed converters before
        # accepting file changes, MCP calls or child sessions from this fallback.
        if item["type"] != "commandExecution" or not isinstance(item.get("command"), str):
            raise ValueError("unsupported native recovery action")
        if item.get("status") not in {"completed", "failed", "declined"}:
            raise ValueError("native command has no terminal status")
        call_id = item["id"]
        steps.append({
            "tool_calls": [{"tool_call_id": call_id, "function_name": "shell",
                            "arguments": {"cmd": item["command"]}}],
            "observation": {"results": [{
                "source_call_id": call_id, "content": item.get("aggregatedOutput"),
                "extra": {"exit_code": item.get("exitCode"), "status": item["status"]},
            }]},
        })
    if not steps:
        raise ValueError("native history has no inspectable commands")
    return {"steps": steps}, contents


def _wrapper_observations(result: dict | None) -> tuple[list[dict], list[str], int, bool]:
    """Decode retained transport blocks, never execute code or infer call/result pairing."""
    content = (result or {}).get("content")
    if isinstance(content, str):
        if len(content) > 32_000_000:
            return [], [], 0, False
        try:
            content = ast.literal_eval(content)
        except (ValueError, SyntaxError, RecursionError, MemoryError):
            return [], [], 0, False
    if not isinstance(content, list) or len(content) > 2000:
        return [], [], 0, False
    records, outputs, images = [], [], 0
    for index, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        if block.get("type") in {"input_image", "image"}:
            images += 1
        if block.get("type") not in {"input_text", "text"}:
            continue
        text = block.get("text")
        if not isinstance(text, str) or len(text) > 1_000_000:
            continue
        try:
            record = json.loads(text)
        except (ValueError, RecursionError):
            continue
        if not isinstance(record, dict):
            continue
        code = record.get("exit_code")
        if type(code) is int:
            records.append({"block": index, "exit_code": code})
        elif type(record.get("session_id")) is int:
            records.append({"block": index, "running": True})
        output = record.get("output")
        if isinstance(output, str):
            outputs.append(output)
    return records, outputs, images, True


def _action_evidence(trajectory: dict) -> list[dict]:
    from harness_testing.Public_Safety import _SECRET_VALUE
    from harness_testing.Trajectory_Events import _content_text, result_success

    aliases = {}

    def safe(value, limit=2000, *, command=False):
        if not isinstance(value, str) or len(value) > limit:
            return None
        secret_check = re.sub(r"([\"'])([A-Za-z_][\w-]*)\1(?=\s*[:=])", r"\2", value)
        if _SECRET_VALUE.search(secret_check):
            return None
        if not command:
            return value if not public_safety_errors(value) else None
        if re.search(r"(?:\.\./)+(?:Users|home|root|Volumes)(?:/|$)", value):
            return None

        def alias(match):
            path = match[0]
            quoted = path[0] in "\"'"
            quote = path[0] if quoted else ""
            path = path[1:-1] if quoted else path
            scratch = path.startswith(("/tmp/", "/var/tmp/", "/private/tmp/"))
            kind = "SCRATCH" if scratch else "PRIVATE"
            if path not in aliases:
                aliases[path] = f"{kind}_PATH_{len(aliases) + 1}"
            return quote + aliases[path] + quote

        # Private grading needs command semantics, not real host/scratch names.
        # These are presentation aliases, never executable shell or public exports.
        roots = r"(?:tmp|var/tmp|private/tmp|Users|home|root|Volumes|mnt|opt|harness-arm)"
        value = re.sub(rf"(?P<q>[\"'])/{roots}(?:/[^\n]*?)?(?P=q)", alias, value)
        value = re.sub(
            rf"(?<![\w:/])/{roots}(?:/[^\s<>\"'`;&|(){{}}\[\],]+)?"
            r"(?=$|[\s<>\"'`;&|(){}\[\],])", alias, value,
        )
        value = re.sub(
            r"(?<![\w:/])/(?:usr/)?bin/(bash|sh|env|node|python3?|git|npm|npx|cargo|rustc)"
            r"(?=$|[\s\"'])", r"\1", value,
        )
        value = re.sub(r"(?<![\w:/])/dev/null(?=$|[\s\"';|&])", "NULL_DEVICE", value)
        # This is private code evidence, not public prose: relative imports, JS
        # regexes, LaTeX and escaped newlines resemble paths to the export filter.
        # Never run that filter on commands or export these private packets.
        if re.search(
            r"file://|\b[A-Za-z]:[\\/]+[A-Za-z0-9_.-]"
            r"|(?:^|[\s\"'])\\\\[A-Za-z0-9_.-]{2,}\\[A-Za-z0-9_.-]+",
            value,
        ):
            return None
        return value

    actions = []
    for step in trajectory.get("steps", []):
        results = {
            r.get("source_call_id"): r for r in (step.get("observation") or {}).get("results", [])
        }
        for call in step.get("tool_calls") or []:
            arguments = call.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            result = results.get(call.get("tool_call_id"))
            wrapper = (
                call.get("function_name") in {"exec", "functions.exec"} and "input" in arguments
            )
            observations, outputs, images, decoded = (
                _wrapper_observations(result) if wrapper else ([], [], 0, True)
            )
            targets = {}
            for key in (
                "path",
                "file_path",
                "paths",
                "file",
                "pattern",
                "query",
                "q",
                "url",
                "urls",
                "search_query",
            ):
                value = arguments.get(key)
                if isinstance(value, list):
                    value = [
                        item.get("q") if isinstance(item, dict) else item for item in value[:20]
                    ]
                    targets[key] = [text for item in value if (text := safe(item)) is not None]
                elif (text := safe(value)) is not None:
                    targets[key] = text
            # Preserve only conventional numeric test summaries; never source, reasoning,
            # arbitrary command output or provider metadata. All are untrusted observations.
            summaries = []
            summary_text = "\n".join(outputs) if wrapper else _content_text(result)
            for line in summary_text.splitlines():
                line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
                if re.fullmatch(
                    r"(?:[#ℹ] )?(?:tests|suites|pass|fail|cancelled|skipped|todo)\s+\d+", line, re.I
                ) or re.fullmatch(
                    r"\d+ (?:passed|failed|skipped)(?:, \d+ (?:passed|failed|skipped))*"
                    r"(?: in [\d.]+s)?",
                    line,
                ) or re.fullmatch(
                    r"(?:Test Files|Tests|Test Suites):?\s+"
                    r"\d+ (?:passed|failed|skipped|total)"
                    r"(?:[, |]+\d+ (?:passed|failed|skipped|total))*(?: \(\d+\))?",
                    line,
                ) or re.fullmatch(
                    r"test result: (?:ok|FAILED)\. \d+ passed; \d+ failed; \d+ ignored; "
                    r"\d+ measured; \d+ filtered out; finished in [\d.]+s", line,
                ):
                    summaries.append(line)
            command = arguments.get("command", arguments.get("cmd"))
            if wrapper:
                command = arguments["input"]
            displayed = safe(command, limit=100_000, command=True)
            actions.append(
                {
                    "ordinal": len(actions) + 1,
                    "tool": safe(call.get("function_name")),
                    "command": displayed,
                    "targets": targets,
                    "test_summary": summaries[:30],
                    "success": None if wrapper else result_success(
                        result, step_extra=step.get("extra"), call_id=call.get("tool_call_id")
                    ),
                }
            )
            if isinstance(command, str) and displayed is None:
                actions[-1]["omissions"] = ["command_unavailable"]
            if wrapper:
                actions[-1].update({
                    "command_format": "javascript-wrapper",
                    "wrapper_results": observations,
                    "returned_image_count": images,
                })
                if not decoded:
                    actions[-1].setdefault("omissions", []).append("wrapper_results_unavailable")
    return actions


def prepare_grading(root: Path, report_path: Path, protocol_path: Path) -> dict:
    """Freeze randomized packets that contain no contender or model identity."""
    root = root.resolve()
    report = load_run_report(root, report_path.resolve())
    protocol, protocol_bytes = _read(protocol_path.resolve(), "collaboration grading protocol")
    _validate(root, "Collaboration Grading Protocol.schema.json", protocol)
    if report["experiment"]["conditions"]["decision_policy"] == "benchmark-readiness-v2":
        from harness_testing.Code_Reviews import _manifest_for_report, evaluation_protocol

        manifest = _manifest_for_report(root, report)
        frozen = evaluation_protocol(manifest, "quality")
        if protocol != frozen:
            raise ValueError("grading protocol differs from the frozen benchmark policy")
    trials = _eligible_trials(report)
    if not trials:
        raise ValueError("collaboration grading requires complete transcript evidence")
    protocol_id = _sha256(protocol_bytes)
    prepared = []
    for trial in trials:
        collaboration = trial["collaboration"]
        packet_id = "collaboration-" + secrets.token_hex(12)
        packet = {
            "schema_version": "1",
            "packet_id": packet_id,
            "task": {
                "instruction": _task_instruction(root, trial),
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
        if protocol["rubric_version"] == RUBRIC_VERSION:
            packet["work_evidence"] = _work_evidence(root, report, trial)
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
    if report["experiment"].get("evaluation_binding"):
        from harness_testing.Code_Reviews import _manifest_for_report

        _manifest_for_report(root, report)
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
    if source["experiment"]["conditions"]["decision_policy"] == "benchmark-readiness-v2":
        from harness_testing.Code_Reviews import _manifest_for_report

        _manifest_for_report(root, source)  # Reject host evaluator drift before revising evidence.
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
    if plan["protocol"]["rubric_version"] == RUBRIC_VERSION:
        for packet_id, mapping in planned.items():
            packet, _ = _read(directory / "Packets" / f"{packet_id}.json", "grading packet")
            visuals = packet["work_evidence"].get("visual_evidence")
            if (
                visuals
                and visuals["status"] != "complete"
                and any(
                    row["name"] == "requirements_fit" and row["score"] is not None
                    for row in summaries[mapping["trial_id"]]["dimensions"]
                )
            ):
                raise ValueError("visual requirements scores require rendered evidence")
            unavailable = packet["work_evidence"].get(
                "unavailable_dimensions",
                []
                if packet["work_evidence"]["status"] == "complete"
                else [
                    "self_verification",
                    "regression_coverage",
                    "requirements_fit",
                    "research_depth",
                ],
            )
            if any(
                row["score"] is not None and row["name"] in unavailable
                for row in summaries[mapping["trial_id"]]["dimensions"]
            ):
                raise ValueError("process scores require retained work evidence")
    revised = copy.deepcopy(source)
    # Retired human-preference fields stay in the immutable source only.
    for key in (
        "collaboration_calibration", "quality_calibration", "grader_validation", "preference"
    ):
        revised["experiment"].pop(key, None)
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
