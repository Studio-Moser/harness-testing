import copy
import json
from pathlib import Path

import pytest

from harness_testing.Experiments import (
    available_reference_reports,
    comparison_mismatches,
    contender_identity,
    resolve_reference_reports,
    validate_experiment_request,
)


def test_reference_discovery_ignores_publication_receipts(tmp_path, monkeypatch):
    report_id = "a" * 64
    evidence = tmp_path / "runs" / "evidence"
    evidence.mkdir(parents=True)
    (evidence / f"{report_id}.json").write_text("{}")
    (evidence / f"{report_id}.Publication.json").write_text("{}")
    loaded = []

    def load_report(_root, path):
        loaded.append(path.name)
        return {"report_id": path.stem}

    monkeypatch.setattr("harness_testing.Run_Reports.load_run_report", load_report)

    assert available_reference_reports(tmp_path) == [{"report_id": report_id}]
    assert loaded == [f"{report_id}.json"]


def request_document():
    return {
        "schema_version": "1",
        "label": "Rubric iteration",
        "purpose": "candidate",
        "skill_evaluation": None,
        "contenders": [
            {
                "family": "studio-moser",
                "label": "Routing revised",
                "sources": [
                    {
                        "name": "Studio Moser",
                        "kind": "collection",
                        "source": "https://example.invalid/collection.git",
                        "commit": "a" * 40,
                    }
                ],
                "rubric": {"mode": "disabled", "path": None},
                "startup_paths": [],
                "delivery_config": {},
            }
        ],
        "conditions": {
            "kickoff": {
                "provider": "codex",
                "runtime_version": "0.150.1",
                "model": "fixture-model",
                "effort": "high",
            },
            "task_ids": ["react-active-badge-count"],
            "task_variant": "comparison",
            "executor_inventory": [],
            "attempts": 3,
            "concurrency": 1,
            "timeout_seconds": 1800,
            "retry_policy": "none",
            "accounting_policy": "agent-tree-v1",
            "decision_policy": "development-comparison-v1",
            "resources": {"cpus": 2, "memory_mb": 4096},
        },
        "baseline_result_ids": ["sha256:" + "b" * 64],
        "predecessor_result_ids": [],
        "first_version": True,
        "change": {
            "summary": "Disable routing",
            "hypothesis": "Reduce task overhead",
            "rerun_reason": None,
        },
        "limits": {
            "billing_mode": "subscription",
            "max_sessions": 3,
            "max_budget_usd": 0,
            "interaction_limit": 12,
        },
        "publication": {"mode": "local-only"},
    }


def test_request_validation_is_strict_and_aggregates_errors():
    document = request_document()
    assert validate_experiment_request(document) == []
    document["baseline_result_ids"] = []
    document["unknown"] = "not accepted"
    document["limits"]["max_sessions"] = 0
    errors = "\n".join(validate_experiment_request(document))
    assert "baseline_result_ids" in errors
    assert "unknown" in errors
    assert "max_sessions" in errors


def test_request_accepts_explicit_skill_capability_invocation():
    document = request_document()
    document["skill_evaluation"] = {
        "mode": "capability",
        "name": "harness:execute",
    }

    assert validate_experiment_request(document) == []


def test_request_keeps_skill_evaluation_optional_for_version_one_inputs():
    document = request_document()
    document.pop("skill_evaluation")

    assert validate_experiment_request(document) == []


def test_startup_instructions_can_define_a_personality_only_contender():
    document = request_document()
    contender = document["contenders"][0]
    contender["family"] = "studio-personality"
    contender["sources"] = []
    contender["startup_paths"] = ["runs/inputs/House Style.md"]
    assert validate_experiment_request(document) == []


def test_non_nothing_contender_requires_a_frozen_input():
    document = request_document()
    contender = document["contenders"][0]
    contender["sources"] = []
    assert any(
        "sources or startup_paths" in error for error in validate_experiment_request(document)
    )


def test_only_common_conditions_change_comparison_compatibility():
    first = request_document()["conditions"]
    assert comparison_mismatches(first, copy.deepcopy(first)) == []
    assert comparison_mismatches(first, first | {"attempts": 1}) == ["attempts"]
    changed = copy.deepcopy(first)
    changed["kickoff"]["effort"] = "low"
    assert comparison_mismatches(first, changed) == ["kickoff.effort"]


@pytest.mark.parametrize("allowance", [0, 600, 3600])
def test_provider_recovery_is_an_explicit_comparison_condition(allowance):
    document = request_document()
    document["conditions"]["provider_recovery_seconds"] = allowance
    assert validate_experiment_request(document) == []
    original = request_document()["conditions"]
    assert comparison_mismatches(original, document["conditions"]) == ["provider_recovery_seconds"]


@pytest.mark.parametrize("allowance", [-1, True, 0.5, 600.0, 3601, float("inf")])
def test_invalid_provider_recovery_is_rejected(allowance):
    document = request_document()
    document["conditions"]["provider_recovery_seconds"] = allowance
    assert validate_experiment_request(document)


def test_recovery_requires_a_supported_native_protocol():
    document = request_document()
    document["conditions"]["kickoff"]["provider"] = "claude"
    document["conditions"]["provider_recovery_seconds"] = 600
    assert any("Codex" in e for e in validate_experiment_request(document))


def test_contender_identity_tracks_effective_inputs_not_labels():
    effective = {
        "sources": [{"commit": "a" * 40}],
        "rubric_digest": "one",
        "inventory": ["harness:execute"],
        "startup_digest": "two",
    }
    assert contender_identity(effective) == contender_identity(dict(effective))
    assert contender_identity(effective) != contender_identity(effective | {"rubric_digest": "off"})


def reference_report(request):
    from harness_testing.Run_Reports import run_report_id

    report = {
        "experiment": {
            "conditions": copy.deepcopy(request["conditions"]),
            "contenders": [
                {"id": "nothing", "family": "nothing"},
                {"id": "superpowers", "family": "superpowers"},
            ],
            "trials": [
                {
                    "contender_id": contender,
                    "task_id": task,
                    "attempt": attempt,
                    "status": "completed",
                }
                for contender in ("nothing", "superpowers")
                for task in request["conditions"]["task_ids"]
                for attempt in range(1, 4)
            ],
        }
    }
    report["report_id"] = run_report_id(report)
    request["baseline_result_ids"] = [report["report_id"]]
    return report


def test_reference_selection_is_exact_validated_and_never_latest():
    request = request_document()
    report = reference_report(request)
    unrelated = {"report_id": "sha256:" + "d" * 64}
    assert resolve_reference_reports(request, [unrelated, report]) == [report]
    with pytest.raises(ValueError, match="missing reference"):
        resolve_reference_reports(request, [unrelated])
    report["experiment"]["conditions"]["attempts"] = 1
    with pytest.raises(ValueError, match="identity"):
        resolve_reference_reports(request, [report])


def test_incompatible_and_partial_baselines_are_rejected():
    from harness_testing.Run_Reports import run_report_id

    request = request_document()
    report = reference_report(request)
    report["experiment"]["trials"].pop()
    report["report_id"] = run_report_id(report)
    request["baseline_result_ids"] = [report["report_id"]]
    with pytest.raises(ValueError, match="coverage"):
        resolve_reference_reports(request, [report])
    report = reference_report(request)
    request["conditions"]["kickoff"]["effort"] = "low"
    with pytest.raises(ValueError, match="kickoff.effort"):
        resolve_reference_reports(request, [report])


def test_nonfinite_and_contradictory_request_is_rejected():
    request = request_document()
    request["limits"]["max_budget_usd"] = float("nan")
    assert validate_experiment_request(request)
    request = request_document()
    request["first_version"] = False
    assert any("predecessor" in error for error in validate_experiment_request(request))


def test_schema_is_valid_json_schema():
    from jsonschema import Draft202012Validator

    path = Path(__file__).parents[2] / "policy" / "Experiment Request.schema.json"
    Draft202012Validator.check_schema(json.loads(path.read_text()))


@pytest.mark.parametrize("reference_kind", ["baseline_result_ids", "predecessor_result_ids"])
def test_diagnostic_reference_reports_are_rejected_before_planning(reference_kind):
    from harness_testing.Run_Reports import run_report_id

    request = request_document()
    report = reference_report(request)
    if reference_kind == "predecessor_result_ids":
        request.update(baseline_result_ids=[], first_version=False)
        report["experiment"]["contenders"] = [{"id": "prior", "family": "studio-moser"}]
        report["experiment"]["trials"] = [
            {**trial, "contender_id": "prior"}
            for trial in report["experiment"]["trials"]
            if trial["contender_id"] == "nothing"
        ]
        report["report_id"] = run_report_id(report)
        request[reference_kind] = [report["report_id"]]
    assert resolve_reference_reports(request, [report]) == [report]
    report["experiment"]["purpose"] = "diagnostic"
    report["report_id"] = run_report_id(report)
    request[reference_kind] = [report["report_id"]]
    with pytest.raises(ValueError, match="diagnostic reference"):
        resolve_reference_reports(request, [report])


def test_comparison_schedule_balances_order_and_preserves_every_slot():
    from collections import Counter

    from harness_testing.Runs import comparison_schedule

    schedule = comparison_schedule([0, 1, 2], ["task-a", "task-b"], 3)
    assert len(schedule) == 18
    assert len({(slot["cell_index"], slot["task_id"], slot["attempt"]) for slot in schedule}) == 18
    for task in ["task-a", "task-b"]:
        first = [
            schedule[index]["cell_index"]
            for index in range(0, len(schedule), 3)
            if schedule[index]["task_id"] == task
        ]
        assert Counter(first) == {0: 1, 1: 1, 2: 1}


def test_documented_requests_validate_and_select_only_candidate_on_iteration():
    root = Path(__file__).parents[2]
    requests = [
        json.loads(path.read_text()) for path in (root / "runs/examples").glob("* Comparison.json")
    ]
    assert len(requests) == 3
    for document in requests:
        assert validate_experiment_request(document) == []
    candidate = next(document for document in requests if document["purpose"] == "candidate")
    assert [c["family"] for c in candidate["contenders"]] == ["studio-moser"]
    assert candidate["limits"]["max_sessions"] == 27
    opus = next(document for document in requests if document["label"].startswith("Opus 5"))
    assert [c["family"] for c in opus["contenders"]] == [
        "nothing",
        "studio-personality",
        "studio-moser",
    ]
    assert opus["conditions"]["kickoff"]["model"] == "claude-opus-5"


def test_runtime_images_use_contents_not_only_recipes(monkeypatch, tmp_path):
    from harness_testing import Materialize
    from harness_testing.Experiments import runtime_image_digests

    checked = []
    monkeypatch.setattr(
        Materialize, "require_current_image", lambda root, name: checked.append(name)
    )
    monkeypatch.setattr(Materialize, "image_reference", lambda root, name: name)
    monkeypatch.setattr(Materialize, "_inspect_image_id", lambda name: "sha256:" + "a" * 64)
    first = runtime_image_digests(tmp_path, ["node"])
    monkeypatch.setattr(Materialize, "_inspect_image_id", lambda name: "sha256:" + "b" * 64)
    assert runtime_image_digests(tmp_path, ["node"]) != first
    assert checked == ["node", "node"]
    monkeypatch.setattr(Materialize, "_inspect_image_id", lambda name: None)
    with pytest.raises(ValueError, match="cannot freeze"):
        runtime_image_digests(tmp_path, ["node"])
