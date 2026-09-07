import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def test_comparison_patch_is_portable_and_freezes_base_files(tmp_path):
    from harness_testing.Code_Reviews import _comparison_patch

    source = tmp_path / "original"
    final = tmp_path / "private-harness-label"
    source.mkdir()
    final.mkdir()
    (source / "App.ts").write_text("old\n")
    (final / "App.ts").write_text("new\n")
    (final / "AGENTS.md").write_text("Private harness instructions")
    patch, base_files = _comparison_patch(source, final)
    assert str(tmp_path).encode() not in patch
    assert b"private-harness-label" not in patch
    assert b"AGENTS.md" not in patch
    assert "App.ts" in base_files
    subprocess.run(["git", "apply", "-"], input=patch, cwd=source, check=True)
    assert (source / "App.ts").read_text() == "new\n"


def test_comparison_patch_accepts_noop_and_rejects_symlink_escape(tmp_path):
    from harness_testing.Code_Reviews import _comparison_patch

    source, final = tmp_path / "a", tmp_path / "b"
    source.mkdir()
    final.mkdir()
    (source / "App.ts").write_text("same\n")
    (final / "App.ts").write_text("same\n")
    patch, _ = _comparison_patch(source, final)
    assert patch == b""
    (final / "escape").symlink_to(tmp_path / "a", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        _comparison_patch(source, final)


def test_prepare_rejects_a_report_without_a_completed_experiment_trial(tmp_path: Path):
    from harness_testing.Code_Reviews import prepare_review

    report = {
        "schema_version": "3",
        "report_id": "sha256:" + "a" * 64,
        "experiment": {"trials": [{"status": "pending"}]},
    }
    report_path = tmp_path / "Run_Report.json"
    report_path.write_text(json.dumps(report))

    with pytest.raises(ValueError, match="completed"):
        prepare_review(ROOT, report_path, ROOT / "policy" / "Code Review Protocol.json")


def test_review_cli_forwards_prepare_paths(monkeypatch, capsys, tmp_path: Path):
    from harness_testing.CLI import main

    calls = []
    monkeypatch.setattr(
        "harness_testing.Code_Reviews.prepare_review",
        lambda root, report, protocol: (
            calls.append((root, report, protocol)) or {"status": "accepted"}
        ),
    )

    assert (
        main(["review", "prepare", "--report", "Report.json", "--protocol", "Protocol.json"]) == 0
    )

    assert calls == [(ROOT, Path("Report.json"), Path("Protocol.json"))]
    assert json.loads(capsys.readouterr().out) == {"status": "accepted"}


def test_record_rejects_stale_packet_before_retaining_private_evidence(monkeypatch, tmp_path: Path):
    from harness_testing.Code_Reviews import record_review

    plan_directory = tmp_path / "runs" / "reviews" / "plan"
    plan_directory.mkdir(parents=True)
    from harness_testing.Experiment_Reports import _price_usage

    plan = {
        "pricing_digest": _price_usage(ROOT, [])[1],
        "plan_id": "sha256:" + "a" * 64,
        "protocol": {
            "protocol_id": "sha256:" + "b" * 64,
            "categories": ["correctness"],
            "time_budget_seconds": 60,
        },
        "conditions": {
            "provider": "codex",
            "model": "gpt-6-astra",
            "effort": "high",
            "executor": "native",
            "runtime_version": "0.153.4",
        },
        "packets": [
            {
                "packet_id": "review-0123456789abcdef01234567",
                "trial_id": "trial",
                "target_digest": "sha256:" + "c" * 64,
            }
        ],
    }
    results = {
        "schema_version": "1",
        "plan_id": plan["plan_id"],
        "protocol_id": plan["protocol"]["protocol_id"],
        "recorded_at": "2026-09-06T00:00:00Z",
        "conditions": plan["conditions"],
        "packets": [
            {
                "packet_id": "review-0123456789abcdef01234567",
                "target_digest": "sha256:" + "d" * 64,
                "conditions": plan["conditions"],
                "status": "incomplete",
                "session_id": "fresh",
                "fresh_session": True,
                "no_tested_harness": True,
                "usage_complete": False,
                "model_usage": [],
                "findings": [],
                "internal_review": {"status": "unknown"},
            }
        ],
    }
    results_path = tmp_path / "Results.json"
    results_path.write_text(json.dumps(results))
    monkeypatch.setattr(
        "harness_testing.Code_Reviews._verify_plan", lambda root, path: (plan, plan_directory)
    )
    monkeypatch.setattr(
        "harness_testing.Code_Reviews._verify_frozen_inputs",
        lambda root, plan, directory: (
            {"report_id": "sha256:" + "e" * 64, "experiment": {"trials": []}},
            tmp_path / "Run_Report.json",
        ),
    )

    with pytest.raises(ValueError, match="target"):
        record_review(ROOT, plan_directory / "Plan.json", results_path)

    assert not (plan_directory / "Imported Results.json").exists()
    assert not (plan_directory / "Evidence").exists()


def test_review_cli_refreshes_dashboard_after_record(monkeypatch, capsys):
    from harness_testing.CLI import main

    calls = []
    monkeypatch.setattr(
        "harness_testing.Code_Reviews.record_review",
        lambda *args: calls.append("record") or {"status": "accepted"},
    )
    monkeypatch.setattr(
        "harness_testing.Run_Reports.refresh_local_dashboard", lambda root: calls.append("refresh")
    )
    assert main(["review", "record", "--plan", "Plan.json", "--results", "Results.json"]) == 0
    assert calls == ["record", "refresh"]
    assert json.loads(capsys.readouterr().out)["status"] == "accepted"


def test_review_cli_forwards_explicit_references(monkeypatch, capsys):
    from harness_testing.CLI import main

    calls = []
    monkeypatch.setattr(
        "harness_testing.Code_Reviews.prepare_review",
        lambda *args, **kwargs: calls.append(kwargs) or {"status": "accepted"},
    )
    assert (
        main(
            [
                "review",
                "prepare",
                "--report",
                "Report.json",
                "--protocol",
                "Protocol.json",
                "--references",
                "References.json",
            ]
        )
        == 0
    )
    assert calls == [{"references_path": Path("References.json")}]


def test_later_global_attempt_resolves_its_own_single_trial_job():
    from harness_testing.Code_Reviews import _trial_job

    manifest = {
        "provenance": {
            "trial_schedule": [
                {"cell_index": 0, "task_id": "task", "attempt": 1},
                {"cell_index": 0, "task_id": "task", "attempt": 2},
            ]
        },
        "cells": [{"contender": {"id": "contender"}}],
        "harbor_config_paths": ["Harbor/r1.json", "Harbor/r2.json"],
    }
    assert _trial_job(
        manifest, {"task_id": "task", "contender_id": "contender", "attempt": 2}
    ) == Path("Harbor/r2.json")
