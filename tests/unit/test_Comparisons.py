import copy
import importlib
import json
from pathlib import Path

import pytest


def run(request, reports, policy=None):
    module = importlib.import_module("harness_testing.Comparisons")
    if policy is None:
        policy = json.loads(
            (Path(__file__).parents[2] / "policy/Comparison Policy.json").read_text()
        )
    return module.build_comparison(request, reports, policy)


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


def quill_diagnostic_fixture(status="completed"):
    request, reports = fixture(ids=("nothing", "superpowers", "studio-moser"), attempts=1)
    conditions = request["conditions"]
    conditions.update(
        task_ids=["quill-shared-toolbar-focus"],
        task_variant="deepswe",
    )
    request["purpose"] = "diagnostic"
    report = reports[0]
    report["experiment"].update(copy.deepcopy(request))
    selected = []
    for contender in request["contenders"]:
        trial = next(
            trial for trial in trials(reports, contender["id"]) if trial["attempt"] == 1
        )
        trial.update(
            task_id="quill-shared-toolbar-focus",
            status=status,
            correctness=True if status == "completed" else None,
            protected_state=None,
            model_usage=[
                {
                    "provider": "openai",
                    "model": "fixture",
                    "input_tokens": 10,
                    "cache_read_tokens": 2,
                    "cache_write_tokens": 1,
                    "output_tokens": 5,
                }
            ]
            if status == "completed"
            else [],
        )
        selected.append(trial)
    report["experiment"]["trials"] = selected
    return request, reports


@pytest.mark.parametrize("status", ["pending", "completed"])
def test_quill_diagnostic_deepswe_retains_rows_without_a_recommendation(status):
    request, reports = quill_diagnostic_fixture(status)

    result = run(request, reports)

    assert result["status"] == "insufficient_evidence"
    assert result["winner_id"] is None
    assert "diagnostic_only" in result["reasons"]
    assert "insufficient_repetitions" in result["reasons"]
    assert "protected_state_unknown" in result["reasons"]
    assert len(result["contenders"]) == 3
    if status == "completed":
        assert [row["total_cost_usd"] for row in result["contenders"]] == [1.0, 1.0, 1.0]
        assert [row["total_tokens"] for row in result["contenders"]] == [18, 18, 18]
        assert all(row["eligible"] is False for row in result["contenders"])
        assert all(row["counts"]["missing_grading"] == 1 for row in result["contenders"])
    else:
        assert all(row["counts"]["pending"] == 1 for row in result["contenders"])


def test_cheap_failure_and_contract_scores_cannot_beat_correctness():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial.update(cost_usd=0.001, contract_score=1_000_000)
    trials(reports, "a")[0].update(status="agent_failed", correctness=False)
    result = run(request, reports)
    assert result["winner_id"] == "b"
    assert result["contenders"][0]["successes"] == 26
    assert result["contenders"][0]["eligible"] is False
    assert "quality_ineligible" in result["reasons"]
    assert result["provisional"] is True


def test_failed_attempt_cost_and_zero_success_accounting():
    request, reports = fixture(ids=("a",), attempts=2)
    for trial in trials(reports, "a"):
        trial.update(status="agent_failed", correctness=False, cost_usd=0.0)
    trials(reports, "a")[0]["cost_usd"] = 2.0
    trials(reports, "a")[1].update(status="completed", correctness=True, cost_usd=3.0)
    result = run(request, reports)
    assert result["contenders"][0]["cost_per_success_usd"] == 5.0
    trials(reports, "a")[1]["correctness"] = False
    assert run(request, reports)["contenders"][0]["cost_per_success_usd"] is None


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("usage_complete", False, "usage_incomplete"),
        ("pricing_digest", None, "pricing_unavailable"),
        ("cost_usd", None, "pricing_unavailable"),
    ],
)
def test_unknown_accounting_never_becomes_zero(field, value, reason):
    request, reports = fixture()
    trials(reports, "a")[0][field] = value
    result = run(request, reports)
    assert result["winner_id"] is None
    assert result["contenders"][0]["total_cost_usd"] is None
    assert reason in result["reasons"]


@pytest.mark.parametrize(
    "status", ["infrastructure_failure", "task_definition_gap", "pending", "cancelled"]
)
def test_unfinished_or_unusable_scheduled_slot_blocks_overall_winner(status):
    request, reports = fixture()
    trials(reports, "a")[0].update(status=status, correctness=None)
    result = run(request, reports)
    assert result["winner_id"] is None
    assert result["status"] == "insufficient_evidence"
    assert result["contenders"][0]["counts"][status] == 1


def test_missing_grading_and_missing_scheduling_block_recommendation():
    request, reports = fixture()
    trials(reports, "a")[0]["correctness"] = None
    assert run(request, reports)["status"] == "insufficient_evidence"
    reports[0]["experiment"]["trials"].pop(0)
    result = run(request, reports)
    assert result["status"] == "insufficient_evidence"
    assert result["contenders"][0]["counts"]["missing"] == 1


@pytest.mark.parametrize("attempts", [1, 2])
def test_smoke_and_two_repetitions_are_diagnostic(attempts):
    request, reports = fixture(attempts=attempts)
    assert run(request, reports)["winner_id"] is None
    assert "insufficient_repetitions" in run(request, reports)["reasons"]


@pytest.mark.parametrize(
    "cost,time,winner",
    [
        (0.9, 1.1, "a"),
        (0.90001, 1.1, None),
        (0.9, 1.10001, None),
        (1.0, 1.0, None),
        (2.0, 1.0, "b"),
    ],
)
def test_practical_boundaries(cost, time, winner):
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial.update(cost_usd=cost, duration_seconds=10 * time)
    result = run(request, reports)
    assert result["winner_id"] == winner
    assert result["pairs"][0]["cost_ratio"]["estimate"] == pytest.approx(cost)


def test_tradeoff_has_no_overall_winner():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial.update(cost_usd=0.5, duration_seconds=20.0)
    result = run(request, reports)
    assert result["winner_id"] is None
    assert "cost_time_tradeoff" in result["reasons"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True])
def test_invalid_numbers_are_rejected(value):
    request, reports = fixture()
    trials(reports, "a")[0]["cost_usd"] = value
    with pytest.raises(ValueError):
        run(request, reports)


def test_duplicate_slots_and_contract_variants_are_rejected():
    request, reports = fixture()
    reports[0]["experiment"]["trials"].append(copy.deepcopy(trials(reports, "a")[0]))
    with pytest.raises(ValueError):
        run(request, reports)
    request, reports = fixture()
    request["conditions"]["task_variant"] = "contract"
    assert run(request, reports)["status"] == "incompatible_conditions"


def test_zero_comparator_withholds_ratio_without_nonfinite_json():
    request, reports = fixture()
    for trial in trials(reports, "b"):
        trial["cost_usd"] = 0.0
    result = run(request, reports)
    assert result["winner_id"] is None
    assert result["pairs"][0]["cost_ratio"] is None
    assert result["pairs"][0]["cost_difference_usd"] == 1.0
    json.dumps(result, allow_nan=False)
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 0.0
    assert run(request, reports)["pairs"][0]["cost_ratio"]["upper"] == 1.0


def test_bootstrap_is_independent_reproducible_and_uses_selected_pairs():
    request, reports = fixture(ids=("a", "b", "c"))
    for trial in reports[0]["experiment"]["trials"]:
        trial["cost_usd"] = float(trial["attempt"])
    first = run(request, reports)
    second = run(request, list(reversed(reports)))
    assert first == second
    assert first["bootstrap"]["pair_count"] == 3
    assert first["bootstrap"]["per_tail_probability"] == pytest.approx(0.05 / 12)
    assert first["bootstrap"]["draws"] == 20000
    ratio = first["pairs"][0]["cost_ratio"]
    assert ratio["lower"] < 1 < ratio["upper"]  # paired repetition resampling would give [1,1]
    reports[0]["experiment"]["comparison"] = {"status": "untrusted-old-conclusion"}
    assert run(request, reports)["bootstrap"]["seed"] == first["bootstrap"]["seed"]


def history_fixture():
    request, reports = fixture(ids=("new",))
    old_request, old_reports = fixture(ids=("old",))
    old_reports[0]["report_id"] = "selected-predecessor"
    old_reports[0]["experiment"]["request_id"] = "old-request"
    old_reports[0]["experiment"]["contenders"][0]["family"] = "new"
    request.update(first_version=False, predecessor_result_ids=["selected-predecessor"])
    return request, reports + old_reports


def test_first_version_and_verbatim_hypothesis():
    request, reports = fixture(ids=("new",))
    result = run(request, reports)
    assert result["history"]["status"] == "first_version"
    assert result["history"]["hypothesis"] == request["change"]["hypothesis"]


def test_history_uses_exact_predecessor_not_latest_or_baseline():
    request, reports = history_fixture()
    for trial in reports[1]["experiment"]["trials"]:
        trial["cost_usd"] = 2.0
    unselected = copy.deepcopy(reports[1])
    unselected["report_id"] = "newer-but-unselected"
    for trial in unselected["experiment"]["trials"]:
        trial["cost_usd"] = 0.01
    result = run(request, reports + [unselected])
    assert result["history"]["status"] == "improved"
    assert result["history"]["predecessor_ids"] == ["selected-predecessor"]


def test_history_recoveries_regressions_and_mixed():
    request, reports = history_fixture()
    reports[1]["experiment"]["trials"][0]["correctness"] = False
    assert run(request, reports)["history"]["status"] == "improved"
    reports[0]["experiment"]["trials"][3]["correctness"] = False
    assert run(request, reports)["history"]["status"] == "mixed"
    reports[1]["experiment"]["trials"][0]["correctness"] = True
    assert run(request, reports)["history"]["status"] == "regressed"


def test_history_rerun_no_clear_change_and_regraded_incompatibility():
    request, reports = history_fixture()
    request["change"]["rerun_reason"] = "Repeat measurement"
    assert run(request, reports)["history"]["status"] == "no_clear_change"
    reports[1]["experiment"]["conditions"]["evaluator_digest"] = "grade-2"
    assert run(request, reports)["history"]["status"] == "incompatible_conditions"
    reports.pop()
    assert run(request, reports)["history"]["status"] == "insufficient_evidence"


def test_repricing_uses_all_token_categories_and_preserves_original_estimates():
    request, reports = fixture()
    policy = json.loads((Path(__file__).parents[2] / "policy/Comparison Policy.json").read_text())
    policy["pricing"] = {
        "digest": "frozen-price",
        "models": {
            "provider/model": {
                "input_per_million": 1,
                "output_per_million": 2,
                "cache_read_per_million": 0.5,
                "cache_write_per_million": 3,
            }
        },
    }
    for trial in reports[0]["experiment"]["trials"]:
        trial["model_usage"] = [
            {
                "provider": "provider",
                "model": "model",
                "input_tokens": 1_000_000,
                "output_tokens": 1_000_000,
                "cache_read_tokens": 1_000_000,
                "cache_write_tokens": 1_000_000,
            }
        ]
    result = run(request, reports, policy)
    assert result["contenders"][0]["total_cost_usd"] == 175.5
    assert result["contenders"][0]["original_estimates"][0]["cost_usd"] == 1.0
    assert result["contenders"][0]["original_estimates"][0]["pricing_digest"] == "price-1"
    trials(reports, "a")[0]["model_usage"][0].pop("cache_write_tokens")
    assert run(request, reports, policy)["contenders"][0]["total_cost_usd"] is None


def test_quarantined_evidence_never_supports_a_recommendation():
    request, reports = fixture(ids=("a",))
    reports[0]["evidence"]["review_state"] = "quarantined"
    result = run(request, reports)
    assert result["winner_id"] is None
    assert "quarantined_evidence" in result["reasons"]


def test_seed_excludes_preliminary_report_identity_even_with_references():
    request, reports = history_fixture()
    for trial in reports[0]["experiment"]["trials"]:
        trial["cost_usd"] = float(trial["attempt"])
    original = run(request, reports)
    reports[0]["report_id"] = "zz-final-report"
    revised = run(request, reports)
    assert revised["bootstrap"]["seed"] == original["bootstrap"]["seed"]
    assert revised["history"]["status"] == original["history"]["status"]


def test_predecessor_pricing_does_not_erase_valid_current_cohort_comparison():
    request, reports = fixture()
    old_request, old_reports = fixture(ids=("old",))
    old_reports[0]["report_id"] = "old-report"
    old_reports[0]["experiment"]["request_id"] = "old"
    old_reports[0]["experiment"]["contenders"][0]["family"] = "a"
    for trial in old_reports[0]["experiment"]["trials"]:
        trial["pricing_digest"] = "old-price"
    request.update(first_version=False, predecessor_result_ids=["old-report"])
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 0.5
    result = run(request, reports + old_reports)
    assert result["winner_id"] == "a"
    assert result["contenders"][0]["total_cost_usd"] == 13.5


def test_different_estimate_prices_disable_only_pair_cost_comparison():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial.update(pricing_digest="different-price", cost_usd=0.1)
    result = run(request, reports)
    assert result["winner_id"] is None
    assert result["pairs"][0]["cost_ratio"] is None
    assert result["contenders"][0]["total_cost_usd"] == pytest.approx(2.7)


def test_diagnostic_purpose_cannot_issue_recommendation():
    request, reports = fixture(ids=("a",))
    request["purpose"] = "diagnostic"
    assert run(request, reports)["winner_id"] is None


def test_history_incomplete_evidence_still_shows_observed_task_changes():
    request, reports = history_fixture()
    reports[0]["experiment"]["trials"][0].update(status="pending", correctness=None)
    result = run(request, reports)
    assert result["history"]["status"] == "insufficient_evidence"
    assert result["history"]["task_changes"][0]["regressions"] == ["react-accent-polish"]


def test_explicit_baseline_and_missing_reference_are_respected():
    request, reports = fixture(ids=("candidate",))
    _, baseline = fixture(ids=("baseline",))
    baseline[0]["report_id"] = "selected-baseline"
    baseline[0]["experiment"]["request_id"] = "baseline-request"
    for trial in trials(reports, "candidate"):
        trial["cost_usd"] = 0.5
    request["baseline_result_ids"] = ["selected-baseline"]
    assert run(request, reports + baseline)["winner_id"] == "candidate"
    assert run(request, reports)["winner_id"] is None
    baseline[0]["experiment"]["conditions"]["attempts"] = 4
    assert run(request, reports + baseline)["status"] == "incompatible_conditions"


def test_contract_task_ids_cannot_masquerade_as_neutral_coverage():
    request, reports = fixture()
    request["conditions"]["task_ids"][0] = "contract-test-enforcement"
    reports[0]["experiment"]["conditions"] = copy.deepcopy(request["conditions"])
    for trial in reports[0]["experiment"]["trials"]:
        if trial["task_id"] == "react-accent-polish":
            trial["task_id"] = "contract-test-enforcement"
    result = run(request, reports)
    assert result["winner_id"] is None
    assert "non_neutral_tasks" in result["reasons"]


def test_decision_policy_mismatch_is_incompatible():
    request, reports = fixture()
    request["conditions"]["decision_policy"] = "different-policy"
    reports[0]["experiment"]["conditions"]["decision_policy"] = "different-policy"
    assert run(request, reports)["status"] == "incompatible_conditions"


def test_contract_scores_do_not_change_uncertainty_seed_or_conclusions():
    request, reports = fixture()
    for trial in reports[0]["experiment"]["trials"]:
        trial["cost_usd"] = float(trial["attempt"])
    original = run(request, reports)
    for trial in reports[0]["experiment"]["trials"]:
        trial["contract_score"] = 9_999
    assert run(request, reports) == original


def test_selected_family_size_does_not_shrink_after_correctness_failure():
    request, reports = fixture(ids=("a", "b", "c"))
    trials(reports, "c")[0]["correctness"] = False
    result = run(request, reports)
    assert result["bootstrap"]["pair_count"] == 3
    assert result["bootstrap"]["per_tail_probability"] == pytest.approx(0.05 / 12)


def test_reused_candidate_is_resampled_once_across_comparisons():
    request, reports = fixture(ids=("a", "b", "c"))
    for trial in trials(reports, "a"):
        trial["cost_usd"] = float(trial["attempt"])
    result = run(request, reports)
    assert result["pairs"][0]["cost_ratio"] == result["pairs"][1]["cost_ratio"]


def test_missing_root_duration_prevents_efficiency_recommendation():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 0.1
    trials(reports, "b")[0]["duration_seconds"] = None
    result = run(request, reports)
    assert result["winner_id"] is None
    assert "duration_unavailable" in result["reasons"]


def test_history_smoke_shows_observed_changes_without_improvement_claim():
    request, reports = history_fixture()
    request["conditions"]["attempts"] = 1
    for report in reports:
        report["experiment"]["conditions"]["attempts"] = 1
        report["experiment"]["trials"] = [
            t for t in report["experiment"]["trials"] if t["attempt"] == 1
        ]
    reports[1]["experiment"]["trials"][0]["correctness"] = False
    result = run(request, reports)
    assert result["history"]["status"] == "insufficient_evidence"
    assert len(result["history"]["task_changes"]) == 1
    assert result["history"]["predecessor_contenders"][0]["successes"] == 8


def test_observed_leaders_keep_ties_and_do_not_override_uncertainty():
    request, reports = fixture()
    result = run(request, reports)
    assert result["leaders"] == {"observed_cost_ids": ["a", "b"], "observed_time_ids": ["a", "b"]}
    assert result["winner_id"] is None
    trials(reports, "a")[0]["usage_complete"] = False
    assert run(request, reports)["leaders"]["observed_cost_ids"] == []


@pytest.mark.parametrize("usage", [None, {}, [None]])
def test_malformed_usage_is_rejected_at_the_boundary(usage):
    request, reports = fixture()
    trials(reports, "a")[0]["model_usage"] = usage
    with pytest.raises(ValueError):
        run(request, reports)


def test_unrepresentable_aggregates_are_rejected_without_infinite_json():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 1e308
    with pytest.raises(ValueError, match="representable"):
        run(request, reports)


def test_ratio_underflow_withholds_recommendation():
    request, reports = fixture()
    for trial in trials(reports, "a"):
        trial["cost_usd"] = 1e-300
    for trial in trials(reports, "b"):
        trial["cost_usd"] = 1e100
    result = run(request, reports)
    assert result["winner_id"] is None
    assert result["pairs"][0]["cost_ratio"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("status", ["completed", "agent_failed", "timeout"])
@pytest.mark.parametrize("grade", ["correctness", "protected_state"])
def test_every_attempt_requires_both_grades_before_overall_recommendation(status, grade):
    request, reports = fixture()
    trials(reports, "a")[0].update(status=status, cost_usd=2.0)
    trials(reports, "a")[0][grade] = None
    result = run(request, reports)
    contender = result["contenders"][0]
    assert contender["counts"]["missing_grading"] == 1
    assert contender["coverage_complete"] is False
    assert contender["attempted"] == 27
    assert contender["total_cost_usd"] == 28.0
    assert contender["cost_per_success_usd"] == pytest.approx(28 / 26)
    assert result["status"] == "insufficient_evidence"
    assert result["winner_id"] is None


def test_diagnostic_baseline_retains_observations_without_overall_recommendation():
    request, reports = fixture(ids=("candidate",))
    _, baseline = fixture(ids=("baseline",))
    baseline[0]["report_id"] = "selected-baseline"
    baseline[0]["experiment"].update(request_id="baseline-request", purpose="diagnostic")
    request["baseline_result_ids"] = ["selected-baseline"]
    for trial in trials(reports, "candidate"):
        trial["cost_usd"] = 0.5
    result = run(request, reports + baseline)
    assert result["status"] == "insufficient_evidence"
    assert result["winner_id"] is None
    assert "diagnostic_reference" in result["reasons"]
    assert len(result["contenders"]) == 2
    assert result["pairs"][0]["cost_ratio"] is not None


def test_diagnostic_predecessor_blocks_history_claim_only():
    request, reports = history_fixture()
    for trial in reports[1]["experiment"]["trials"]:
        trial["cost_usd"] = 2.0
    assert run(request, reports)["history"]["status"] == "improved"
    reports[1]["experiment"]["purpose"] = "diagnostic"
    result = run(request, reports)
    assert result["winner_id"] == "new"
    assert result["history"]["status"] == "insufficient_evidence"
    assert "diagnostic_reference" in result["reasons"]
    assert result["history"]["predecessor_contenders"][0]["total_cost_usd"] == 54.0
    assert len(result["history"]["task_changes"]) == 1


def test_diagnostic_current_report_cannot_bypass_gate_with_changed_request_purpose():
    request, reports = fixture(ids=("a",))
    reports[0]["experiment"]["purpose"] = "diagnostic"
    result = run(request, reports)
    assert result["winner_id"] is None
    assert "diagnostic_only" in result["reasons"]


def test_recorded_infrastructure_work_is_not_free_and_tokens_include_cache():
    request, reports = fixture(ids=("a",), attempts=1)
    rows = trials(reports, "a")
    for trial in rows:
        trial["model_usage"] = [
            {
                "provider": "openai",
                "model": "fixture",
                "input_tokens": 10,
                "cache_read_tokens": 2,
                "cache_write_tokens": 3,
                "output_tokens": 5,
            }
        ]
    rows[0]["status"] = "infrastructure_failure"
    result = run(request, reports)["contenders"][0]
    assert result["coverage_complete"] is False
    assert result["total_cost_usd"] == 9
    assert result["total_tokens"] == 180
    rows[0]["usage_complete"] = False
    result = run(request, reports)["contenders"][0]
    assert result["total_cost_usd"] is None
    assert result["total_tokens"] is None
