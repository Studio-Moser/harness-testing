"""Correctness-first conclusions over one fixed task suite: a per-task table and totals.

A contender is eligible when it matches the best correctness observed in the cohort and
its final-patch review finished without confirmed remaining defects. Among eligible
contenders, cost and time decide using plain ratio thresholds from the policy; there is
no resampling. Missing measurements stay unknown, never zero.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path

_ATTEMPTED = {"completed", "agent_failed", "timeout"}
_STATUSES = _ATTEMPTED | {"infrastructure_failure", "task_definition_gap", "cancelled", "pending"}
_LIMITS = [
    "This is an observed fixed-suite correctness judgment, not a universal reliability claim.",
    "One attempt per task is the default minimum; one flaky trial can change the verdict.",
    "Cost and time ratios are point estimates over per-task means; the advantage and "
    "noninferiority thresholds are product defaults, not research findings.",
    "Review is advisory: a missing or incomplete review leaves the verdict provisional and "
    "flagged, unconfirmed reviewer claims are listed, and confirmed remaining defects "
    "disqualify.",
]


def load_comparison_policy(root: Path, conditions: dict, frozen: dict | None = None) -> dict:
    policy = frozen or json.loads((root / "policy/Benchmark Policy.json").read_text())
    tasks = conditions["task_ids"]
    scope = next((s for s in policy["scopes"] if set(s) == set(tasks)), None)
    return policy | {
        "task_ids": scope or tasks,
        "required_task_count": len(scope or tasks),
        "declared_scope": scope is not None,
    }


def _digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _number(value, name):
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be finite and nonnegative or null")
    return value


def _mean(values):
    return math.fsum(values) / len(values)


def _success(trial):
    return (
        trial["status"] == "completed"
        and trial.get("correctness") is True
        and trial.get("protected_state") is True
    )


def code_review_summary(trials, scheduled):
    """Summarize review evidence without treating missing reviews as clean code."""
    reviews = [t["code_review"] for t in trials if t.get("code_review")]
    protocols = {r["protocol_id"] for r in reviews}
    completed = sum(r["status"] == "completed" for r in reviews)
    findings = [finding for review in reviews for finding in review["findings"]]
    costs = [r.get("cost_usd") for r in reviews]
    internal = [
        r["internal_review"]
        for r in reviews
        if r.get("internal_review", {}).get("status") == "recorded"
    ]
    return {
        "status": "not_reviewed"
        if not reviews
        else "incompatible"
        if len(protocols) != 1
        else "completed"
        if completed == scheduled
        else "incomplete",
        "completed": completed,
        "scheduled": scheduled,
        "protocol_id": next(iter(protocols)) if len(protocols) == 1 else None,
        "confirmed": {
            severity: sum(
                f["status"] == "confirmed" and f["severity"] == severity for f in findings
            )
            for severity in ("P0", "P1", "P2", "P3")
        },
        "unconfirmed": sum(f["status"] == "unconfirmed" for f in findings),
        "evaluation_cost_usd": math.fsum(costs)
        if len(reviews) == scheduled and costs and all(c is not None for c in costs)
        else None,
        "internal_review": {
            "recorded": len(internal),
            "scheduled": scheduled,
            **{
                field: sum(r[field] for r in internal) if len(internal) == scheduled else None
                for field in ("found", "fixed", "unresolved")
            },
        },
    }


def _cost(trial, pricing):
    if not trial.get("usage_complete"):
        return None
    if pricing is None:
        return trial.get("cost_usd") if trial.get("pricing_digest") else None
    usage = trial.get("model_usage")
    if not usage:
        return None
    costs = []
    for row in usage:
        rates = pricing["models"].get(f"{row.get('provider')}/{row.get('model')}")
        if rates is None:
            return None
        for category, rate in (
            ("input_tokens", "input_per_million"),
            ("output_tokens", "output_per_million"),
            ("cache_read_tokens", "cache_read_per_million"),
            ("cache_write_tokens", "cache_write_per_million"),
        ):
            tokens = row.get(category)
            price = rates.get(rate)
            if tokens is None or price is None:
                return None
            costs.append(tokens * price / 1_000_000)
    return _number(math.fsum(costs), "repriced cost")


def _dataset(report, contender, conditions, pricing):
    """One contender's trials in one report, checked and summarized."""
    tasks = conditions["task_ids"]
    repetitions = conditions["attempts"]
    fields = (
        "trial_id", "task_id", "attempt", "contender_id", "status", "correctness",
        "protected_state", "duration_seconds", "usage_complete", "cost_usd", "pricing_digest",
        "model_usage", "code_review",
    )
    selected = [
        {field: t.get(field) for field in fields}
        for t in report["experiment"].get("trials", [])
        if t.get("contender_id") == contender["id"]
    ]
    slots, ids = set(), set()
    for trial in selected:
        attempt = trial.get("attempt")
        if type(attempt) is not int or not 1 <= attempt <= repetitions:
            raise ValueError("trial attempt is outside the schedule")
        slot = (trial.get("task_id"), attempt)
        if slot[0] not in tasks or slot in slots:
            raise ValueError("trial has an unknown task or duplicate scheduled slot")
        if not trial.get("trial_id") or trial["trial_id"] in ids:
            raise ValueError("trial identity must be present and unique")
        slots.add(slot)
        ids.add(trial["trial_id"])
        if trial.get("status") not in _STATUSES:
            raise ValueError("unknown trial status")
        for field in ("correctness", "protected_state"):
            if trial.get(field) is not None and type(trial[field]) is not bool:
                raise ValueError(f"{field} must be boolean or null")
        if type(trial.get("usage_complete")) is not bool:
            raise ValueError("usage_complete must be boolean")
        for field in ("cost_usd", "duration_seconds"):
            _number(trial.get(field), field)
        if not isinstance(trial.get("model_usage"), list) or not all(
            isinstance(row, dict) for row in trial["model_usage"]
        ):
            raise ValueError("model_usage must be a list of usage objects")
        for row in trial["model_usage"]:
            for field in (
                "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"
            ):
                _number(row.get(field), field)
    selected.sort(key=lambda t: (t["task_id"], t["attempt"], t["trial_id"]))
    counts = {status: sum(t["status"] == status for t in selected) for status in sorted(_STATUSES)}
    scheduled = len(tasks) * repetitions
    counts["missing"] = scheduled - len(selected)
    counts["missing_grading"] = sum(
        t["status"] in _ATTEMPTED
        and (t.get("correctness") is None or t.get("protected_state") is None)
        for t in selected
    )
    complete = not any(counts[s] for s in (_STATUSES - _ATTEMPTED) | {"missing", "missing_grading"})
    attempted = [t for t in selected if t["status"] in _ATTEMPTED or t.get("model_usage")]
    costs = [_cost(t, pricing) for t in attempted]
    cost_known = bool(attempted) and all(c is not None for c in costs)
    total = _number(math.fsum(costs), "total cost") if cost_known else None
    successes = sum(_success(t) for t in selected)
    token_counts = [
        row.get(field)
        for trial in attempted
        for row in trial.get("model_usage", [])
        for field in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")
    ]
    tokens_known = (
        bool(attempted)
        and all(trial.get("usage_complete") and trial.get("model_usage") for trial in attempted)
        and all(value is not None for value in token_counts)
    )
    review = code_review_summary(selected, scheduled)
    # Per-task means so every task weighs the same regardless of its absolute workload.
    by_task = {task: [t for t in selected if t["task_id"] == task] for task in sorted(tasks)}

    def task_mean(groups):
        if not complete or any(not g or any(v is None for v in g) for g in groups):
            return None
        return _mean([_mean(g) for g in groups])

    public = {
        **{key: contender.get(key) for key in ("id", "family", "label")},
        "scheduled": scheduled,
        "completed": counts["completed"],
        "attempted": len(attempted),
        "successes": successes,
        "success_fraction": {"numerator": successes, "denominator": scheduled},
        "passed_all": complete and successes == scheduled,
        "reviewed": review["status"] == "completed",
        "review_clean": not any(review["confirmed"].values()),
        "eligible": False,
        "coverage_complete": complete,
        "counts": counts,
        "task_successes": {
            task: sum(_success(t) for t in group) for task, group in by_task.items()
        },
        "repetitions": repetitions,
        "total_cost_usd": total,
        "total_tokens": sum(token_counts) if tokens_known else None,
        "cost_per_success_usd": total / successes if total is not None and successes else None,
        "mean_cost_usd": task_mean([[_cost(t, pricing) for t in g] for g in by_task.values()]),
        "mean_duration_seconds": task_mean(
            [[t.get("duration_seconds") for t in g] for g in by_task.values()]
        ),
        "usage_complete": bool(attempted) and all(t["usage_complete"] for t in attempted),
        "pricing_digest": pricing["digest"] if pricing else None,
        "original_estimates": [
            {
                "trial_id": t["trial_id"],
                "cost_usd": t.get("cost_usd"),
                "pricing_digest": t.get("pricing_digest"),
            }
            for t in attempted
        ],
        "code_review": review,
    }
    if pricing is None:
        prices = {t.get("pricing_digest") for t in attempted}
        if len(prices) != 1 or None in prices:
            public.update(total_cost_usd=None, cost_per_success_usd=None, mean_cost_usd=None)
        else:
            public["pricing_digest"] = next(iter(prices))
    return public


def _ratio(left, right):
    if left is None or right is None or right == 0:
        return None
    return left / right


def _difference(left, right):
    return None if left is None or right is None else left - right


def _pair(left_key, right_key, left, right, current_id):
    def report_id(key):
        return None if key[0] == current_id else key[0]

    return {
        "left_id": left["id"],
        "right_id": right["id"],
        "left_report_id": report_id(left_key),
        "right_report_id": report_id(right_key),
        "cost_ratio": _ratio(left["mean_cost_usd"], right["mean_cost_usd"]),
        "time_ratio": _ratio(left["mean_duration_seconds"], right["mean_duration_seconds"]),
        "cost_difference_usd": _difference(left["mean_cost_usd"], right["mean_cost_usd"]),
        "time_difference_seconds": _difference(
            left["mean_duration_seconds"], right["mean_duration_seconds"]
        ),
    }


def _inverse(pair):
    return {
        "cost_ratio": _ratio(1.0, pair["cost_ratio"]),
        "time_ratio": _ratio(1.0, pair["time_ratio"]),
    }


def _dominates(pair, policy):
    """Left wins when it is clearly better on cost or time and not worse on the other."""
    cost, time = pair["cost_ratio"], pair["time_ratio"]
    if cost is None or time is None:
        return False
    advantage, noninferior = policy["advantage_ratio"], policy["noninferiority_ratio"]
    return (cost <= advantage and time <= noninferior) or (
        time <= advantage and cost <= noninferior
    )


def build_comparison(request: dict, reports: list[dict], policy: dict) -> dict:
    """Compare exact selections; no report is chosen by timestamp or label."""
    policy = dict(policy, code_review_policy="final-patch-review-v1")
    pricing = policy.get("pricing")
    if pricing is not None:
        if not pricing.get("digest") or not isinstance(pricing.get("models"), dict):
            raise ValueError("pricing requires a frozen digest and per-provider/model rates")
        for rates in pricing["models"].values():
            for value in rates.values():
                _number(value, "pricing rate")
    conditions = request["conditions"]
    tasks = conditions.get("task_ids", [])
    attempts = conditions.get("attempts")
    if (
        not tasks
        or not all(isinstance(t, str) and t for t in tasks)
        or len(set(tasks)) != len(tasks)
        or type(attempts) is not int
        or attempts < 1
    ):
        raise ValueError("conditions require unique task IDs and positive integer attempts")
    baseline_ids = request.get("baseline_result_ids", [])
    if len(set(baseline_ids)) != len(baseline_ids):
        raise ValueError("duplicate selected evidence IDs")
    contender_ids = [c["id"] for c in request["contenders"]]
    if not contender_ids or len(set(contender_ids)) != len(contender_ids):
        raise ValueError("request contenders must be nonempty and unique")
    references = set(baseline_ids)
    by_id = {}
    for report in reports:
        if report["report_id"] in by_id:
            raise ValueError("duplicate report ID")
        by_id[report["report_id"]] = report
    current = [
        r
        for r in reports
        if r["report_id"] not in references
        and (
            r.get("experiment", {}).get("request_id") == request["request_id"]
            if request.get("request_id")
            else sorted(c["id"] for c in r.get("experiment", {}).get("contenders", []))
            == sorted(contender_ids)
        )
    ]
    result = {
        "status": "insufficient_evidence",
        "winner_id": None,
        "summary": "Selected evidence is insufficient for a recommendation.",
        "reasons": [],
        "contenders": [],
        "pairs": [],
        "leaders": {"observed_cost_ids": [], "observed_time_ids": []},
        "provisional": True,
        "limitations": list(_LIMITS),
        "policy_id": policy["policy_id"],
        "policy_digest": _digest(policy),
        "unsolved_tasks": [],
    }
    reasons = result["reasons"]
    if conditions.get("decision_policy") != policy["policy_id"]:
        result.update(status="incompatible_conditions", summary="Decision policy does not match.")
        reasons.append("decision_policy_mismatch")
        return result
    from harness_testing.Materialize import DEEPSWE_TASK_IDS

    neutral = conditions.get("task_variant") == "comparison" and set(tasks) <= set(
        policy["task_ids"]
    )
    research = conditions.get("task_variant") == "deepswe" and set(tasks) <= set(
        DEEPSWE_TASK_IDS
    )
    if not neutral and not research:
        result.update(
            status="incompatible_conditions", summary="Neutral comparison tasks are required."
        )
        reasons.append("non_neutral_tasks")
        return result
    if len(current) != 1 or any(i not in by_id for i in baseline_ids):
        reasons.append("missing_or_ambiguous_evidence")
        return result
    current = current[0]
    current_id = current["report_id"]
    cohort_reports = [current] + [by_id[i] for i in baseline_ids]
    if any(r.get("experiment", {}).get("conditions") != conditions for r in cohort_reports):
        result.update(status="incompatible_conditions", summary="Selected conditions do not match.")
        reasons.append("incompatible_conditions")
        return result
    if {c["id"] for c in current["experiment"]["contenders"]} != set(contender_ids):
        reasons.append("contender_identity_mismatch")
        return result
    datasets, cohort = {}, []
    for report in cohort_reports:
        declared = report["experiment"]["contenders"]
        declared_ids = [c["id"] for c in declared]
        if len(set(declared_ids)) != len(declared_ids):
            raise ValueError("report contender identities must be unique")
        if any(
            t.get("contender_id") not in declared_ids
            for t in report["experiment"].get("trials", [])
        ):
            raise ValueError("trial references undeclared contender")
        for contender in declared:
            key = (report["report_id"], contender["id"])
            datasets.setdefault(key, _dataset(report, contender, conditions, pricing))
            if key not in cohort:
                cohort.append(key)
    if len({key[1] for key in cohort}) != len(cohort):
        reasons.append("ambiguous_contender_evidence")
        return result
    cohort.sort()
    # A task nobody solved says nothing about which contender is better.
    best = max(datasets[k]["successes"] for k in cohort)
    for key in cohort:
        public = datasets[key]
        public["eligible"] = (
            public["coverage_complete"] and public["successes"] >= best and public["review_clean"]
        )
    result["unsolved_tasks"] = [
        task for task in tasks if all(datasets[k]["task_successes"][task] == 0 for k in cohort)
    ]
    if result["unsolved_tasks"]:
        result["limitations"].append(
            "Some tasks were solved by no contender; they cannot separate the contenders and "
            "are listed under unsolved_tasks."
        )
    result["contenders"] = [datasets[k] for k in cohort]
    result["pairs"] = [
        _pair(left, right, datasets[left], datasets[right], current_id)
        for left, right in itertools.combinations(cohort, 2)
    ]
    reviews = [datasets[k]["code_review"] for k in cohort]
    if any(r["status"] in {"not_reviewed", "incomplete"} for r in reviews):
        reasons.append("code_review_incomplete")
    if any(r["status"] == "incompatible" for r in reviews) or (
        len({r["protocol_id"] for r in reviews if r["protocol_id"] is not None}) > 1
    ):
        reasons.append("code_review_protocol_mismatch")
    if any(r["unconfirmed"] for r in reviews):
        reasons.append("code_review_unconfirmed")
    if any(any(r["confirmed"].values()) for r in reviews):
        reasons.append("code_review_defects")
    result["provisional"] = False
    covered = set(tasks) == set(policy["task_ids"]) and policy.get("declared_scope", True)
    enough = covered and attempts >= policy["minimum_repetitions"]
    if not covered:
        reasons.append("insufficient_task_coverage")
    if attempts < policy["minimum_repetitions"]:
        reasons.append("insufficient_repetitions")
    coverage_complete = all(datasets[k]["coverage_complete"] for k in cohort)
    if not coverage_complete:
        reasons.append("incomplete_coverage")
    for key in cohort:
        public = datasets[key]
        if not public["eligible"]:
            reasons.append("quality_ineligible")
        if not public["usage_complete"]:
            reasons.append("usage_incomplete")
        if public["total_cost_usd"] is None:
            reasons.append("pricing_unavailable")
        if public["mean_duration_seconds"] is None:
            reasons.append("duration_unavailable")
    if len({datasets[k]["pricing_digest"] for k in cohort}) != 1:
        reasons.append("pricing_unavailable")
    result["reasons"] = reasons = list(dict.fromkeys(reasons))
    eligible = [k for k in cohort if datasets[k]["eligible"]]
    for field, leader in (
        ("mean_cost_usd", "observed_cost_ids"),
        ("mean_duration_seconds", "observed_time_ids"),
    ):
        values = [datasets[k][field] for k in eligible]
        if values and all(v is not None for v in values):
            result["leaders"][leader] = sorted(
                k[1] for k in eligible if datasets[k][field] == min(values)
            )
    pairs = {(p["left_id"], p["right_id"]): p for p in result["pairs"]}

    def pair_between(left, right):
        pair = pairs.get((left[1], right[1]))
        return pair if pair is not None else _inverse(pairs[(right[1], left[1])])

    # Review is advisory: an incomplete review keeps the verdict provisional and flagged,
    # while confirmed remaining defects still disqualify a contender.
    if any(not datasets[k]["reviewed"] for k in cohort):
        result["provisional"] = True
    if enough and coverage_complete:
        result.update(
            status="no_clear_winner", summary="No clear overall winner in the selected evidence."
        )
        if not eligible:
            result.update(
                status="no_quality_qualified_winner",
                summary="No contender reached the best observed correctness with complete "
                "coverage and no confirmed remaining defects.",
            )
        elif len(eligible) == 1:
            result.update(
                status="recommended",
                winner_id=eligible[0][1],
                summary="One contender reached the best observed correctness with no confirmed "
                "remaining defects.",
            )
            reasons.append("sole_quality_eligible")
        else:
            for key in eligible:
                if all(
                    _dominates(pair_between(key, other), policy)
                    for other in eligible
                    if other != key
                ):
                    result.update(
                        status="recommended",
                        winner_id=key[1],
                        summary="A practical cost or time advantage with noninferiority is "
                        "supported against every other eligible contender.",
                    )
                    reasons.append("practical_advantage_supported")
                    break
            cost_leaders = set(result["leaders"]["observed_cost_ids"])
            time_leaders = set(result["leaders"]["observed_time_ids"])
            if cost_leaders and time_leaders and not (cost_leaders & time_leaders):
                reasons.append("cost_time_tradeoff")
    return result
