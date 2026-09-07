import copy
import json
from pathlib import Path

import pytest

from harness_testing.Review_References import validate_review_references
from harness_testing.Run_Reports import run_report_id

ROOT = Path(__file__).parents[2]
PROTOCOL = "sha256:" + "a" * 64


def _old() -> dict:
    report = json.loads((ROOT / "tests/Fixtures/Run_Reports/Comparison.json").read_text())
    report["report_id"] = run_report_id(report)
    return report


def _reviewed(old: dict, protocol: str = PROTOCOL) -> dict:
    report = copy.deepcopy(old)
    for trial in report["experiment"]["trials"]:
        trial["code_review"] = {
            "protocol_id": protocol,
            "status": "incomplete",
            "target_digest": "sha256:" + "b" * 64,
            "findings": [],
            "cost_usd": None,
            "duration_seconds": None,
            "usage_complete": False,
            "model_usage": [],
            "internal_review": {
                "status": "unknown",
                "found": None,
                "fixed": None,
                "unresolved": None,
                "evidence_digest": None,
            },
        }
    report["experiment"]["code_review"] = {
        "plan_id": "sha256:" + "c" * 64,
        "protocol_id": protocol,
        "source_report_id": old["report_id"],
        "results_digest": "sha256:" + "d" * 64,
        "evaluation_cost_usd": None,
    }
    report["report_id"] = run_report_id(report)
    return report


def _source(*ids: str) -> dict:
    return {
        "experiment": {
            "baseline_result_ids": list(ids[:1]),
            "predecessor_result_ids": list(ids[1:]),
        }
    }


def _reports(monkeypatch, reports):
    monkeypatch.setattr(
        "harness_testing.Review_References.available_reference_reports", lambda root: reports
    )


def test_accepts_explicit_baseline_and_predecessor_successors(monkeypatch):
    baseline, predecessor = _old(), _old()
    predecessor["run_id"] = "run-" + "1" * 20
    predecessor["report_id"] = run_report_id(predecessor)
    reviewed_baseline, reviewed_predecessor = _reviewed(baseline), _reviewed(predecessor)
    _reports(monkeypatch, [baseline, predecessor, reviewed_baseline, reviewed_predecessor])

    assert validate_review_references(
        ROOT,
        _source(baseline["report_id"], predecessor["report_id"]),
        PROTOCOL,
        {
            baseline["report_id"]: reviewed_baseline["report_id"],
            predecessor["report_id"]: reviewed_predecessor["report_id"],
        },
    ) == {
        baseline["report_id"]: reviewed_baseline["report_id"],
        predecessor["report_id"]: reviewed_predecessor["report_id"],
    }


@pytest.mark.parametrize("change", ["protocol", "execution", "source"])
def test_rejects_wrong_successor_evidence(monkeypatch, change):
    old = _old()
    reviewed = _reviewed(old)
    if change == "protocol":
        reviewed["experiment"]["code_review"]["protocol_id"] = "sha256:" + "e" * 64
    elif change == "execution":
        reviewed["experiment"]["trials"][0]["cost_usd"] = 9
    else:
        reviewed["experiment"]["code_review"]["source_report_id"] = "sha256:" + "e" * 64
    reviewed["report_id"] = run_report_id(reviewed)
    _reports(monkeypatch, [old, reviewed])

    with pytest.raises(ValueError):
        validate_review_references(
            ROOT, _source(old["report_id"]), PROTOCOL, {old["report_id"]: reviewed["report_id"]}
        )


def test_rejects_unselected_and_ambiguous_references(monkeypatch):
    old, reviewed = _old(), _reviewed(_old())
    _reports(monkeypatch, [old, old, reviewed])

    with pytest.raises(ValueError, match="unselected"):
        validate_review_references(
            ROOT, _source(), PROTOCOL, {old["report_id"]: reviewed["report_id"]}
        )
    with pytest.raises(ValueError, match="ambiguous"):
        validate_review_references(
            ROOT, _source(old["report_id"]), PROTOCOL, {old["report_id"]: reviewed["report_id"]}
        )
