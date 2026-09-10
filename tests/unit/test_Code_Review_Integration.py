import hashlib
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "root"
    shutil.copytree(ROOT / "policy", root / "policy")
    shutil.copy2(ROOT / "Versions.toml", root / "Versions.toml")
    report = json.loads((ROOT / "tests/Fixtures/Run_Reports/Comparison.json").read_text())
    from harness_testing.Run_Reports import run_report_id

    report["experiment"]["conditions"]["image_digests"]["rust"] = "sha256:" + "b" * 64
    report["report_id"] = run_report_id(report)
    report_path = (
        root
        / "runs/generated"
        / report["manifest_digest"].removeprefix("sha256:")
        / "Run_Report.json"
    )
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    patch = root / "fixtures/Final.patch"
    instruction = root / "fixtures/Comparison Instruction.md"
    patch.parent.mkdir()
    patch.write_text("diff --git a/App.tsx b/App.tsx\n+fixture\n")
    instruction.write_text("Review this neutral task requirement.\n")

    manifest = {
        "digest": report["manifest_digest"],
        "provenance": {
            "image_input_digests": {"node": "sha256:" + "1" * 64},
            "experiment": {"conditions": report["experiment"]["conditions"]},
        },
    }
    monkeypatch.setattr("harness_testing.Code_Reviews._manifest_for_report", lambda *_: manifest)
    monkeypatch.setattr(
        "harness_testing.Code_Reviews._trial_inputs",
        lambda *_: {
            "patch_path": patch,
            "patch": patch.read_bytes(),
            "instruction_path": instruction,
            "instruction": instruction.read_bytes(),
            "base": "fixture-base",
        },
    )
    return root, report_path


def _results(plan_path: Path) -> dict:
    plan = json.loads(plan_path.read_text())
    return {
        "schema_version": "1",
        "plan_id": plan["plan_id"],
        "protocol_id": plan["protocol"]["protocol_id"],
        "recorded_at": "2026-09-06T00:00:00Z",
        "conditions": plan["conditions"],
        "packets": [
            {
                "packet_id": packet["packet_id"],
                "target_digest": packet["target_digest"],
                "conditions": plan["conditions"],
                "status": "completed",
                "session_id": f"fresh-{index}",
                "fresh_session": True,
                "no_tested_harness": True,
                "usage_complete": True,
                "duration_seconds": 1,
                "model_usage": [
                    {
                        "provider": "openai",
                        "model": "gpt-6-astra",
                        "input_tokens": 10,
                        "output_tokens": 1,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                    }
                ],
                "findings": [],
                "internal_review": {"status": "unknown"},
            }
            for index, packet in enumerate(plan["packets"])
        ],
    }


def test_prepare_record_and_repeat_preserve_the_source_and_execution_cost(tmp_path, monkeypatch):
    from harness_testing.Code_Reviews import prepare_review, record_review
    from harness_testing.Run_Reports import load_run_report

    root, report_path = _root(tmp_path, monkeypatch)
    source_bytes = report_path.read_bytes()
    prepared = prepare_review(root, report_path, root / "policy/Code Review Protocol.json")
    plan_path = Path(prepared["artifacts"]["files"][0])
    results_path = root / "Returned Results.json"
    results_path.write_text(json.dumps(_results(plan_path)))

    recorded = record_review(root, plan_path, results_path)
    revision_path = Path(recorded["artifacts"]["report"])
    revision = load_run_report(root, revision_path)

    assert revision["experiment"]["supersedes_report_id"] == json.loads(source_bytes)["report_id"]
    assert revision["observed_api_equivalent_cost_usd"] == 0.01
    assert revision["experiment"]["code_review"]["evaluation_cost_usd"] is not None
    assert (plan_path.parent / "Source Report.json").read_bytes() == source_bytes
    repeated = record_review(root, plan_path, results_path)
    assert Path(repeated["artifacts"]["report"]) == revision_path
    assert report_path.read_bytes() == revision_path.read_bytes()


def test_record_rejects_tampered_target_without_persisting_results(tmp_path, monkeypatch):
    from harness_testing.Code_Reviews import prepare_review, record_review

    root, report_path = _root(tmp_path, monkeypatch)
    prepared = prepare_review(root, report_path, root / "policy/Code Review Protocol.json")
    plan_path = Path(prepared["artifacts"]["files"][0])
    results = _results(plan_path)
    results["packets"][0]["target_digest"] = "sha256:" + "0" * 64
    results_path = root / "Tampered Results.json"
    results_path.write_text(json.dumps(results))

    with pytest.raises(ValueError, match="target"):
        record_review(root, plan_path, results_path)

    assert not (plan_path.parent / "Imported Results.json").exists()
    assert not (plan_path.parent / "Evidence").exists()


def test_partial_trial_coverage_reviews_finished_work_without_erasing_gap(tmp_path, monkeypatch):
    from harness_testing.Code_Reviews import prepare_review, record_review
    from harness_testing.Run_Reports import load_run_report, run_report_id

    root, report_path = _root(tmp_path, monkeypatch)
    source = json.loads(report_path.read_text())
    interrupted = source["experiment"]["trials"][0]
    interrupted.update(status="task_definition_gap", correctness=False)
    source["report_id"] = run_report_id(source)
    report_path.write_text(json.dumps(source, indent=2) + "\n")
    source_bytes = report_path.read_bytes()

    prepared = prepare_review(root, report_path, root / "policy/Code Review Protocol.json")
    plan_path = Path(prepared["artifacts"]["files"][0])
    plan = json.loads(plan_path.read_text())
    assert len(plan["packets"]) == len(source["experiment"]["trials"]) - 1
    assert plan["unreviewed_trials"] == [
        {"trial_id": interrupted["trial_id"], "status": "task_definition_gap"}
    ]
    from harness_testing.Code_Reviews import _verify_frozen_inputs

    for changed in (
        plan | {"packets": plan["packets"][1:]},
        plan | {"packets": plan["packets"] + [plan["packets"][0]]},
        plan | {"unreviewed_trials": []},
    ):
        with pytest.raises(ValueError, match="cover completed trials"):
            _verify_frozen_inputs(root, changed, plan_path.parent)
    results_path = root / "Results.json"
    results_path.write_text(json.dumps(_results(plan_path)))
    recorded = record_review(root, plan_path, results_path)
    revised = load_run_report(root, Path(recorded["artifacts"]["report"]))
    gap = next(
        t for t in revised["experiment"]["trials"] if t["trial_id"] == interrupted["trial_id"]
    )
    assert gap == interrupted
    assert revised["experiment"]["comparison"]["winner_id"] is None
    assert (plan_path.parent / "Source Report.json").read_bytes() == source_bytes
    reviewed = [t for t in revised["experiment"]["trials"] if "code_review" in t]
    assert len(reviewed) == len(plan["packets"])


@pytest.mark.parametrize("tamper", ["patch", "packet", "protocol", "conditions", "session"])
def test_record_rejects_changed_review_inputs(tmp_path, monkeypatch, tamper):
    from harness_testing.Code_Reviews import prepare_review, record_review

    root, report_path = _root(tmp_path, monkeypatch)
    protocol = root / "policy/Code Review Protocol.json"
    prepared = prepare_review(root, report_path, protocol)
    plan_path = Path(prepared["artifacts"]["files"][0])
    results = _results(plan_path)
    if tamper == "patch":
        (root / "fixtures/Final.patch").write_text("changed")
    elif tamper == "packet":
        next((plan_path.parent / "Packets").glob("*.json")).write_text("changed")
    elif tamper == "protocol":
        protocol.write_text(protocol.read_text() + " ")
    elif tamper == "conditions":
        results["packets"][0]["conditions"] = dict(results["conditions"], effort="low")
    else:
        results["packets"][0]["session_id"] = results["packets"][1]["session_id"]
    returned = root / "Results.json"
    returned.write_text(json.dumps(results))
    with pytest.raises(ValueError):
        record_review(root, plan_path, returned)
    assert not (plan_path.parent / "Imported Results.json").exists()


@pytest.mark.parametrize("invalid", [None, "same_session", "blank", "hash", "private"])
def test_confirmation_requires_distinct_session_and_retained_evidence(
    tmp_path, monkeypatch, invalid
):
    from harness_testing.Code_Reviews import prepare_review, record_review
    from harness_testing.Run_Reports import load_run_report

    root, report_path = _root(tmp_path, monkeypatch)
    prepared = prepare_review(root, report_path, root / "policy/Code Review Protocol.json")
    plan_path = Path(prepared["artifacts"]["files"][0])
    results = _results(plan_path)
    packet = results["packets"][0]
    proof = root / "Proof.txt"
    proof.write_text("Reproduced stale active editor on the pinned patch.\n")
    finding = {
        "id": "F1",
        "severity": "P1",
        "category": "correctness",
        "title": "Stale editor",
        "file": "src/App.tsx",
        "line": 2,
        "status": "confirmed",
        "confirmation": {
            "session_id": "separate-verifier",
            "procedure": "Focus the second editor; click Bold.",
            "expected": "Only the second editor changes.",
            "observed": "First editor changes.",
            "evidence": {"path": proof.name, "digest": _digest(proof.read_bytes())},
        },
    }
    if invalid == "same_session":
        finding["confirmation"]["session_id"] = packet["session_id"]
    elif invalid == "blank":
        finding["confirmation"]["procedure"] = " "
    elif invalid == "hash":
        proof.write_text("tampered")
    elif invalid == "private":
        finding["title"] = "/Users/private/raw-log"
    packet["findings"] = [finding]
    returned = root / "Results.json"
    returned.write_text(json.dumps(results))
    if invalid:
        with pytest.raises(ValueError):
            record_review(root, plan_path, returned)
        assert not (plan_path.parent / "Imported Results.json").exists()
        assert not (plan_path.parent / "Evidence").exists()
        # A malformed submission must not poison an otherwise usable plan.
        returned.write_text(json.dumps(_results(plan_path)))
    result = record_review(root, plan_path, returned)
    report = load_run_report(root, Path(result["artifacts"]["report"]))
    reviewed = [f for t in report["experiment"]["trials"] for f in t["code_review"]["findings"]]
    assert len(reviewed) == (0 if invalid else 1)
    if not invalid:
        assert reviewed[0]["evidence_digest"] == _digest(proof.read_bytes())
        reviewed_trial = next(
            trial for trial in report["experiment"]["trials"] if trial["code_review"]["findings"]
        )
        assert reviewed_trial["code_review"]["usage_complete"] is False
        assert reviewed_trial["code_review"]["cost_usd"] is None


@pytest.mark.parametrize("field,value", [("provider", "anthropic"), ("model", "gpt-5.6-sol")])
def test_record_rejects_wrong_review_usage_identity(tmp_path, monkeypatch, field, value):
    from harness_testing.Code_Reviews import prepare_review, record_review

    root, report_path = _root(tmp_path, monkeypatch)
    prepared = prepare_review(root, report_path, root / "policy/Code Review Protocol.json")
    plan_path = Path(prepared["artifacts"]["files"][0])
    results = _results(plan_path)
    results["packets"][0]["model_usage"][0][field] = value
    returned = root / "Wrong Usage.json"
    returned.write_text(json.dumps(results))

    with pytest.raises(ValueError, match="usage"):
        record_review(root, plan_path, returned)


def test_confirmation_usage_adds_distinct_session_cost_and_duration(tmp_path, monkeypatch):
    from harness_testing.Code_Reviews import prepare_review, record_review
    from harness_testing.Run_Reports import load_run_report

    root, report_path = _root(tmp_path, monkeypatch)
    prepared = prepare_review(root, report_path, root / "policy/Code Review Protocol.json")
    plan_path = Path(prepared["artifacts"]["files"][0])
    results = _results(plan_path)
    packet = results["packets"][0]
    proof = root / "Confirmation.txt"
    proof.write_text("Observed the defect on the frozen patch.\n")
    confirmer = "independent-confirmation"
    packet["findings"] = [
        {
            "id": "F-confirmed",
            "severity": "P1",
            "category": "correctness",
            "title": "Confirmed defect",
            "file": "src/App.tsx",
            "line": 1,
            "status": "confirmed",
            "confirmation": {
                "session_id": confirmer,
                "procedure": "Exercise the pinned case.",
                "expected": "Expected behavior.",
                "observed": "Observed defect.",
                "evidence": {"path": proof.name, "digest": _digest(proof.read_bytes())},
            },
        }
    ]
    packet["confirmation_usage"] = [
        {
            "session_id": confirmer,
            "target_digest": packet["target_digest"],
            "conditions": packet["conditions"],
            "fresh_session": True,
            "no_tested_harness": True,
            "usage_complete": True,
            "duration_seconds": 2,
            "model_usage": [
                {
                    "provider": "openai",
                    "model": "gpt-6-astra",
                    "input_tokens": 20,
                    "output_tokens": 2,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                }
            ],
        }
    ]
    returned = root / "Confirmation Results.json"
    returned.write_text(json.dumps(results))

    recorded = record_review(root, plan_path, returned)
    report = load_run_report(root, Path(recorded["artifacts"]["report"]))
    review = next(
        trial["code_review"]
        for trial in report["experiment"]["trials"]
        if trial["code_review"]["findings"]
    )
    assert review["usage_complete"] is True
    assert review["cost_usd"] is not None
    assert review["duration_seconds"] == 3.0
    assert len(review["model_usage"]) == 2


def test_confirmation_usage_rejects_wrong_conditions(tmp_path, monkeypatch):
    from harness_testing.Code_Reviews import prepare_review, record_review

    root, report_path = _root(tmp_path, monkeypatch)
    prepared = prepare_review(root, report_path, root / "policy/Code Review Protocol.json")
    plan_path = Path(prepared["artifacts"]["files"][0])
    results = _results(plan_path)
    packet = results["packets"][0]
    proof = root / "Confirmation.txt"
    proof.write_text("Evidence\n")
    packet["findings"] = [
        {
            "id": "F1",
            "severity": "P1",
            "category": "correctness",
            "title": "Defect",
            "file": "src/App.tsx",
            "line": 1,
            "status": "confirmed",
            "confirmation": {
                "session_id": "confirm",
                "procedure": "Run case.",
                "expected": "Pass.",
                "observed": "Fail.",
                "evidence": {"path": proof.name, "digest": _digest(proof.read_bytes())},
            },
        }
    ]
    packet["confirmation_usage"] = [
        {
            "session_id": "confirm",
            "target_digest": packet["target_digest"],
            "conditions": {**packet["conditions"], "effort": "low"},
            "fresh_session": True,
            "no_tested_harness": True,
            "usage_complete": True,
            "duration_seconds": 1,
            "model_usage": [
                {
                    "provider": "openai",
                    "model": "gpt-6-astra",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                }
            ],
        }
    ]
    returned = root / "Wrong Confirmation Conditions.json"
    returned.write_text(json.dumps(results))

    with pytest.raises(ValueError, match="confirmation usage"):
        record_review(root, plan_path, returned)


def test_interrupted_review_keeps_unknown_usage_and_cannot_win(tmp_path, monkeypatch):
    from harness_testing.Code_Reviews import prepare_review, record_review
    from harness_testing.Run_Reports import load_run_report

    root, report_path = _root(tmp_path, monkeypatch)
    prepared = prepare_review(root, report_path, root / "policy/Code Review Protocol.json")
    plan_path = Path(prepared["artifacts"]["files"][0])
    results = _results(plan_path)
    results["packets"][0].update(status="incomplete", usage_complete=False, duration_seconds=1801)
    results["packets"][0]["model_usage"][0]["output_tokens"] = None
    returned = root / "Results.json"
    returned.write_text(json.dumps(results))
    result = record_review(root, plan_path, returned)
    report = load_run_report(root, Path(result["artifacts"]["report"]))
    assert report["experiment"]["comparison"]["winner_id"] is None
    assert report["experiment"]["code_review"]["evaluation_cost_usd"] is None
