import json
from pathlib import Path

from harness_testing import Contract_Criteria


def _result() -> dict[str, object]:
    return {
        "status": "accepted",
        "route": {
            "requested": "bulk",
            "actual_model": "test-model",
            "effort": "high",
            "provider": "test-provider",
            "executor": "test-executor",
            "resolution": "primary",
            "attempted": ["test-model@high"],
            "fallback_reason": None,
        },
        "artifacts": {"files": ["Output.json"], "report": None},
        "evidence": {
            "fixed_target": "fixture:test",
            "checks": ["Output.json structure: passed"],
            "outcome": "proven",
        },
        "telemetry": {
            "attempts": 1,
            "elapsed": None,
            "verification_failures": 0,
            "token_or_quota_usage": None,
        },
        "shelby": {"project_id": None, "run_id": None, "checkpoint_ids": []},
        "blockers": [],
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "Input.json").write_text('{"value":1}\n')
    (workspace / "Output.json").write_text('{"value":2}\n')
    (workspace / "Harness_Result.json").write_text(json.dumps(_result()))
    expected = tmp_path / "Expected.json"
    expected.write_text(
        json.dumps(
            {
                "result": _result(),
                "calls": [
                    {
                        "action": "dispatch",
                        "payload": {"route": "bulk"},
                    }
                ],
                "artifacts": {
                    "Output.json": {"json": {"value": 2}},
                },
            }
        )
    )
    manifest = tmp_path / "Protected_Files.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "files": {
                    "Input.json": (
                        "sha256:3a37782e8974c48eebf2a0517c866ad15641c53b3d319931"
                        "88796b56aeb79624"
                    )
                },
                "mutable_files": {},
            }
        )
    )
    events = tmp_path / "Events.jsonl"
    events.write_text(
        json.dumps(
            {
                "sequence": 1,
                "action": "dispatch",
                "payload": {"route": "bulk"},
                "matched": True,
            }
        )
        + "\n"
    )
    return workspace, expected, manifest


def test_contract_result_requires_the_exact_complete_public_shape(tmp_path):
    workspace, expected, manifest = _fixture(tmp_path)

    assert Contract_Criteria.result_matches_contract(workspace, expected, manifest)

    result_path = workspace / "Harness_Result.json"
    result = json.loads(result_path.read_text())
    del result["route"]["attempted"]
    result_path.write_text(json.dumps(result))

    assert not Contract_Criteria.result_matches_contract(workspace, expected, manifest)


def test_contract_workflow_requires_exact_protected_sidecar_calls(tmp_path):
    workspace, expected, _ = _fixture(tmp_path)
    events = tmp_path / "Events.jsonl"
    events.write_text(
        json.dumps(
            {
                "sequence": 1,
                "action": "dispatch",
                "payload": {"route": "bulk"},
                "matched": True,
            }
        )
        + "\n"
    )

    assert Contract_Criteria.stub_calls_match(expected, events)

    events.write_text(
        events.read_text()
        + json.dumps(
            {
                "sequence": 2,
                "action": "install",
                "payload": {},
                "matched": False,
            }
        )
        + "\n"
    )

    assert not Contract_Criteria.stub_calls_match(expected, events)


def test_contract_efficiency_rejects_unrequested_development_lifecycle(
    tmp_path, monkeypatch
):
    trajectory = tmp_path / "Trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    trajectory.write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "tool_calls": [
                            {
                                "function_name": "shell",
                                "arguments": {"cmd": "harness-stub dispatch '{} '"},
                            }
                        ]
                    }
                ]
            }
        )
    )

    assert Contract_Criteria.no_unrequested_lifecycle()

    trajectory.write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "tool_calls": [
                            {
                                "function_name": "shell",
                                "arguments": {"cmd": "git commit -am benchmark"},
                            }
                        ]
                    }
                ]
            }
        )
    )

    assert not Contract_Criteria.no_unrequested_lifecycle()
