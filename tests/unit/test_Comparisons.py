import copy
import json
from pathlib import Path

import pytest

from harness_testing.Comparisons import build_comparison, load_comparison_policy

ROOT = Path(__file__).parents[2]


def run(request, reports, policy=None):
    if policy is None:
        policy = json.loads((ROOT / "policy/Comparison Policy.json").read_text())
    return build_comparison(request, reports, policy)


def fixture(ids=("a", "b"), attempts=3):
    contenders = [{"id": i, "family": i, "label": i} for i in ids]
    conditions = {
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
        "decision_policy": "development-comparison-v1",
        "attempts": attempts,
        "task_variant": "comparison",
        "evaluator_digest": "grade-1",
    }
    request = {
        "request_id": "current",
        "purpose": "candidate",
        "conditions": conditions,
        "contenders": contenders,
        "baseline_result_ids": [],
        "predecessor_result_ids": [],
        "first_version": True,
        "change": {"hypothesis": "Preserve this exactly.\nSecond line."},
    }
    trials = [
        {
            "trial_id": f"{c}-{t}-{a}",
            "contender_id": c,
            "task_id": t,
            "attempt": a,
            "status": "completed",
            "correctness": True,
            "protected_state": True,
            "duration_seconds": 10.0,
            "usage_complete": True,
            "cost_usd": 1.0,
            "pricing_digest": "price-1",
            "model_usage": [],
            "code_review": {
                "protocol_id": "review-1",
                "status": "completed",
                "findings": [],
                "cost_usd": 0.5,
            },
        }
        for c in ids
        for t in conditions["task_ids"]
        for a in range(1, attempts + 1)
    ]
    report = {
        "report_id": "current-report",
        "evidence": {"review_state": "unreviewed"},
        "experiment": {**copy.deepcopy(request), "trials": trials},
    }
    return request, [report]


def trials(reports, contender):
    return [t for t in reports[0]["experiment"]["trials"] if t["contender_id"] == contender]


def test_equal_contenders_have_no_clear_winner_and_full_tables():
    request, reports = fixture()
    result = run(request, reports)
    assert result["status"] == "no_clear_winner" and result["winner_id"] is None
    assert [row["successes"] for row in result["contenders"]] == [27, 27]
    assert all(row["eligible"] and row["passed_all"] for row in result["contenders"])
    assert result["pairs"][0]["cost_ratio"] == 1.0 and result["pairs"][0]["time_ratio"] == 1.0
    assert result["leaders"] == {"observed_cost_ids": ["a", "b"], "observed_time_ids": ["a", "b"]}
    assert result["unsolved_tasks"] == []
    assert result["provisional"] is True
    assert result["history"]["status"] == "first_version"
    assert result["history"]["hypothesis"] == request["change"]["hypothesis"]


@pytest.mark.parametrize("attempts", [1, 2])
def test_single_and_double_attempts_are_decision_grade(attempts):
    request, reports = fixture(attempts=attempts)
    result = run(request, reports)
    assert "insufficient_repetitions" not in result["reasons"]
    assert result["status"] == "no_clear_winner"


def test_cheaper_contender_with_noninferior_time_is_recommended():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 0.5
    result = run(request, reports)
    assert result["status"] == "recommended" and result["winner_id"] == "a"
    assert "practical_advantage_supported" in result["reasons"]
    assert result["pairs"][0]["cost_ratio"] == 0.5


@pytest.mark.parametrize(
    "cost,time,winner",
    [(0.9, 1.1, "a"), (0.9001, 1.1, None), (0.9, 1.1001, None), (1.1, 0.9, "a")],
)
def test_advantage_and_noninferiority_thresholds_are_exact(cost, time, winner):
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial.update(cost_usd=cost, duration_seconds=10 * time)
    assert run(request, reports)["winner_id"] == winner


def test_cost_and_time_leaders_that_differ_are_a_tradeoff():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial.update(cost_usd=0.5, duration_seconds=20.0)
    result = run(request, reports)
    assert result["winner_id"] is None
    assert "cost_time_tradeoff" in result["reasons"]
    assert result["leaders"] == {"observed_cost_ids": ["a"], "observed_time_ids": ["b"]}


def test_cheap_failure_cannot_beat_correctness():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 0.001
    trials(reports, "a")[0].update(status="agent_failed", correctness=False)
    result = run(request, reports)
    assert result["winner_id"] == "b"
    assert result["contenders"][0]["successes"] == 26
    assert result["contenders"][0]["eligible"] is False
    assert "quality_ineligible" in result["reasons"]


def test_shared_unsolved_task_keeps_equally_correct_contenders_eligible():
    request, reports = fixture()
    for contender in ("a", "b"):
        for trial in trials(reports, contender):
            if trial["task_id"] == "react-accent-polish":
                trial["correctness"] = False
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 0.5
    result = run(request, reports)
    assert result["unsolved_tasks"] == ["react-accent-polish"]
    assert [row["eligible"] for row in result["contenders"]] == [True, True]
    assert [row["passed_all"] for row in result["contenders"]] == [False, False]
    assert result["status"] == "recommended" and result["winner_id"] == "a"


def test_confirmed_defects_disqualify_while_unconfirmed_claims_only_warn():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 0.5
    trials(reports, "a")[0]["code_review"]["findings"].append(
        {"status": "unconfirmed", "severity": "P2"}
    )
    result = run(request, reports)
    assert result["winner_id"] == "a"
    assert "code_review_unconfirmed" in result["reasons"]
    trials(reports, "a")[0]["code_review"]["findings"].append(
        {"status": "confirmed", "severity": "P1"}
    )
    result = run(request, reports)
    assert result["winner_id"] == "b"
    assert result["contenders"][0]["review_clean"] is False
    assert "code_review_defects" in result["reasons"]


def test_missing_review_keeps_the_verdict_but_flags_it():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 0.5
        trial["code_review"] = None
    result = run(request, reports)
    assert result["status"] == "recommended" and result["winner_id"] == "a"
    assert "code_review_incomplete" in result["reasons"]
    assert result["contenders"][0]["reviewed"] is False
    assert result["provisional"] is True


@pytest.mark.parametrize("status", ["pending", "infrastructure_failure", "task_definition_gap"])
def test_incomplete_coverage_keeps_rows_without_a_verdict(status):
    request, reports = fixture()
    trials(reports, "a")[0].update(status=status, correctness=None, protected_state=None)
    result = run(request, reports)
    assert result["status"] == "insufficient_evidence"
    assert "incomplete_coverage" in result["reasons"]
    assert result["contenders"][0]["counts"][status] == 1
    assert result["contenders"][0]["mean_cost_usd"] is None


def test_missing_usage_or_duration_keeps_cost_and_time_unknown():
    request, reports = fixture()
    trials(reports, "a")[0].update(usage_complete=False, cost_usd=None)
    result = run(request, reports)
    assert result["contenders"][0]["total_cost_usd"] is None
    assert "usage_incomplete" in result["reasons"] and "pricing_unavailable" in result["reasons"]
    trials(reports, "b")[0]["duration_seconds"] = None
    result = run(request, reports)
    assert result["contenders"][1]["mean_duration_seconds"] is None
    assert "duration_unavailable" in result["reasons"]


def test_repricing_uses_the_frozen_pricing_table():
    request, reports = fixture(ids=("a",), attempts=1)
    for trial in trials(reports, "a"):
        trial["model_usage"] = [
            {
                "provider": "openai",
                "model": "fixture",
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            }
        ]
    policy = json.loads((ROOT / "policy/Comparison Policy.json").read_text())
    policy["pricing"] = {
        "digest": "sha256:" + "0" * 64,
        "models": {
            "openai/fixture": {
                "input_per_million": 3.0,
                "output_per_million": 0.0,
                "cache_read_per_million": 0.0,
                "cache_write_per_million": 0.0,
            }
        },
    }
    result = run(request, reports, policy)
    assert result["contenders"][0]["total_cost_usd"] == pytest.approx(27.0)
    assert result["contenders"][0]["total_tokens"] == 9_000_000


def test_partial_scope_and_policy_mismatch_are_reported_not_ranked():
    request, reports = fixture()
    request["conditions"]["task_ids"] = request["conditions"]["task_ids"][:3]
    reports[0]["experiment"]["conditions"]["task_ids"] = request["conditions"]["task_ids"]
    reports[0]["experiment"]["trials"] = [
        t for t in reports[0]["experiment"]["trials"]
        if t["task_id"] in request["conditions"]["task_ids"]
    ]
    result = run(request, reports)
    assert result["status"] == "insufficient_evidence"
    assert "insufficient_task_coverage" in result["reasons"]
    assert len(result["contenders"]) == 2
    request, reports = fixture()
    request["conditions"]["decision_policy"] = "other"
    reports[0]["experiment"]["conditions"]["decision_policy"] = "other"
    assert run(request, reports)["status"] == "incompatible_conditions"


def test_quarantined_or_ambiguous_evidence_cannot_produce_a_winner():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 0.5
    reports[0]["evidence"]["review_state"] = "quarantined"
    result = run(request, reports)
    assert result["winner_id"] is None and "quarantined_evidence" in result["reasons"]
    request, reports = fixture()
    duplicate = copy.deepcopy(reports[0])
    duplicate["report_id"] = "another"
    assert "missing_or_ambiguous_evidence" in run(request, reports + [duplicate])["reasons"]


def test_explicit_baseline_is_compared_and_unselected_reports_are_ignored():
    request, reports = fixture(ids=("candidate",))
    _, baseline = fixture(ids=("baseline",))
    baseline[0]["report_id"] = "selected-baseline"
    baseline[0]["experiment"]["request_id"] = "baseline-request"
    request["baseline_result_ids"] = ["selected-baseline"]
    for trial in trials(reports, "candidate"):
        trial["cost_usd"] = 0.5
    result = run(request, reports + baseline)
    assert result["winner_id"] == "candidate"
    assert result["pairs"][0]["left_report_id"] is None
    assert result["pairs"][0]["right_report_id"] == "selected-baseline"
    assert "missing_or_ambiguous_evidence" in run(request, reports)["reasons"]


def history_fixture():
    request, reports = fixture(ids=("new",))
    _, old_reports = fixture(ids=("old",))
    old_reports[0]["report_id"] = "selected-predecessor"
    old_reports[0]["experiment"]["request_id"] = "old-request"
    old_reports[0]["experiment"]["contenders"][0]["family"] = "new"
    request.update(first_version=False, predecessor_result_ids=["selected-predecessor"])
    return request, reports + old_reports


def test_history_judges_correctness_then_efficiency_against_the_exact_predecessor():
    request, reports = history_fixture()
    assert run(request, reports)["history"]["status"] == "no_clear_change"
    for trial in reports[1]["experiment"]["trials"]:
        trial["cost_usd"] = 2.0
    result = run(request, reports)
    assert result["history"]["status"] == "improved"
    assert result["history"]["predecessor_ids"] == ["selected-predecessor"]
    reports[1]["experiment"]["trials"][0]["correctness"] = False
    result = run(request, reports)
    assert result["history"]["status"] == "improved"
    assert result["history"]["task_changes"][0]["recoveries"] == ["react-accent-polish"]
    reports[0]["experiment"]["trials"][3]["correctness"] = False
    assert run(request, reports)["history"]["status"] == "mixed"
    for trial in reports[1]["experiment"]["trials"]:
        trial.update(correctness=True, cost_usd=0.1)
    reports[0]["experiment"]["trials"][3]["correctness"] = True
    assert run(request, reports)["history"]["status"] == "regressed"


def test_history_needs_a_compatible_complete_predecessor():
    request, reports = history_fixture()
    reports[1]["experiment"]["conditions"]["attempts"] = 2
    assert run(request, reports)["history"]["status"] == "incompatible_conditions"
    request, reports = history_fixture()
    reports[1]["experiment"]["trials"][0].update(status="pending", correctness=None)
    assert run(request, reports)["history"]["status"] == "insufficient_evidence"
    request, reports = history_fixture()
    assert run(request, reports[:1])["history"]["status"] == "insufficient_evidence"


def test_readiness_policy_scopes_and_research_tasks_are_accepted():
    request, reports = fixture()
    policy = load_comparison_policy(ROOT, {"decision_policy": "development-comparison-v1"})
    assert policy["policy_id"] == "development-comparison-v1"
    readiness = load_comparison_policy(
        ROOT,
        {
            "decision_policy": "benchmark-readiness-v2",
            "task_ids": request["conditions"]["task_ids"],
        },
    )
    assert readiness["declared_scope"] is True
    for report in reports:
        report["experiment"]["conditions"]["decision_policy"] = "benchmark-readiness-v2"
    request["conditions"]["decision_policy"] = "benchmark-readiness-v2"
    assert run(request, reports, readiness)["status"] == "no_clear_winner"


def test_invalid_trials_are_rejected_loudly():
    request, reports = fixture()
    trials(reports, "a")[0]["attempt"] = 9
    with pytest.raises(ValueError, match="outside the schedule"):
        run(request, reports)
    request, reports = fixture()
    trials(reports, "a")[0]["cost_usd"] = -1
    with pytest.raises(ValueError, match="cost_usd"):
        run(request, reports)
    request, reports = fixture()
    reports[0]["experiment"]["trials"].append(copy.deepcopy(trials(reports, "a")[0]))
    with pytest.raises(ValueError, match="duplicate"):
        run(request, reports)
