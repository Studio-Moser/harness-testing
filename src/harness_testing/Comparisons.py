"""Correctness-first conclusions for explicitly selected, fixed-suite evidence.

Token input is exclusive of cache reads/writes. Missing token categories are unknown,
not zero. Report estimates are comparable only under one retained pricing identity.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random

_ATTEMPTED = {"completed", "agent_failed", "timeout"}
_STATUSES = _ATTEMPTED | {"infrastructure_failure", "task_definition_gap", "cancelled", "pending"}
_DEFAULTS = {
    "policy_id": "development-comparison-v1",
    "required_task_count": 9,
    "task_ids": [
        "react-accent-polish",
        "react-active-badge-count",
        "react-grouped-ui-updates",
        "react-saved-view-feature",
        "rust-quoted-value-parser",
        "rust-workspace-warning-summary",
        "static-accessible-disclosure",
        "static-grouped-page-updates",
        "static-pricing-copy-polish",
    ],
    "minimum_repetitions": 3,
    "bootstrap_draws": 20000,
    "family_error_rate": 0.05,
    "advantage_ratio": 0.9,
    "noninferiority_ratio": 1.1,
}
_LIMITS = [
    "This is an observed fixed-suite correctness judgment, not a universal reliability claim.",
    "Intervals describe repetition variation within the selected fixed tasks; they do not cover "
    "model drift, provider load changes, new tasks, or broad software quality.",
    "Three repetitions are the default minimum. Identical repetitions can yield narrow intervals "
    "without proving universal stability.",
    "Historical time comparisons are observational; they do not establish causality.",
    "The 10% advantage and noninferiority thresholds are product defaults, not research findings.",
    "No clear change does not establish equivalence.",
]


def _is_quill_deepswe_diagnostic(request, conditions):
    return (
        request.get("purpose") == "diagnostic"
        and conditions.get("task_variant") == "deepswe"
        and conditions.get("task_ids") == ["quill-shared-toolbar-focus"]
    )


def _digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


def _number(value, name):
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be finite and nonnegative or null")
    return value


def _sum(values):
    try:
        total = math.fsum(values)
    except OverflowError as error:
        raise ValueError("aggregate is not representable as a finite JSON number") from error
    return _number(total, "aggregate")


def _mean(values):
    return _sum(values) / len(values)


def _success(trial):
    return (
        trial["status"] == "completed"
        and trial.get("correctness") is True
        and trial.get("protected_state") is True
    )


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
        for category, rate in [
            ("input_tokens", "input_per_million"),
            ("output_tokens", "output_per_million"),
            ("cache_read_tokens", "cache_read_per_million"),
            ("cache_write_tokens", "cache_write_per_million"),
        ]:
            tokens = row.get(category)
            price = rates.get(rate)
            if tokens is None or price is None:
                return None
            costs.append(tokens * price / 1_000_000)
    return _number(_sum(costs), "repriced cost")


def _dataset(report, contender, conditions, pricing):
    tasks = conditions["task_ids"]
    repetitions = conditions["attempts"]
    allowed_trial_fields = (
        "trial_id",
        "task_id",
        "attempt",
        "contender_id",
        "status",
        "correctness",
        "protected_state",
        "duration_seconds",
        "usage_complete",
        "cost_usd",
        "pricing_digest",
        "model_usage",
    )
    selected = [
        {field: t.get(field) for field in allowed_trial_fields}
        for t in report["experiment"].get("trials", [])
        if t.get("contender_id") == contender["id"]
    ]
    slots = set()
    trial_ids = set()
    for trial in selected:
        attempt = trial.get("attempt")
        if type(attempt) is not int or not 1 <= attempt <= repetitions:
            raise ValueError("trial attempt is outside the schedule")
        slot = (trial.get("task_id"), attempt)
        if slot[0] not in tasks or slot in slots:
            raise ValueError("trial has an unknown task or duplicate scheduled slot")
        if not trial.get("trial_id") or trial["trial_id"] in trial_ids:
            raise ValueError("trial identity must be present and unique")
        slots.add(slot)
        trial_ids.add(trial["trial_id"])
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
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
            ):
                _number(row.get(field), field)
    selected.sort(key=lambda t: (t["task_id"], t["attempt"], t["trial_id"]))
    counts = {status: sum(t["status"] == status for t in selected) for status in sorted(_STATUSES)}
    counts["missing"] = len(tasks) * repetitions - len(selected)
    counts["missing_grading"] = sum(
        t["status"] in _ATTEMPTED
        and (t.get("correctness") is None or t.get("protected_state") is None)
        for t in selected
    )
    complete = not any(counts[s] for s in (_STATUSES - _ATTEMPTED) | {"missing", "missing_grading"})
    attempted = [t for t in selected if t["status"] in _ATTEMPTED or t.get("model_usage")]
    costs = [_cost(t, pricing) for t in attempted]
    cost_known = bool(attempted) and all(c is not None for c in costs)
    total = _number(_sum(costs), "total cost") if cost_known else None
    successes = sum(_success(t) for t in selected)
    durations = [t.get("duration_seconds") for t in attempted]
    durations_known = bool(attempted) and all(d is not None for d in durations)
    task_successes = {
        task: sum(_success(t) for t in selected if t["task_id"] == task) for task in tasks
    }
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
    public = {
        **{key: contender.get(key) for key in ("id", "family", "label")},
        "scheduled": len(tasks) * repetitions,
        "completed": counts["completed"],
        "attempted": len(attempted),
        "successes": successes,
        "success_fraction": {"numerator": successes, "denominator": len(tasks) * repetitions},
        "eligible": complete and successes == len(tasks) * repetitions,
        "coverage_complete": complete,
        "counts": counts,
        "task_successes": task_successes,
        "repetitions": repetitions,
        "total_cost_usd": total,
        "total_tokens": sum(token_counts) if tokens_known else None,
        "cost_per_success_usd": total / successes if total is not None and successes else None,
        "mean_duration_seconds": _mean(durations) if durations_known else None,
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
    }
    groups = [[t for t in selected if t["task_id"] == task] for task in sorted(tasks)]
    # Every selected task has equal weight, irrespective of its absolute workload.
    cost_groups = [[_cost(t, pricing) for t in group] for group in groups]
    time_groups = [[t.get("duration_seconds") for t in group] for group in groups]
    metric_groups = []
    for metric in (cost_groups, time_groups):
        metric_groups.append(
            metric
            if complete
            and all(group and all(value is not None for value in group) for group in metric)
            else None
        )
    public["mean_cost_usd"] = (
        _mean([_mean(g) for g in metric_groups[0]]) if metric_groups[0] is not None else None
    )
    return {
        "public": public,
        "groups": metric_groups,
        "trials": selected,
        "report_id": report["report_id"],
        "key": (report["report_id"], contender["id"]),
    }


def _percentile(values, probability):
    position = (len(values) - 1) * probability
    low = math.floor(position)
    high = math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def _bootstrap(datasets, pair_keys, policy, seed):
    draws = policy["bootstrap_draws"]
    sampled = {}
    for key in sorted(datasets):
        dataset = datasets[key]
        rng = random.Random(_digest([seed, dataset["sampling_identity"]]))
        groups = dataset["groups"]
        metrics = []
        for group in groups:
            if group is None:
                metrics.append(None)
            elif all(len(set(task)) == 1 for task in group):
                metrics.append([_mean([task[0] for task in group])] * draws)
            else:
                metrics.append([])
        varying = any(metric == [] for metric in metrics)
        for _ in range(draws if varying else 0):
            values = [[], []]
            for task_index in range(len(groups[0] or groups[1] or [])):
                task = (groups[0] or groups[1])[task_index]
                indices = [rng.randrange(len(task)) for _ in task]
                for index, metric in enumerate(groups):
                    if metric is not None and len(metrics[index]) < draws:
                        values[index].append(_mean([metric[task_index][i] for i in indices]))
            for index in range(2):
                if values[index]:
                    metrics[index].append(_mean(values[index]))
        sampled[key] = metrics
    tail = policy["family_error_rate"] / (4 * len(pair_keys)) if pair_keys else None
    pairs = {}
    for left, right in sorted(pair_keys):
        pair = {
            "left_id": left[1],
            "right_id": right[1],
            "left_report_id": left[0],
            "right_report_id": right[0],
        }
        for index, name, difference in [
            (0, "cost_ratio", "cost_difference_usd"),
            (1, "time_ratio", "time_difference_seconds"),
        ]:
            lg, rg = datasets[left]["groups"][index], datasets[right]["groups"][index]
            pair[name] = None
            pair[difference] = None
            if index == 0 and (
                datasets[left]["public"]["pricing_digest"]
                != datasets[right]["public"]["pricing_digest"]
            ):
                continue
            if lg is None or rg is None:
                continue
            lm, rm = _mean([_mean(g) for g in lg]), _mean([_mean(g) for g in rg])
            pair[difference] = lm - rm
            if lm == rm == 0:
                pair[name] = {"estimate": 1.0, "lower": 1.0, "upper": 1.0}
                continue
            if lm == 0 or rm == 0:
                continue
            ratios = []
            for a, b in zip(sampled[left][index], sampled[right][index], strict=True):
                if a == 0 or b == 0:
                    break
                ratios.append(a / b)
            if len(ratios) == draws and all(math.isfinite(r) and r > 0 for r in ratios):
                ratios.sort()
                pair[name] = {
                    "estimate": lm / rm,
                    "lower": _percentile(ratios, tail),
                    "upper": _percentile(ratios, 1 - tail),
                }
        pairs[(left, right)] = pair
    return pairs, tail


def _dominates(pair, reverse, policy):
    ratios = [pair["cost_ratio"], pair["time_ratio"]]
    if any(r is None for r in ratios):
        return False
    bounds = [1 / r["lower"] if reverse else r["upper"] for r in ratios]
    return (
        min(bounds) <= policy["advantage_ratio"] and max(bounds) <= policy["noninferiority_ratio"]
    )


def _tradeoff(pair):
    cost, duration = pair["cost_ratio"], pair["time_ratio"]
    return bool(
        cost
        and duration
        and (
            (cost["upper"] < 1 and duration["lower"] > 1)
            or (duration["upper"] < 1 and cost["lower"] > 1)
        )
    )


def build_comparison(request: dict, reports: list[dict], policy: dict) -> dict:
    """Compare exact selections after reference IDs are authenticated by Experiments.

    Current report IDs may be preliminary; their identity never seeds the conclusion.
    No report selection is inferred from a timestamp, label, or previous conclusion.
    """
    if any(policy.get(key) != value for key, value in _DEFAULTS.items()):
        raise ValueError("development-comparison-v1 policy defaults must remain frozen")
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
    predecessor_ids = request.get("predecessor_result_ids", [])
    if len(set(baseline_ids)) != len(baseline_ids) or len(set(predecessor_ids)) != len(
        predecessor_ids
    ):
        raise ValueError("duplicate selected evidence IDs")
    contender_ids = [c["id"] for c in request["contenders"]]
    if not contender_ids or len(set(contender_ids)) != len(contender_ids):
        raise ValueError("request contenders must be nonempty and unique")
    references = set(baseline_ids + predecessor_ids)
    by_id = {}
    for report in reports:
        identity = report["report_id"]
        if identity in by_id:
            raise ValueError("duplicate report ID")
        by_id[identity] = report
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
        "history": {
            "status": "first_version" if request.get("first_version") else "insufficient_evidence",
            "summary": "No predecessor selected."
            if request.get("first_version")
            else "Selected predecessor evidence is insufficient.",
            "predecessor_ids": list(predecessor_ids),
            "hypothesis": request.get("change", {}).get("hypothesis"),
            "task_changes": [],
            "predecessor_contenders": [],
        },
        "limitations": list(_LIMITS),
        "policy_id": policy["policy_id"],
        "policy_digest": _digest(policy),
        "bootstrap": None,
    }
    reasons = result["reasons"]
    if conditions.get("decision_policy") != policy["policy_id"]:
        result.update(status="incompatible_conditions", summary="Decision policy does not match.")
        reasons.append("decision_policy_mismatch")
        return result
    neutral_tasks = conditions.get("task_variant") == "comparison" and set(tasks) <= set(
        policy["task_ids"]
    )
    if not neutral_tasks and not _is_quill_deepswe_diagnostic(request, conditions):
        result.update(
            status="incompatible_conditions", summary="Neutral comparison tasks are required."
        )
        reasons.append("non_neutral_tasks")
        return result
    if len(current) != 1 or any(i not in by_id for i in baseline_ids):
        reasons.append("missing_or_ambiguous_evidence")
        return result
    current = current[0]
    cohort_reports = [current] + [by_id[i] for i in baseline_ids]
    if any(r.get("experiment", {}).get("conditions") != conditions for r in cohort_reports):
        result.update(status="incompatible_conditions", summary="Selected conditions do not match.")
        reasons.append("incompatible_conditions")
        return result
    if set(c["id"] for c in current["experiment"]["contenders"]) != set(contender_ids):
        reasons.append("contender_identity_mismatch")
        return result
    old_reports = [by_id[i] for i in predecessor_ids if i in by_id]
    old_compatible = (
        len(old_reports) == len(predecessor_ids)
        and bool(old_reports)
        and all(r["experiment"]["conditions"] == conditions for r in old_reports)
    )
    datasets = {}
    cohort = []
    history_old = []
    for report in cohort_reports + (old_reports if old_compatible else []):
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
            if key not in datasets:
                datasets[key] = _dataset(report, contender, conditions, pricing)
            if report in cohort_reports and key not in cohort:
                cohort.append(key)
            if report in old_reports and key not in history_old:
                history_old.append(key)
    if len({key[1] for key in cohort}) != len(cohort):
        reasons.append("ambiguous_contender_evidence")
        return result
    cohort.sort()
    current_keys = [k for k in cohort if k[0] == current["report_id"]]
    history_pairs = []
    for new in current_keys:
        matches = [
            old
            for old in history_old
            if datasets[old]["public"]["family"] == datasets[new]["public"]["family"]
        ]
        if len(matches) == 1:
            history_pairs.append((new, matches[0]))
    pair_keys = {tuple(sorted(pair)) for pair in itertools.combinations(cohort, 2)}
    pair_keys.update(tuple(sorted(pair)) for pair in history_pairs if pair[0] != pair[1])
    # Reuse each immutable evidence dataset once, including a shared selected baseline.
    seed_evidence = []
    for key in sorted(datasets):
        identity = (
            key[0] if key[0] != current["report_id"] else current["experiment"].get("request_id")
        )
        sampling_identity = _digest([identity, key[1], datasets[key]["trials"]])
        datasets[key]["sampling_identity"] = sampling_identity
        seed_evidence.append(sampling_identity)
    seed = _digest({"evidence": sorted(seed_evidence), "policy": result["policy_digest"]})
    if pricing is None:
        for dataset in datasets.values():
            prices = {
                t.get("pricing_digest") for t in dataset["trials"] if t["status"] in _ATTEMPTED
            }
            if len(prices) != 1 or None in prices:
                dataset["groups"][0] = None
                dataset["public"].update(
                    total_cost_usd=None, cost_per_success_usd=None, mean_cost_usd=None
                )
            else:
                dataset["public"]["pricing_digest"] = next(iter(prices))
        if len({datasets[k]["public"]["pricing_digest"] for k in cohort}) != 1:
            reasons.append("pricing_unavailable")
    pairs, tail = _bootstrap(datasets, pair_keys, policy, seed)
    result["bootstrap"] = {
        "seed": seed,
        "draws": policy["bootstrap_draws"],
        "pair_count": len(pair_keys),
        "per_tail_probability": tail,
    }
    result["contenders"] = [datasets[k]["public"] for k in cohort]
    result["pairs"] = [pairs[k] for k in sorted(pairs)]
    result["provisional"] = any(
        r.get("evidence", {}).get("review_state") != "reviewed"
        for r in cohort_reports + old_reports
    )
    enough = (
        len(tasks) == policy["required_task_count"] and attempts >= policy["minimum_repetitions"]
    )
    if len(tasks) != policy["required_task_count"]:
        reasons.append("insufficient_task_coverage")
    if attempts < policy["minimum_repetitions"]:
        reasons.append("insufficient_repetitions")
    if not all(datasets[k]["public"]["coverage_complete"] for k in cohort):
        reasons.append("incomplete_coverage")
    for key in cohort:
        public = datasets[key]["public"]
        if not public["eligible"]:
            reasons.append("quality_ineligible")
        if not public["usage_complete"]:
            reasons.append("usage_incomplete")
        if public["total_cost_usd"] is None:
            reasons.append("pricing_unavailable")
        if public["mean_duration_seconds"] is None:
            reasons.append("duration_unavailable")
    eligible = [k for k in cohort if datasets[k]["public"]["eligible"]]
    for field, leader in [
        ("mean_cost_usd", "observed_cost_ids"),
        ("mean_duration_seconds", "observed_time_ids"),
    ]:
        values = [datasets[k]["public"][field] for k in eligible]
        comparable_prices = len({datasets[k]["public"]["pricing_digest"] for k in eligible}) == 1
        if (
            values
            and all(v is not None for v in values)
            and (field != "mean_cost_usd" or comparable_prices)
        ):
            result["leaders"][leader] = sorted(
                k[1] for k in eligible if datasets[k]["public"][field] == min(values)
            )
    quarantined = any(
        r.get("evidence", {}).get("review_state") == "quarantined" for r in cohort_reports
    )
    diagnostic = (
        request.get("purpose") == "diagnostic"
        or current["experiment"].get("purpose") == "diagnostic"
    )
    diagnostic_baseline = any(
        r["experiment"].get("purpose") == "diagnostic" for r in cohort_reports[1:]
    )
    diagnostic_predecessor = any(
        r["experiment"].get("purpose") == "diagnostic" for r in old_reports
    )
    if diagnostic_baseline or diagnostic_predecessor:
        reasons.append("diagnostic_reference")
    if quarantined:
        reasons.append("quarantined_evidence")
    if diagnostic:
        reasons.append("diagnostic_only")
    if _is_quill_deepswe_diagnostic(request, conditions) and any(
        trial.get("protected_state") is None
        for key in cohort
        for trial in datasets[key]["trials"]
    ):
        reasons.append("protected_state_unknown")
    if (
        enough
        and not quarantined
        and not diagnostic
        and not diagnostic_baseline
        and all(datasets[k]["public"]["coverage_complete"] for k in cohort)
    ):
        result.update(
            status="no_clear_winner", summary="No clear overall winner in the selected evidence."
        )
        if not eligible:
            result.update(
                status="no_quality_qualified_winner",
                summary="No contender passed every scheduled correctness check.",
            )
        elif len(eligible) == 1:
            result.update(
                status="recommended",
                winner_id=eligible[0][1],
                summary="One contender passed every scheduled correctness check.",
            )
            reasons.append("sole_quality_eligible")
        else:
            for key in eligible:
                if all(
                    _dominates(pairs[tuple(sorted((key, other)))], key > other, policy)
                    for other in eligible
                    if other != key
                ):
                    result.update(
                        status="recommended",
                        winner_id=key[1],
                        summary="A practical efficiency advantage with noninferiority is "
                        "supported against every other eligible contender.",
                    )
                    reasons.append("practical_advantage_supported")
            if any(
                _tradeoff(pairs[tuple(sorted(pair))])
                for pair in itertools.combinations(eligible, 2)
            ):
                reasons.append("cost_time_tradeoff")
    history = result["history"]
    if not request.get("first_version"):
        if old_reports and not old_compatible and len(old_reports) == len(predecessor_ids):
            history.update(
                status="incompatible_conditions", summary="Predecessor conditions do not match."
            )
        elif old_compatible and len(history_pairs) == len(current_keys):
            history["predecessor_contenders"] = [datasets[k]["public"] for k in sorted(history_old)]
            history_claims_allowed = (
                enough
                and not quarantined
                and not diagnostic
                and not diagnostic_predecessor
                and not any(
                    r.get("evidence", {}).get("review_state") == "quarantined" for r in old_reports
                )
            )
            statuses = []
            for new, old in history_pairs:
                np, op = datasets[new]["public"], datasets[old]["public"]
                recoveries = [t for t in tasks if np["task_successes"][t] > op["task_successes"][t]]
                regressions = [
                    t for t in tasks if np["task_successes"][t] < op["task_successes"][t]
                ]
                history["task_changes"].append(
                    {
                        "contender_id": new[1],
                        "predecessor_contender_id": old[1],
                        "recoveries": recoveries,
                        "regressions": regressions,
                    }
                )
                if (
                    not history_claims_allowed
                    or not np["coverage_complete"]
                    or not op["coverage_complete"]
                ):
                    status = "insufficient_evidence"
                elif recoveries and regressions:
                    status = "mixed"
                elif np["eligible"] and not op["eligible"] and not regressions:
                    status = "improved"
                elif op["eligible"] and not np["eligible"] and not recoveries:
                    status = "regressed"
                elif np["eligible"] and op["eligible"]:
                    pair = pairs[tuple(sorted((new, old)))]
                    if _dominates(pair, new > old, policy):
                        status = "improved"
                    elif _dominates(pair, old > new, policy):
                        status = "regressed"
                    elif _tradeoff(pair):
                        status = "mixed"
                    elif pair["cost_ratio"] is None or pair["time_ratio"] is None:
                        status = "insufficient_evidence"
                    else:
                        status = "no_clear_change"
                else:
                    status = "insufficient_evidence"
                statuses.append(status)
            status_set = set(statuses)
            status = (
                "insufficient_evidence"
                if "insufficient_evidence" in status_set
                else "mixed"
                if "mixed" in status_set or {"improved", "regressed"} <= status_set
                else "improved"
                if "improved" in status_set
                else "regressed"
                if "regressed" in status_set
                else "no_clear_change"
            )
            history.update(
                status=status,
                summary={
                    "improved": "Improvement is supported against the selected predecessor.",
                    "regressed": "Regression is supported against the selected predecessor.",
                    "mixed": "Selected predecessor comparisons show opposing changes.",
                    "no_clear_change": "No clear change; this is not equivalence.",
                    "insufficient_evidence": "Task changes do not support an improvement claim.",
                }[status],
            )
    result["reasons"] = list(dict.fromkeys(reasons))
    return result
