"""Explicit model-free coordination of controlled and research comparison lanes."""

import copy
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from statistics import mean

from harness_testing.Comparisons import build_comparison, load_comparison_policy
from harness_testing.Experiments import contender_identity
from harness_testing.Quality import quality_score
from harness_testing.Run_Reports import load_run_report
from harness_testing.Runs import verify_manifest_document

# Exact request fields retained by attach_experiment_report; evidence fields are added later.
_REPORT_IDENTITY_FIELDS = (
    "request_id", "label", "purpose", "conditions", "contenders", "baseline_result_ids",
    "predecessor_result_ids", "first_version", "change",
)
# Differences here are expected between lanes and between a lane's continuation reports.
_LANE_FIELDS = {
    "task_ids",
    "task_variant",
    "task_digests",
    "evaluator_digest",
    "image_digests",
    "scripted_user_digest",
    "authority_digest",
}


def campaign_plan(root: Path, manifest_paths: list[Path]) -> dict:
    policy = json.loads((root / "policy/Benchmark Campaign.json").read_text())
    manifests = []
    for path in manifest_paths:
        manifest = json.loads(path.read_text())
        if verify_manifest_document(manifest) != manifest["digest"]:
            raise ValueError("invalid campaign manifest identity")
        manifests.append(manifest)
    unsigned = build_campaign(policy, manifests)
    digest = contender_identity(unsigned)
    plan = {"digest": digest, **unsigned}
    directory = root / "runs/campaigns" / digest[7:]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "Plan.json"
    content = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text() != content:
        raise ValueError("campaign recovery conflict")
    path.write_text(content)
    return {"plan": str(path), **plan}


def build_campaign(policy: dict, manifests: list[dict]) -> dict:
    lanes, shared, contenders, evaluations = {}, None, None, None
    execution = None
    for manifest in manifests:
        request = manifest["provenance"]["experiment"]
        conditions = request["conditions"]
        lane = conditions["task_variant"]
        tasks = {task for task, spec in policy["tasks"].items() if spec[0] == lane}
        if not tasks or lane in lanes or set(conditions["task_ids"]) != tasks:
            raise ValueError("campaign requires each complete declared lane exactly once")
        # A one-attempt pass over the full declared scope is decision evidence; the purpose
        # label records how the run was requested, not whether its trials count.
        if (
            request["purpose"] not in {"baseline", "diagnostic"}
            or request["baseline_result_ids"]
            or conditions["decision_policy"] != "benchmark-readiness-v2"
            or conditions["attempts"] < policy["minimum_attempts"]
        ):
            raise ValueError("campaign requires fresh decision baselines and sufficient attempts")
        roster = sorted(request["contenders"], key=lambda row: row["id"])
        if len(roster) != 3 or {row["family"] for row in roster} != {
            "nothing",
            "superpowers",
            "studio-moser",
        }:
            raise ValueError("campaign requires the three primary harnesses")
        common = {key: value for key, value in conditions.items() if key not in _LANE_FIELDS}
        runtime = {
            "skill_evaluation": request.get("skill_evaluation"),
            "billing_mode": request.get("limits", {}).get("billing_mode"),
            "interaction_limit": request.get("limits", {}).get("interaction_limit"),
        }
        if shared is not None and (
            shared != common
            or contenders != roster
            or evaluations != request["evaluation_inputs"]
            or execution != runtime
        ):
            raise ValueError("campaign lanes have incompatible harnesses, conditions or evaluators")
        shared, contenders, evaluations = common, roster, request["evaluation_inputs"]
        execution = runtime
        lanes[lane] = {
            "manifest_digest": manifest["digest"],
            "conditions": conditions,
            "report_identity": {key: request.get(key) for key in _REPORT_IDENTITY_FIELDS},
        }
    if set(lanes) != {spec[0] for spec in policy["tasks"].values()}:
        raise ValueError("campaign is missing a lane")
    trials = len(policy["tasks"]) * shared["attempts"] * len(contenders)
    return {
        "schema_version": "1",
        "policy": policy,
        "lanes": lanes,
        "conditions": shared,
        "contenders": contenders,
        "evaluation_inputs": evaluations,
        "execution": execution,
        "workload": {
            "coding_trials": trials,
            "quality_grader_sessions": trials,
            "patch_review_sessions": trials,
            "minimum_model_sessions": trials * 3,
            "confirmation_sessions": "additional-per-finding",
            "native_child_sessions": "additional-observed",
            "approval": "Each coding manifest and evaluation plan needs separate exact approval.",
        },
    }


def campaign_summary(root: Path, plan_path: Path, report_paths: list[Path]) -> dict:
    from harness_testing.Experiment_Reports import comparison_pricing

    plan = json.loads(plan_path.read_text())
    if plan["digest"] != contender_identity({k: v for k, v in plan.items() if k != "digest"}):
        raise ValueError("campaign plan identity mismatch")
    reports = [load_run_report(root, path) for path in report_paths]
    # The verdict uses the current policy and task list; retained evidence is unchanged.
    current = json.loads((root / "policy/Benchmark Campaign.json").read_text())
    return summarize_campaign(
        plan,
        reports,
        active_tasks=set(current["tasks"]),
        policy_for_lane=lambda conditions: load_comparison_policy(root, conditions)
        | {"pricing": comparison_pricing(root)},
        evaluation={
            "comparison_policy_matches_plan": json.loads(
                (root / "policy/Benchmark Policy.json").read_text()
            )
            == plan["evaluation_inputs"].get("comparison"),
        },
    )


def assemble_lane(plan: dict, lane: str, reports: list[dict]) -> dict:
    """Fill every scheduled slot of one lane from ordered original and continuation reports.

    Reports are applied in the given order. A later report replaces an earlier trial in the
    same slot only when the earlier trial did not complete, or when the task itself was
    corrected (a different task digest); a completed trial is never replaced by a rerun of
    the same task, so a favourable retry cannot be selected over a genuine failure.
    """
    frozen = plan["lanes"][lane]
    ids = {row["id"] for row in plan["contenders"]}
    attempts = plan["conditions"]["attempts"]
    if not reports or reports[0]["manifest_digest"] != frozen["manifest_digest"]:
        raise ValueError(f"{lane}: first report must belong to the frozen campaign manifest")
    if len({report["manifest_digest"] for report in reports}) != len(reports):
        raise ValueError(f"{lane}: select one immutable revision per manifest")
    anchor = reports[0]["experiment"]
    if (
        frozen.get("report_identity") != {key: anchor.get(key) for key in _REPORT_IDENTITY_FIELDS}
        or anchor["conditions"] != frozen["conditions"]
    ):
        raise ValueError(f"{lane}: report does not belong to frozen campaign")
    # A continuation may carry a corrected runtime adapter; that is disclosed, not hidden.
    continuation_fields = _LANE_FIELDS | {"adapter_digest"}
    shared = {k: v for k, v in plan["conditions"].items() if k not in continuation_fields}
    for report in reports:
        experiment = report["experiment"]
        conditions = experiment["conditions"]
        if (
            {k: v for k, v in conditions.items() if k not in continuation_fields} != shared
            or conditions["task_variant"] != lane
            or not set(conditions["task_ids"]) <= set(frozen["conditions"]["task_ids"])
            or not {row["id"] for row in experiment["contenders"]} <= ids
        ):
            raise ValueError(f"{lane}: continuation report has incompatible conditions")
    expected = {
        (c, task, a)
        for c in ids
        for task in frozen["conditions"]["task_ids"]
        for a in range(1, attempts + 1)
    }
    chosen: dict[tuple, tuple[dict, dict]] = {}
    superseded = []
    for report in reports:
        experiment = report["experiment"]
        digests = experiment["conditions"].get("task_digests") or {}
        seen = set()
        for trial in experiment["trials"]:
            slot = (trial["contender_id"], trial["task_id"], trial["attempt"])
            if slot not in expected or slot in seen:
                raise ValueError(f"{lane}: report contains an unscheduled or duplicated trial")
            seen.add(slot)
            if trial["status"] == "pending":
                continue
            if slot in chosen:
                previous, source = chosen[slot]
                same_task = (
                    (source["experiment"]["conditions"].get("task_digests") or {}).get(slot[1])
                    == digests.get(slot[1])
                )
                if previous["status"] == "completed" and same_task:
                    raise ValueError(
                        f"{lane}: a completed trial cannot be replaced without a task correction"
                    )
                superseded.append(
                    {
                        "trial_id": previous["trial_id"],
                        "report_id": source["report_id"],
                        "status": previous["status"],
                        "replaced_by": trial["trial_id"],
                        "task_corrected": not same_task,
                    }
                )
            chosen[slot] = (trial, report)
    missing = expected - set(chosen)
    if missing:
        raise ValueError(f"{lane}: campaign trial coverage is incomplete ({len(missing)} slots)")
    task_digests, image_digests = {}, dict(frozen["conditions"].get("image_digests") or {})
    for (_contender, task, _attempt), (_trial, report) in chosen.items():
        conditions = report["experiment"]["conditions"]
        digest = (conditions.get("task_digests") or {}).get(task)
        if task_digests.setdefault(task, digest) != digest:
            raise ValueError(f"{lane}: task inputs differ across contenders for {task}")
        for suffix in ("agent", "verifier"):
            key = f"{task}:{suffix}"
            if key in (conditions.get("image_digests") or {}):
                image_digests[key] = conditions["image_digests"][key]
    experiment = copy.deepcopy(frozen["report_identity"])
    experiment["conditions"] = dict(
        frozen["conditions"], task_digests=task_digests, image_digests=image_digests
    )
    experiment["trials"] = [
        trial for _, (trial, _) in sorted(chosen.items(), key=lambda item: item[0])
    ]
    return {
        "report_id": f"campaign:{lane}",
        "manifest_digest": frozen["manifest_digest"],
        "evidence": {"review_state": "unreviewed", "limitations": []},
        "experiment": experiment,
        "members": [
            {
                "report_id": report["report_id"],
                "manifest_digest": report["manifest_digest"],
                "label": report["experiment"].get("label"),
                "trials_used": sum(
                    1 for _, (_, source) in chosen.items() if source is report
                ),
                "evaluator_digest": report["experiment"]["conditions"].get("evaluator_digest"),
                "adapter_digest": report["experiment"]["conditions"].get("adapter_digest"),
                "adapter_corrected": report["experiment"]["conditions"].get("adapter_digest")
                != frozen["conditions"].get("adapter_digest"),
            }
            for report in reports
        ],
        "superseded_trials": superseded,
    }


def _retire_tasks(experiment: dict, active_tasks: set[str]) -> None:
    conditions = experiment["conditions"]
    kept = [task for task in conditions["task_ids"] if task in active_tasks]
    conditions["task_ids"] = kept
    for field in ("task_digests",):
        if isinstance(conditions.get(field), dict):
            conditions[field] = {k: v for k, v in conditions[field].items() if k in active_tasks}
    experiment["trials"] = [t for t in experiment["trials"] if t["task_id"] in active_tasks]


def summarize_campaign(
    plan: dict,
    reports: list[dict],
    *,
    policy_for_lane: Callable[[dict], dict] | None = None,
    evaluation: dict | None = None,
    active_tasks: set[str] | None = None,
) -> dict:
    """Summarize a campaign; tasks retired since it ran (not in active_tasks) are left out
    of every verdict and summary, while the retained evidence itself is unchanged."""
    lanes = plan["lanes"]
    by_lane: dict[str, list[dict]] = defaultdict(list)
    for report in reports:
        lane = report["experiment"]["conditions"]["task_variant"]
        if lane not in lanes:
            raise ValueError("report does not belong to a campaign lane")
        by_lane[lane].append(report)
    if set(by_lane) != set(lanes):
        raise ValueError("campaign requires both lane reports")
    ids = {row["id"] for row in plan["contenders"]}
    selected, trials, reasons, lane_results, lane_winners = {}, [], [], {}, []
    for lane in sorted(lanes):
        assembled = assemble_lane(plan, lane, by_lane[lane])
        experiment = assembled["experiment"]
        if active_tasks is not None:
            _retire_tasks(experiment, active_tasks)
        if policy_for_lane is not None:
            policy = policy_for_lane(experiment["conditions"])
            comparison = build_comparison(experiment, [assembled], policy)
            for pair in comparison["pairs"]:
                for field in ("left_report_id", "right_report_id"):
                    if pair[field] == experiment.get("request_id"):
                        pair[field] = None
        else:
            comparison = by_lane[lane][0]["experiment"].get("comparison") or {}
        experiment["comparison"] = comparison
        selected[lane] = [row["report_id"] for row in assembled["members"]]
        if comparison.get("status") not in {
            "recommended", "no_clear_winner", "no_quality_qualified_winner"
        }:
            reasons.append(f"{lane}:evaluation_incomplete")
        lane_winners.append(comparison.get("winner_id"))
        trials.extend(experiment["trials"])
        limitations = []
        if any(row["adapter_corrected"] for row in assembled["members"]):
            limitations.append(
                "Some slots were rerun under a corrected runtime adapter after the original "
                "attempt did not complete or its task was corrected; see members."
            )
        if assembled["superseded_trials"]:
            limitations.append(
                f"{len(assembled['superseded_trials'])} original trials were superseded by "
                "continuation or correction runs; the superseded trials are listed."
            )
        lane_results[lane] = {
            "limitations": limitations,
            "members": assembled["members"],
            "superseded_trials": assembled["superseded_trials"],
            "task_digests": experiment["conditions"]["task_digests"],
            "comparison": {
                key: comparison.get(key)
                for key in (
                    "status", "summary", "winner_id", "reasons", "leaders", "contenders",
                    "unsolved_tasks",
                )
            },
        }
    tasks = {
        task: spec for task, spec in plan["policy"]["tasks"].items()
        if active_tasks is None or task in active_tasks
    }
    groups = {"overall": set(tasks)}
    for task, (_, level, kind) in tasks.items():
        groups.setdefault(f"L{level}/{kind}", set()).add(task)
    groups["holdouts"] = set(plan["policy"]["holdouts"]) & set(tasks)
    summaries = {}
    for group, members in groups.items():
        summaries[group] = []
        for contender in sorted(ids):
            selected_trials = [
                t for t in trials if t["contender_id"] == contender and t["task_id"] in members
            ]
            by_task = defaultdict(list)
            for trial in selected_trials:
                by_task[trial["task_id"]].append(
                    quality_score(trial.get("collaboration", {}).get("grade"))
                )
            blocks = defaultdict(list)
            complete = all(score is not None for values in by_task.values() for score in values)
            if complete:
                for task, values in by_task.items():
                    blocks[plan["policy"]["matched_blocks"].get(task, task)].append(mean(values))
            summaries[group].append(
                {
                    "id": contender,
                    "trials": len(selected_trials),
                    "correct": sum(
                        t["status"] == "completed"
                        and t["correctness"] is True and t["protected_state"] is True
                        for t in selected_trials
                    ),
                    "outcomes": dict(Counter(t["status"] for t in selected_trials)),
                    "duration_seconds": _complete_total(selected_trials, "duration_seconds"),
                    "cost_usd": _complete_total(selected_trials, "cost_usd")
                    if all(t.get("usage_complete") is True for t in selected_trials) else None,
                    "usage_complete": bool(selected_trials)
                    and all(t.get("usage_complete") is True for t in selected_trials),
                    "quality": mean(mean(values) for values in blocks.values())
                    if complete and blocks
                    else None,
                }
            )
    # The campaign recommends a harness only when every lane recommends the same one.
    winner = (
        lane_winners[0]
        if not reasons and lane_winners and all(w == lane_winners[0] for w in lane_winners)
        else None
    )
    return {
        "campaign_digest": plan["digest"],
        "report_ids": selected,
        "status": "insufficient_evidence"
        if reasons
        else "recommended"
        if winner
        else "no_clear_winner",
        "winner_id": winner,
        "reasons": reasons,
        "lanes": lane_results,
        "summaries": summaries,
        "evaluation": evaluation or {},
        "scope": "Frozen toolbox and kickoff conditions only; not universal harness reliability.",
    }


def _complete_total(trials: list[dict], field: str) -> float | None:
    values = [t.get(field) for t in trials]
    if not values or any(
        type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values
    ):
        return None
    return sum(values)
