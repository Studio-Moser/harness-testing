import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_Experiments import request_document

from harness_testing.Campaigns import assemble_lane, build_campaign, summarize_campaign
from harness_testing.Comparisons import load_comparison_policy
from harness_testing.Experiments import contender_identity, validate_experiment_request
from harness_testing.Quality import DIMENSIONS, RUBRIC_VERSION

ROOT = Path(__file__).parents[2]


def digest(name):
    return "sha256:" + hashlib.sha256(name.encode()).hexdigest()


def policy_for_lane(conditions):
    return load_comparison_policy(ROOT, conditions)


def summarize(plan, reports):
    return summarize_campaign(plan, reports, policy_for_lane=policy_for_lane)


@pytest.mark.parametrize("field", [
    "contenders", "request_id", "purpose", "baseline_result_ids", "predecessor_result_ids",
    "first_version", "change", "label",
])
def test_campaign_rejects_report_identity_drift(field):
    _, _, plan, reports = fixture()
    report = reports[0]["experiment"]
    if field == "contenders":
        report[field] = copy.deepcopy(report[field])
        report[field][0]["family"] = "studio-moser"
    else:
        report[field] = "changed"
    with pytest.raises(ValueError, match="frozen campaign"):
        summarize(plan, reports)


def _trial(contender, task, attempt):
    return {
        "trial_id": f"{contender}-{task}-{attempt}",
        "contender_id": contender,
        "task_id": task,
        "attempt": attempt,
        "correctness": True,
        "status": "completed",
        "usage_complete": True,
        "duration_seconds": 10,
        "cost_usd": 0.5 if contender == "a" else 1,
        "pricing_digest": "price-1",
        "model_usage": [],
        "protected_state": True,
        "code_review": {
            "protocol_id": "review-1",
            "status": "completed",
            "findings": [],
            "cost_usd": 0.5,
        },
        "collaboration": {
            "contract": {"scenario": "scenario-0"},
            "grade": {
                "status": "completed",
                "rubric_version": RUBRIC_VERSION,
                "protocol_id": "grader",
                "dimensions": [{"name": name, "score": 4} for name in DIMENSIONS],
            },
        },
    }


def fixture(attempts=3, purpose="baseline"):
    policy = json.loads((ROOT / "policy/Benchmark Campaign.json").read_text())
    roster = [
        {"id": key, "family": family}
        for key, family in zip("abc", ["nothing", "superpowers", "studio-moser"], strict=True)
    ]
    manifests, reports = [], []
    for lane in ["comparison", "deepswe"]:
        tasks = [task for task, spec in policy["tasks"].items() if spec[0] == lane]
        conditions = {
            "task_variant": lane,
            "task_ids": tasks,
            "task_digests": {task: digest(f"task-{task}") for task in tasks},
            "attempts": attempts,
            "decision_policy": "benchmark-readiness-v2",
            "kickoff": {"model": "synthetic"},
            "adapter_digest": digest("adapter-1"),
        }
        request = {
            "request_id": f"{lane}-request",
            "label": f"{lane} lane",
            "conditions": conditions,
            "contenders": roster,
            "evaluation_inputs": {"implementation": "synthetic"},
            "purpose": purpose,
            "baseline_result_ids": [],
            "predecessor_result_ids": [],
            "first_version": True,
            "change": {"hypothesis": "synthetic"},
        }
        manifest_digest = contender_identity(request)
        manifests.append({"digest": manifest_digest, "provenance": {"experiment": request}})
        reports.append(
            {
                "report_id": lane,
                "manifest_digest": manifest_digest,
                "evidence": {"review_state": "unreviewed"},
                "experiment": {
                    **copy.deepcopy(request),
                    "trials": [
                        _trial(contender, task, attempt)
                        for contender in "abc"
                        for task in tasks
                        for attempt in range(1, attempts + 1)
                    ],
                },
            }
        )
    plan = build_campaign(policy, manifests)
    return policy, manifests, {"digest": contender_identity(plan), **plan}, reports


def test_campaign_declares_complete_lanes_and_total_evaluation_workload():
    import tomllib

    policy, _, plan, reports = fixture()
    profiles = tomllib.loads((ROOT / "runs/Profiles.toml").read_text())["profiles"]
    assert profiles["research"]["max_sessions"] >= 5 * 3 * 3
    assert len(policy["tasks"]) == 24
    assert plan["workload"]["coding_trials"] == 216
    assert plan["workload"]["minimum_model_sessions"] == 648
    assert "human_pairs" not in plan["workload"]
    result = summarize(plan, reports)
    assert result["status"] == "recommended" and result["winner_id"] == "a"
    assert result["lanes"]["comparison"]["comparison"]["status"] == "recommended"
    assert result["lanes"]["comparison"]["superseded_trials"] == []
    assert result["summaries"]["overall"][0] == {
        "id": "a",
        "trials": 72,
        "correct": 72,
        "outcomes": {"completed": 72},
        "duration_seconds": 720,
        "cost_usd": 36.0,
        "usage_complete": True,
        "quality": 0.8,
    }
    assert len(result["summaries"]) == 14  # overall, all twelve cells, held-out subset
    document = request_document()
    document["conditions"].update(plan["lanes"]["comparison"]["conditions"])
    document["conditions"]["kickoff"] = request_document()["conditions"]["kickoff"]
    document["limits"]["max_sessions"] = 57
    assert validate_experiment_request(document) == []


def test_campaign_matches_both_lanes_without_allowing_condition_or_identity_drift():
    policy, manifests, plan, reports = fixture()
    with pytest.raises(ValueError, match="missing a lane"):
        build_campaign(policy, manifests[:1])
    changed = copy.deepcopy(manifests)
    changed[1]["provenance"]["experiment"]["conditions"]["kickoff"]["model"] = "different"
    with pytest.raises(ValueError, match="incompatible"):
        build_campaign(policy, changed)
    with pytest.raises(ValueError, match="both lane reports"):
        summarize(plan, reports[:1])
    with pytest.raises(ValueError, match="one immutable revision per manifest"):
        summarize(plan, reports + reports[:1])
    reports[0]["manifest_digest"] = "other"
    with pytest.raises(ValueError, match="frozen campaign manifest"):
        summarize(plan, reports)


def test_campaign_unresolved_review_claims_failures_and_duplicate_trials_cannot_win():
    _, _, plan, original = fixture()
    # A missing automated grade leaves quality unknown but does not touch the verdict.
    reports = copy.deepcopy(original)
    reports[0]["experiment"]["trials"][0]["collaboration"]["grade"]["dimensions"][0]["score"] = None
    result = summarize(plan, reports)
    assert result["winner_id"] == "a"
    assert result["summaries"]["overall"][0]["quality"] is None
    # An unconfirmed reviewer claim is advisory; a confirmed defect disqualifies.
    reports = copy.deepcopy(original)
    reports[0]["experiment"]["trials"][0]["code_review"]["findings"].append(
        {"status": "unconfirmed", "severity": "P2"}
    )
    assert summarize(plan, reports)["winner_id"] == "a"
    reports[0]["experiment"]["trials"][0]["code_review"]["findings"].append(
        {"status": "confirmed", "severity": "P1"}
    )
    assert summarize(plan, reports)["winner_id"] is None
    # One genuine failure removes that contender from eligibility; the others still compete.
    reports = copy.deepcopy(original)
    reports[0]["experiment"]["trials"][0].update(correctness=False)
    result = summarize(plan, reports)
    assert result["winner_id"] is None and result["status"] == "no_clear_winner"
    assert result["lanes"]["comparison"]["comparison"]["contenders"][0]["eligible"] is False
    reports = copy.deepcopy(original)
    reports[0]["experiment"]["trials"].append(reports[0]["experiment"]["trials"][0])
    with pytest.raises(ValueError, match="duplicated"):
        summarize(plan, reports)


def test_campaign_weights_export_variants_as_one_task_block():
    _, _, plan, reports = fixture()
    for report in reports:
        for trial in report["experiment"]["trials"]:
            if trial["task_id"] in {"node-export-clear", "node-export-ambiguous"}:
                for dimension in trial["collaboration"]["grade"]["dimensions"]:
                    dimension["score"] = 1
    result = summarize(plan, reports)
    assert result["summaries"]["overall"][0]["quality"] == pytest.approx((22 * 0.8 + 0.2) / 23)


def test_one_attempt_diagnostic_campaign_is_decision_evidence():
    policy, manifests, plan, reports = fixture(attempts=1, purpose="diagnostic")
    assert plan["workload"]["coding_trials"] == 72
    result = summarize(plan, reports)
    assert result["status"] == "recommended" and result["winner_id"] == "a"
    assert result["reasons"] == []
    # A timed-out patch can pass checks, but did not complete the task.
    trial = reports[0]["experiment"]["trials"][0]
    trial.update(status="timeout", usage_complete=False, cost_usd=None)
    result = summarize(plan, reports)
    row = result["summaries"]["overall"][0]
    assert row["correct"] == 23 and row["outcomes"]["timeout"] == 1
    assert row["duration_seconds"] == 240 and row["cost_usd"] is None
    assert row["usage_complete"] is False
    assert result["winner_id"] is None
    trial["duration_seconds"] = None
    assert summarize(plan, reports)["summaries"]["overall"][0]["duration_seconds"] is None
    with pytest.raises(ValueError, match="sufficient attempts"):
        build_campaign(dict(policy, minimum_attempts=3), manifests)
    manifests[0]["provenance"]["experiment"]["purpose"] = "candidate"
    with pytest.raises(ValueError, match="fresh decision baselines"):
        build_campaign(policy, manifests)


def _split(report, tasks, *, continuation_id, task_digest=None, statuses=None):
    """Move the given tasks' trials and labels into a continuation report."""
    experiment = report["experiment"]
    moved = [t for t in experiment["trials"] if t["task_id"] in tasks]
    for trial in moved:
        trial.update((statuses or {}).get(trial["task_id"], {"status": "pending"}))
        if trial["status"] != "completed":
            trial.update(correctness=None, protected_state=None)
    continuation = copy.deepcopy(report)
    continuation["report_id"] = continuation_id
    continuation["manifest_digest"] = f"manifest-{continuation_id}"
    continuation["experiment"]["label"] = continuation_id
    continuation["experiment"]["conditions"] = dict(
        experiment["conditions"],
        task_ids=list(tasks),
        task_digests={
            task: task_digest or experiment["conditions"]["task_digests"][task] for task in tasks
        },
    )
    continuation["experiment"]["trials"] = [
        dict(t, trial_id=f"{continuation_id}:{t['trial_id']}", status="completed",
             correctness=True, protected_state=True)
        for t in copy.deepcopy(moved)
    ]
    return continuation


def test_campaign_assembles_original_recovery_and_correction_reports():
    _, _, plan, reports = fixture(attempts=1, purpose="diagnostic")
    original = reports[0]
    # Unstarted slots and an infrastructure failure are completed by a recovery run.
    recovery = _split(
        original,
        ["react-accent-polish", "node-export-clear"],
        continuation_id="recovery",
        statuses={"node-export-clear": {"status": "infrastructure_failure"}},
    )
    recovery["experiment"]["conditions"]["adapter_digest"] = digest("adapter-2")
    # A corrected fixture reruns one task for every contender under a new task digest.
    correction = _split(
        original, ["react-saved-view-feature"], continuation_id="correction",
        task_digest=digest("task-react-saved-view-feature-v2"),
        statuses={"react-saved-view-feature": {"status": "completed", "correctness": False}},
    )
    result = summarize(plan, [original, recovery, correction, reports[1]])
    lane = result["lanes"]["comparison"]
    assert result["status"] == "recommended" and result["winner_id"] == "a"
    assert [m["trials_used"] for m in lane["members"]] == [16 * 3, 2 * 3, 3]
    assert [m["adapter_corrected"] for m in lane["members"]] == [False, True, False]
    assert lane["task_digests"]["react-saved-view-feature"] == digest(
        "task-react-saved-view-feature-v2"
    )
    assert sorted(row["status"] for row in lane["superseded_trials"]) == [
        "completed", "completed", "completed", "infrastructure_failure",
        "infrastructure_failure", "infrastructure_failure",
    ]
    assert all(row["task_corrected"] for row in lane["superseded_trials"]
               if row["status"] == "completed")
    assert len(lane["limitations"]) == 2
    assert lane["comparison"]["contenders"][0]["completed"] == 19
    # Order is authoritative: listing the original last would try to undo the correction.
    with pytest.raises(ValueError, match="first report must belong"):
        summarize(plan, [recovery, original, correction, reports[1]])


def test_campaign_assembly_refuses_cherry_picking_gaps_and_uneven_corrections():
    _, _, plan, reports = fixture(attempts=1, purpose="diagnostic")
    original = reports[0]
    # A completed trial on an unchanged task cannot be replaced by a rerun.
    retry = _split(copy.deepcopy(original), ["react-accent-polish"], continuation_id="retry",
                   statuses={"react-accent-polish": {"status": "completed"}})
    with pytest.raises(ValueError, match="cannot be replaced without a task correction"):
        assemble_lane(plan, "comparison", [original, retry])
    # A slot that never completed leaves the lane incomplete.
    gap = copy.deepcopy(original)
    gap["experiment"]["trials"][0].update(status="pending", correctness=None)
    with pytest.raises(ValueError, match="incomplete"):
        assemble_lane(plan, "comparison", [gap])
    # A correction must cover every contender, or the task inputs differ across contenders.
    uneven_source = copy.deepcopy(original)
    uneven = _split(uneven_source, ["node-export-clear"], continuation_id="uneven",
                    task_digest=digest("task-node-export-clear-v2"),
                    statuses={"node-export-clear": {"status": "completed"}})
    uneven["experiment"]["trials"] = uneven["experiment"]["trials"][:1]
    uneven["experiment"]["contenders"] = uneven["experiment"]["contenders"][:1]
    with pytest.raises(ValueError, match="differ across contenders"):
        assemble_lane(plan, "comparison", [uneven_source, uneven])
    # A continuation under different kickoff conditions is not the same campaign.
    other = _split(copy.deepcopy(original), ["node-export-clear"], continuation_id="other")
    other["experiment"]["conditions"]["kickoff"] = {"model": "different"}
    with pytest.raises(ValueError, match="incompatible conditions"):
        assemble_lane(plan, "comparison", [original, other])
    # A report from the wrong lane is rejected before any slot is filled.
    with pytest.raises(ValueError, match="continuation report has incompatible conditions"):
        assemble_lane(plan, "comparison", [original, reports[1]])


def test_retired_tasks_are_left_out_of_the_verdict_without_touching_evidence():
    _, _, plan, reports = fixture(attempts=1, purpose="diagnostic")
    research = [t for t, spec in plan["policy"]["tasks"].items() if spec[0] == "deepswe"]
    retired = research[-1]
    for trial in reports[1]["experiment"]["trials"]:
        if trial["task_id"] == retired:
            trial.update(correctness=False)
    active = set(plan["policy"]["tasks"]) - {retired}
    result = summarize_campaign(plan, reports, policy_for_lane=policy_for_lane, active_tasks=active)
    lane = result["lanes"]["deepswe"]["comparison"]
    assert result["summaries"]["overall"][0]["trials"] == len(active)
    assert lane["unsolved_tasks"] == []
    assert all(row["passed_all"] for row in lane["contenders"])
    assert any(t["task_id"] == retired for t in reports[1]["experiment"]["trials"])
