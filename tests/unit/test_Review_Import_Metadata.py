import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_Code_Review_Integration import _results, _root

from harness_testing.Code_Reviews import prepare_review, record_review
from harness_testing.Run_Reports import load_run_report, run_report_id


@pytest.mark.parametrize("claimed_time", ["1970-01-01T00:00:00Z", "2999-01-01T00:00:00Z"])
def test_import_uses_local_time_and_repeat_preserves_identity(tmp_path, monkeypatch, claimed_time):
    root, source = _root(tmp_path, monkeypatch)
    prepared = prepare_review(root, source, root / "policy/Code Review Protocol.json")
    plan = Path(prepared["artifacts"]["files"][0])
    returned = root / "Results.json"
    results = _results(plan)
    results["recorded_at"] = claimed_time
    returned.write_text(json.dumps(results))
    before = datetime.now(UTC)
    outcome = record_review(root, plan, returned)
    report = load_run_report(root, Path(outcome["artifacts"]["report"]))
    assert before <= datetime.fromisoformat(report["updated_at"]) <= datetime.now(UTC)
    assert (
        record_review(root, plan, returned)["artifacts"]["report"] == outcome["artifacts"]["report"]
    )


def test_record_rejects_changed_pricing(tmp_path, monkeypatch):
    root, source = _root(tmp_path, monkeypatch)
    prepared = prepare_review(root, source, root / "policy/Code Review Protocol.json")
    plan = Path(prepared["artifacts"]["files"][0])
    returned = root / "Results.json"
    returned.write_text(json.dumps(_results(plan)))
    monkeypatch.setattr("harness_testing.Code_Reviews._price_usage", lambda *_: (None, "changed"))
    with pytest.raises(ValueError, match="pricing changed"):
        record_review(root, plan, returned)
    assert not (plan.parent / "Imported Results.json").exists()


def test_explicit_reviewed_baseline_and_predecessor_are_frozen_and_reused(tmp_path, monkeypatch):
    root, source = _root(tmp_path, monkeypatch)
    original = json.loads(source.read_text())
    protocol = root / "policy/Code Review Protocol.json"
    prepared = prepare_review(root, source, protocol)
    baseline_plan = Path(prepared["artifacts"]["files"][0])
    returned = root / "Results.json"
    returned.write_text(json.dumps(_results(baseline_plan)))
    baseline_path = Path(record_review(root, baseline_plan, returned)["artifacts"]["report"])
    reviewed_baseline = load_run_report(root, baseline_path)

    candidate = copy.deepcopy(original)
    experiment = candidate["experiment"]
    experiment["purpose"] = "candidate"
    experiment["first_version"] = False
    experiment["contenders"] = [
        c for c in experiment["contenders"] if c["family"] == "studio-moser"
    ]
    selected = experiment["contenders"][0]["id"]
    experiment["trials"] = [t for t in experiment["trials"] if t["contender_id"] == selected]
    experiment["baseline_result_ids"] = [original["report_id"]]
    experiment["predecessor_result_ids"] = [original["report_id"]]
    candidate["report_id"] = run_report_id(candidate)
    candidate_path = root / "Candidate.json"
    candidate_path.write_text(json.dumps(candidate))
    mapping = {original["report_id"]: reviewed_baseline["report_id"]}
    references = root / "References.json"
    references.write_text(json.dumps(mapping))
    prepared = prepare_review(root, candidate_path, protocol, references)
    plan_path = Path(prepared["artifacts"]["files"][0])
    assert json.loads(plan_path.read_text())["reference_revisions"] == mapping
    # Editing the input selection file cannot change the already frozen plan.
    references.write_text("{}")
    returned.write_text(json.dumps(_results(plan_path)))
    outcome = record_review(root, plan_path, returned)
    result = load_run_report(root, Path(outcome["artifacts"]["report"]))["experiment"]
    assert result["baseline_result_ids"] == [reviewed_baseline["report_id"]]
    assert result["predecessor_result_ids"] == [reviewed_baseline["report_id"]]
    assert all(
        c["code_review"]["status"] == "completed" for c in result["comparison"]["contenders"]
    )


def test_confirmation_cannot_reuse_a_session_across_blinded_packets(tmp_path, monkeypatch):
    root, source = _root(tmp_path, monkeypatch)
    prepared = prepare_review(root, source, root / "policy/Code Review Protocol.json")
    plan = Path(prepared["artifacts"]["files"][0])
    results = _results(plan)
    for packet in results["packets"][:2]:
        packet["findings"] = [
            {
                "id": "F1",
                "severity": "P1",
                "category": "correctness",
                "title": "Wrong result",
                "file": "App.ts",
                "line": 1,
                "status": "confirmed",
                "confirmation": {"session_id": "shared-confirmer"},
            }
        ]
    returned = root / "Results.json"
    returned.write_text(json.dumps(results))
    with pytest.raises(ValueError, match="confirmation sessions"):
        record_review(root, plan, returned)
    assert not (plan.parent / "Imported Results.json").exists()


@pytest.mark.parametrize("recorded_digest", [None, "sha256:" + "0" * 64])
def test_prepare_authenticates_retained_harbor_config_before_loading(
    tmp_path, monkeypatch, recorded_digest
):
    from harness_testing import Code_Reviews

    real_trial_inputs = Code_Reviews._trial_inputs
    root, source = _root(tmp_path, monkeypatch)
    monkeypatch.setattr(Code_Reviews, "_trial_inputs", real_trial_inputs)
    report = json.loads(source.read_text())
    manifest = Code_Reviews._manifest_for_report(root, report)
    relative = "jobs/001.yaml"
    trial = report["experiment"]["trials"][0]
    manifest["cells"] = [{"contender": {"id": trial["contender_id"]}}]
    manifest["harbor_config_paths"] = [relative]
    manifest["provenance"]["trial_schedule"] = [
        {"cell_index": 0, "task_id": trial["task_id"], "attempt": trial["attempt"]}
    ]
    if recorded_digest is not None:
        manifest["provenance"]["harbor_config_digests"] = {relative: recorded_digest}
    config = source.parent / relative
    config.parent.mkdir()
    config.write_text("job_name: redirected-job\n")
    monkeypatch.setattr(
        "harness_testing.Config.load_job",
        lambda *_: pytest.fail("unauthenticated config must not be loaded"),
    )
    with pytest.raises(ValueError, match="Harbor config digest"):
        prepare_review(root, source, root / "policy/Code Review Protocol.json")
    assert not (root / "runs/reviews").exists()
