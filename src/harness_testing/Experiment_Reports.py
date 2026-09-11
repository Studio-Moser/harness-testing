"""Allowlisted per-trial evidence and derived harness comparisons."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from harness_testing.Comparisons import build_comparison
from harness_testing.Config import load_job, load_versions
from harness_testing.Experiments import (
    available_reference_reports,
    contender_identity,
    resolve_reference_reports,
)
from harness_testing.Workflow_Criteria import protected_files_intact


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


def _safe_trial(
    root: Path,
    task: str,
    contender_id: str,
    attempt: int,
    directory: Path | None,
    *,
    task_variant: str = "comparison",
) -> dict:
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
        protected_files_intact(
            workspace, root / "tasks/workflow" / task / "tests/Protected_Files.json"
        )
        if task_variant == "comparison" and workspace is not None and workspace.is_dir()
        else True
        if task_variant == "comparison" and correctness is True
        else None
    )
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
    if task_variant == "comparison":
        from harness_testing.Collaboration_Quality import (
            calculate_communication_metrics,
            validate_visible_transcript,
        )
        from harness_testing.Communication_Contracts import communication_contract_for_task

        frozen = communication_contract_for_task(root, task)
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
            prompt_path = root / "tasks" / "workflow" / task / "Comparison Instruction.md"
            collaboration = {
                "status": "complete",
                "reasons": [],
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
        resolve_reference_reports(request, available_reference_reports(root))
        if request["baseline_result_ids"] or request["predecessor_result_ids"]
        else []
    )
    policy = json.loads((root / "policy/Comparison Policy.json").read_text())
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
