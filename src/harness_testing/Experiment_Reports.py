"""Allowlisted per-trial evidence and derived harness comparisons."""

from __future__ import annotations

import copy
import json
import math
import re
import shlex
from pathlib import Path

from harness_testing.Comparisons import build_comparison, load_comparison_policy
from harness_testing.Config import load_job, load_versions
from harness_testing.Experiments import (
    available_reference_reports,
    contender_identity,
    resolve_reference_reports,
)
from harness_testing.Workflow_Criteria import protected_files_intact, verification_config_path


def _read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError("trial evidence is unreadable") from error
    if not isinstance(document, dict):
        raise ValueError("trial evidence must be an object")
    return document


def _finite(value):
    return value if type(value) in {float, int} and math.isfinite(value) and value >= 0 else None


def _research_protected_state(
    task_path: Path, rewards: dict | None, directory: Path | None
) -> bool | None:
    """The separate pinned verifier must account for every protected whitelist test."""
    config = _read(task_path / "tests/config.json")
    if config is None or rewards is None:
        return None
    patch = directory / "artifacts/logs/artifacts/model.patch" if directory else None
    if patch is None or not patch.is_file():
        return None
    # Upstream reapplies its tests, but runner/config tampering is only a signal.
    # Enforce that signal as an eligibility gate, independent of the reward.
    try:
        sections = patch.read_text().split("diff --git ")
        if sections[0].strip():
            return False
        for section in sections[1:]:
            header, _, body = section.partition("\n")
            paths = shlex.split(header)
            if len(paths) != 2 or any(
                not p.startswith(prefix) for p, prefix in zip(paths, ("a/", "b/"), strict=True)
            ):
                return False
            for raw in paths:
                path = Path(raw[2:])
                if path.is_absolute() or ".." in path.parts or "\\" in raw:
                    return False
                test_file = {"test", "tests", "__tests__"} & set(path.parts) or re.search(
                    r"\.(?:test|spec)\.", path.name
                )
                if verification_config_path(path) or (
                    test_file and not body.startswith("new file mode 100644\n")
                ):
                    return False
            if re.search(
                r"(?m)^(?:new file mode|new mode|old mode|deleted file mode) 120000$", body
            ):
                return False
    except (OSError, UnicodeError, ValueError):
        return None
    for prefix in ("f2p", "p2p"):
        nodes = config.get(f"{prefix}_node_ids")
        total = rewards.get(f"{prefix}_total")
        passed = rewards.get(f"{prefix}_passed")
        if not isinstance(nodes, list) or type(total) is not int or type(passed) is not int:
            return None
        if total != len(set(nodes)) or not 0 <= passed <= total:
            return False
        if rewards.get("reward") == 1 and passed != total:
            return False
    return bool(config["f2p_node_ids"]) and not rewards.get("apply_failed", 0)


def _price_usage(root: Path, usage: list[dict]) -> tuple[float | None, str]:
    prices = load_versions(root / "Versions.toml").get("models", [])
    digest = contender_identity({"pricing": prices})
    total = 0.0
    for row in usage:
        provider = {"openai": "codex", "anthropic": "claude"}.get(row["provider"], row["provider"])
        matches = [
            price
            for price in prices
            if price["provider"] == provider and price["model"] == row["model"]
        ]
        if len(matches) != 1:
            return None, digest
        price = matches[0]
        for category, field in [
            ("input_tokens", "input_usd_per_million_tokens"),
            ("output_tokens", "output_usd_per_million_tokens"),
            ("cache_read_tokens", "cache_read_usd_per_million_tokens"),
            ("cache_write_tokens", "cache_write_usd_per_million_tokens"),
        ]:
            tokens = row[category]
            if tokens is None or (tokens and field not in price):
                return None, digest
            if tokens:
                total += tokens * float(price[field]) / 1_000_000
    return _finite(total) if usage else None, digest


def comparison_pricing(root: Path) -> dict:
    """Reprice retained tokens under one documented standard-rate snapshot."""
    models = {}
    for row in load_versions(root / "Versions.toml").get("models", []):
        provider = {"codex": "openai", "claude": "anthropic"}[row["provider"]]
        rates = {
            f"{name}_per_million": float(row[f"{name}_usd_per_million_tokens"])
            if f"{name}_usd_per_million_tokens" in row
            else None
            for name in ("input", "output", "cache_read", "cache_write")
        }
        key = f"{provider}/{row['model']}"
        if key in models and models[key] != rates:
            raise ValueError("conflicting model pricing rows")
        models[key] = rates
    return {"digest": contender_identity({"standard_token_rates": models}), "models": models}


def _safe_simulated_user(root, raw, settings, expected_max_calls):
    """Separate allowlisted apparatus ledger; never add it to agent-tree usage."""
    if type(expected_max_calls) is not int or not 2 <= expected_max_calls <= 101:
        raise ValueError("missing approved simulated user call limit")
    if not isinstance(raw, dict):
        return None
    if any(raw.get(key) != settings[key] for key in ("protocol", "model", "effort")):
        raise ValueError("invalid simulated user identity")
    for key in ("call_count", "max_calls"):
        if type(raw.get(key)) is not int or raw[key] < 0:
            raise ValueError("invalid simulated user count")
    if raw["call_count"] > raw["max_calls"] or _finite(raw.get("duration_seconds")) is None:
        raise ValueError("invalid simulated user bounds")
    rows = []
    for source in raw.get("model_usage", []):
        if source.get("provider") != "openai" or source.get("model") != settings["model"]:
            raise ValueError("invalid simulated user usage identity")
        rows.append(
            {
                "provider": "openai",
                "model": settings["model"],
                **{
                    key: source[key] if type(source.get(key)) is int and source[key] >= 0 else None
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "cache_read_tokens",
                        "cache_write_tokens",
                    )
                },
            }
        )
    complete = (
        raw.get("usage_complete") is True
        and raw["max_calls"] == expected_max_calls
        and 1 <= raw["call_count"] <= expected_max_calls
        # Each isolated call has one pinned model and no children, so its
        # collector contributes exactly one model-usage row when complete.
        and len(rows) == raw["call_count"]
        and all(value is not None for row in rows for value in row.values())
    )
    cost, digest = _price_usage(root, rows)
    return {
        **{
            key: raw[key]
            for key in (
                "protocol",
                "model",
                "effort",
                "call_count",
                "max_calls",
                "duration_seconds",
            )
        },
        "usage_complete": complete,
        "model_usage": rows,
        "cost_usd": cost if complete else None,
        "pricing_digest": digest,
    }


def _safe_trial(
    root: Path,
    task: str,
    contender_id: str,
    attempt: int,
    directory: Path | None,
    *,
    task_variant: str = "comparison",
    task_path: Path | None = None,
    frozen_contract: dict | None = None,
    simulated_user: dict | None = None,
    simulated_user_max_calls: int | None = None,
) -> dict:
    task_path = task_path or root / "tasks/workflow" / task
    result = _read(directory / "result.json") if directory else None
    native = _read(directory / "agent/Trial_Evidence.json") if directory else None
    rewards = _read(directory / "verifier/reward.json") if directory else None
    native = native or {}
    recovery = native.get("provider_recovery")
    if recovery is not None:
        if not isinstance(recovery, dict) or not (
            type(recovery.get("allowance_seconds")) is int
            and 0 <= recovery["allowance_seconds"] <= 3600
            and type(recovery.get("transport_error_count")) is int
            and recovery["transport_error_count"] >= 0
            and type(recovery.get("extension_applied")) is bool
            and (
                not recovery["extension_applied"]
                or (recovery["allowance_seconds"] > 0 and recovery["transport_error_count"] > 0)
            )
        ):
            raise ValueError("invalid provider recovery evidence")
        recovery = {
            key: recovery[key]
            for key in ("allowance_seconds", "transport_error_count", "extension_applied")
        }
    status = native.get("status", "infrastructure_failure" if result else "pending")
    responder = (
        _safe_simulated_user(
            root, native.get("simulated_user"), simulated_user, simulated_user_max_calls
        )
        if simulated_user
        else None
    )
    if simulated_user and native and (responder is None or not responder["usage_complete"]):
        status = "infrastructure_failure"
    if status not in {
        "completed",
        "agent_failed",
        "timeout",
        "infrastructure_failure",
        "task_definition_gap",
        "cancelled",
        "pending",
    }:
        status = "agent_failed"
    if (result or {}).get("exception_info"):
        exception = result["exception_info"].get("exception_type")
        status = (
            "timeout"
            if exception == "AgentTimeoutError"
            and not (recovery and recovery["transport_error_count"])
            else "infrastructure_failure"
        )
    score = (rewards or {}).get("reward")
    correctness = score == 1 if type(score) in {int, float} and score in {0, 1} else None
    workspace = directory / "artifacts/workspace" if directory else None
    protected = (
        protected_files_intact(workspace, task_path / "tests/Protected_Files.json")
        if task_variant == "comparison" and workspace is not None and workspace.is_dir()
        else True
        if task_variant == "comparison" and correctness is True
        else None
    )
    if task_variant == "deepswe" and frozen_contract is not None:
        protected = _research_protected_state(task_path, rewards, directory)
    if task_variant == "comparison" and protected is False:
        # The local verifier short-circuits before testing modified protected trees.
        # Preserve the protection failure without inventing a functional verdict.
        correctness = None
    if task_variant == "deepswe" and (native or result or rewards):
        from harness_testing.Submission import submission_problem

        problem = submission_problem(task_path, directory)
        if problem:
            # Never grade an absent, overwritten, or ambiguous snapshot as a no-op.
            correctness = protected = None
            if status not in {"timeout", "cancelled"}:
                status = "infrastructure_failure"
            native = native | {
                "incomplete_reasons": list(dict.fromkeys(
                    native.get("incomplete_reasons", []) + [problem]
                ))
            }
    model_usage = []
    for row in native.get("model_usage", []):
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("provider"), str)
            or not isinstance(row.get("model"), str)
        ):
            raise ValueError("invalid model usage identity")
        model_usage.append(
            {
                "provider": row["provider"],
                "model": row["model"],
                **{
                    key: value if type(value := row.get(key)) is int and value >= 0 else None
                    for key in (
                        "input_tokens",
                        "cache_read_tokens",
                        "cache_write_tokens",
                        "output_tokens",
                    )
                },
            }
        )
    session_usage = [
        {
            key: row.get(key)
            for key in (
                "session",
                "provider",
                "model",
                "effort",
                "input_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "output_tokens",
            )
        }
        for row in native.get("session_usage", [])
        if isinstance(row, dict)
    ]
    complete = (
        native.get("usage_complete") is True
        and bool(model_usage)
        and all(all(value is not None for value in row.values()) for row in model_usage)
    )
    cost, pricing_digest = _price_usage(root, model_usage)
    collaboration = None
    if task_variant == "comparison" or frozen_contract is not None:
        from harness_testing.Collaboration_Quality import (
            calculate_communication_metrics,
            validate_visible_transcript,
        )
        from harness_testing.Communication_Contracts import load_communication_contract

        frozen = frozen_contract or load_communication_contract(
            task_path / "Communication Contract.json"
        )
        base = {
            "contract_digest": frozen["digest"],
            "contract": frozen["contract"],
        }
        try:
            transcript = validate_visible_transcript(native.get("transcript"))
        except ValueError as error:
            collaboration = {
                "status": "unavailable",
                "reasons": [str(error)],
                **base,
                "transcript": [],
                "metrics": None,
            }
        else:
            outputs = [row["output_tokens"] for row in model_usage]
            output_tokens = (
                sum(outputs) if outputs and all(value is not None for value in outputs) else None
            )
            prompt_path = task_path / "instruction.md"
            if not prompt_path.is_file():
                prompt_path = task_path / "Comparison Instruction.md"
            collaboration = {
                "status": "complete",
                "reasons": ["local_paths_omitted"]
                if transcript != native.get("transcript")
                else [],
                **base,
                "transcript": transcript,
                "metrics": calculate_communication_metrics(
                    transcript,
                    frozen["contract"],
                    task_text=prompt_path.read_text(),
                    model_output_tokens=output_tokens,
                ),
            }
    return {
        "trial_id": contender_identity(
            {"contender": contender_id, "task": task, "attempt": attempt}
        ),
        "task_id": task,
        "attempt": attempt,
        "contender_id": contender_id,
        "status": status,
        "correctness": correctness,
        "protected_state": protected,
        "duration_seconds": _finite(native.get("duration_seconds")),
        "usage_complete": complete,
        "cost_usd": cost if complete else None,
        "pricing_digest": pricing_digest,
        "model_usage": model_usage,
        "session_usage": session_usage,
        "interaction_count": native.get("interaction_count", 0),
        "child_count": native.get("child_count"),
        "incomplete_reasons": native.get("incomplete_reasons", []),
        **({"collaboration": collaboration} if collaboration is not None else {}),
        **({"provider_recovery": recovery} if recovery is not None else {}),
        **({"simulated_user": responder} if responder is not None else {}),
    }


def attach_experiment_report(
    root: Path, manifest, report: dict, previous: dict | None = None
) -> None:
    """Attach new evidence; retain the existing safe legacy reporting path."""
    request = manifest.provenance["experiment"]
    extension = {
        key: copy.deepcopy(request[key])
        for key in (
            "request_id",
            "label",
            "purpose",
            "conditions",
            "contenders",
            "baseline_result_ids",
            "predecessor_result_ids",
            "first_version",
            "change",
        )
    }
    trials = []
    for index, relative_path in enumerate(manifest.harbor_config_paths):
        from harness_testing.Runs import job_slot

        cell, task, scheduled_attempt = job_slot(manifest, index)
        job = load_job(manifest.path.parent / relative_path)
        from harness_testing.Materialize import _tree_digest

        task_path = root / job.datasets[0].path / task
        if _tree_digest(task_path) != request["conditions"]["task_digests"][task]:
            raise ValueError("frozen task inputs are missing or changed; cannot rebuild evidence")
        job_directory = root / "jobs/raw" / job.job_name
        directories = (
            sorted(
                path
                for path in job_directory.iterdir()
                if path.is_dir() and (path / "config.json").is_file()
            )
            if job_directory.is_dir()
            else []
        )
        if len(directories) > job.n_attempts:
            raise ValueError("unexpected trial directories: refusing to omit attempted work")
        for attempt in range(1, job.n_attempts + 1):
            directory = directories[attempt - 1] if attempt <= len(directories) else None
            trials.append(
                _safe_trial(
                    root,
                    task,
                    cell.contender["id"],
                    scheduled_attempt or attempt,
                    directory,
                    task_variant=request["conditions"]["task_variant"],
                    task_path=task_path,
                    frozen_contract=request.get("evaluation_inputs", {}).get("research_contract")
                    if request["conditions"]["task_variant"] == "deepswe"
                    else None,
                    simulated_user=request["conditions"].get("simulated_user"),
                    simulated_user_max_calls=request["limits"]["interaction_limit"] + 1,
                )
            )
    extension["trials"] = trials
    extension["comparison"] = None
    extension["supersedes_report_id"] = (
        previous.get("report_id")
        if previous and previous.get("status") in {"completed", "failed"}
        else (previous or {}).get("experiment", {}).get("supersedes_report_id")
    )
    report["schema_version"] = "3"
    report["experiment"] = extension
    costs = [trial["cost_usd"] for trial in trials]
    report["observed_api_equivalent_cost_usd"] = (
        sum(costs) if costs and all(cost is not None for cost in costs) else None
    )
    references = (
        resolve_reference_reports(
            request,
            available_reference_reports(
                root, set(request["baseline_result_ids"] + request["predecessor_result_ids"])
            ),
        )
        if request["baseline_result_ids"] or request["predecessor_result_ids"]
        else []
    )
    policy = load_comparison_policy(
        root, request["conditions"], request.get("evaluation_inputs", {}).get("comparison")
    )
    policy["pricing"] = comparison_pricing(root)
    # The provisional identity avoids a circular self-hash; the engine seeds from trial content.
    report["report_id"] = request["request_id"]
    extension["comparison"] = build_comparison(request, [report, *references], policy)

    # A report cannot contain its own content hash. Null denotes this report;
    # retained references keep their exact immutable report IDs.
    for pair in extension["comparison"]["pairs"]:
        for field in ("left_report_id", "right_report_id"):
            if pair[field] == request["request_id"]:
                pair[field] = None
