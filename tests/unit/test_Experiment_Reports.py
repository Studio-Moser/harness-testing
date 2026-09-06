import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_Experiments import request_document

from harness_testing.Experiment_Reports import attach_experiment_report
from harness_testing.Run_Reports import run_report_id, validate_run_report

ROOT = Path(__file__).parents[2]


def test_empty_comparison_stays_insufficient_and_sanitized(tmp_path):
    request = request_document()
    request["purpose"] = "diagnostic"
    request["baseline_result_ids"] = []
    request["request_id"] = "sha256:" + "a" * 64
    request["change"]["diff_digest"] = "sha256:" + "b" * 64
    request["contenders"] = [
        {
            "id": "sha256:" + "c" * 64,
            "family": "studio-moser",
            "label": "Fixture",
            "source_commits": ["d" * 40],
            "inventory_digest": "sha256:" + "e" * 64,
            "rubric_digest": None,
        }
    ]
    for name in ("evaluator_digest", "scripted_user_digest", "authority_digest", "adapter_digest"):
        request["conditions"][name] = "sha256:" + "f" * 64
    request["conditions"]["task_digests"] = {"react-active-badge-count": "sha256:" + "f" * 64}
    request["conditions"]["image_digests"] = {"node": "sha256:" + "f" * 64}
    manifest = SimpleNamespace(
        provenance={"experiment": request}, harbor_config_paths=[], cells=[], attempts=3
    )
    report = json.loads((ROOT / "tests/Fixtures/Run_Reports/Valid.json").read_text())
    attach_experiment_report(ROOT, manifest, report)
    report["report_id"] = run_report_id(report)
    assert report["schema_version"] == "3"
    assert report["experiment"]["comparison"]["winner_id"] is None
    assert report["observed_api_equivalent_cost_usd"] is None
    assert validate_run_report(ROOT, report, published=True) == ()
    original_id = report["report_id"]
    previous = report | {"status": "completed"}
    attach_experiment_report(ROOT, manifest, report, previous)
    assert report["experiment"]["supersedes_report_id"] == original_id
    previous = report | {"status": "running"}
    attach_experiment_report(ROOT, manifest, report, previous)
    assert report["experiment"]["supersedes_report_id"] == original_id
    report["experiment"]["change"]["summary"] = "/Users/private/token"
    assert any("sensitive" in e for e in validate_run_report(ROOT, report))


def test_new_report_fields_are_strict():
    schema = json.loads((ROOT / "policy/Run_Report.schema.json").read_text())
    assert schema["$defs"]["comparisonTrial"]["additionalProperties"] is False
    assert schema["$defs"]["comparison"]["additionalProperties"] is False


@pytest.mark.parametrize("status", ["running", "completed"])
def test_quill_deepswe_diagnostic_report_schema_accepts_pending_and_completed(status):
    report = json.loads((ROOT / "tests/Fixtures/Run_Reports/Comparison.json").read_text())
    experiment = report["experiment"]
    experiment["purpose"] = "diagnostic"
    experiment["conditions"].update(
        task_ids=["quill-shared-toolbar-focus"],
        task_variant="deepswe",
        attempts=1,
        task_digests={"quill-shared-toolbar-focus": "sha256:" + "b" * 64},
        image_digests={"quill-shared-toolbar-focus:agent": "sha256:" + "b" * 64},
    )
    report.update(
        profile="research",
        status=status,
        expected_jobs=3,
        completed_jobs=3 if status == "completed" else 0,
        pending_jobs=0 if status == "completed" else 3,
        expected_trials=3,
        completed_trials=3 if status == "completed" else 0,
        finished_at="2026-09-03T20:01:00Z" if status == "completed" else None,
    )
    report["report_id"] = run_report_id(report)

    assert validate_run_report(ROOT, report) == ()


def test_infrastructure_failure_and_safe_agent_breakdown(tmp_path):
    from harness_testing.Experiment_Reports import _safe_trial

    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "verifier").mkdir()
    (trial / "result.json").write_text(
        json.dumps({"exception_info": {"exception_type": "EnvironmentStopError"}})
    )
    (trial / "verifier/reward.json").write_text('{"reward":1}')
    usage = {
        "provider": "openai",
        "model": "gpt-5.6-terra",
        "input_tokens": 20,
        "output_tokens": 10,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    session = usage | {"session": "child_1", "effort": "low", "private_path": "/Users/private"}
    (trial / "agent/Trial_Evidence.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "usage_complete": True,
                "model_usage": [usage],
                "session_usage": [session],
            }
        )
    )
    result = _safe_trial(ROOT, "react-active-badge-count", "sha256:" + "a" * 64, 1, trial)
    assert result["status"] == "infrastructure_failure"
    assert result["session_usage"] == [{k: v for k, v in session.items() if k != "private_path"}]
    assert result["cost_usd"] is not None  # Recorded work is retained, not counted as free.


def test_safe_trial_keeps_research_protected_state_unknown(tmp_path: Path):
    from harness_testing.Experiment_Reports import _safe_trial

    directory = tmp_path / "trial"
    (directory / "verifier").mkdir(parents=True)
    (directory / "verifier" / "reward.json").write_text('{"reward": 1}\n')

    trial = _safe_trial(
        ROOT,
        "quill-shared-toolbar-focus",
        "sha256:" + "a" * 64,
        1,
        directory,
        task_variant="research",
    )

    assert trial["correctness"] is True
    assert trial["protected_state"] is None


def test_comparison_pricing_reprices_at_one_complete_snapshot():
    from harness_testing.Comparisons import _cost
    from harness_testing.Experiment_Reports import comparison_pricing

    pricing = comparison_pricing(ROOT)
    trial = {
        "usage_complete": True,
        "cost_usd": 999,
        "pricing_digest": "old",
        "model_usage": [
            {
                "provider": "openai",
                "model": "gpt-6-astra",
                "input_tokens": 1000000,
                "output_tokens": 0,
                "cache_read_tokens": 1000000,
                "cache_write_tokens": 0,
            }
        ],
    }
    assert _cost(trial, pricing) == 11
    assert trial["cost_usd"] == 999


def test_populated_comparison_fixture_is_public_safe():
    report = json.loads((ROOT / "tests/Fixtures/Run_Reports/Comparison.json").read_text())
    assert validate_run_report(ROOT, report, published=True) == ()
    report["experiment"]["trials"][0]["session_usage"][0]["session"] = "provider-private-session"
    report["report_id"] = run_report_id(report)
    assert validate_run_report(ROOT, report, published=True)
