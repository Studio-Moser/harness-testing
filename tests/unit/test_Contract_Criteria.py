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
                "evidence_requirements": ["Output.json structure: passed"],
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


def test_contract_result_accepts_equivalent_proof_wording_and_telemetry(tmp_path):
    workspace, expected, manifest = _fixture(tmp_path)

    result_path = workspace / "Harness_Result.json"
    result = json.loads(result_path.read_text())
    result["evidence"]["checks"] = [
        "Output.json structure: passed; behavior independently verified"
    ]
    result["telemetry"]["elapsed"] = "1.2s"
    result["telemetry"]["token_or_quota_usage"] = "reported by provider"
    result_path.write_text(json.dumps(result))

    assert Contract_Criteria.result_matches_contract(workspace, expected, manifest)


def test_contract_result_rejects_a_false_attempt_history(tmp_path):
    workspace, expected, manifest = _fixture(tmp_path)

    result_path = workspace / "Harness_Result.json"
    result = json.loads(result_path.read_text())
    result["route"]["attempted"] = ["made-a-dispatch@high"]
    result_path.write_text(json.dumps(result))

    assert not Contract_Criteria.result_matches_contract(workspace, expected, manifest)


def test_contract_result_requires_nonblank_task_relevant_evidence(tmp_path):
    workspace, expected, manifest = _fixture(tmp_path)
    result_path = workspace / "Harness_Result.json"

    for checks in (
        [""],
        ["Everything is fine"],
        ["Output.json structure is not passed"],
    ):
        result = json.loads(result_path.read_text())
        result["evidence"]["checks"] = checks
        result_path.write_text(json.dumps(result))
        assert not Contract_Criteria.result_matches_contract(
            workspace, expected, manifest
        )


def test_contract_result_rejects_the_wrong_semantic_route(tmp_path):
    workspace, expected, manifest = _fixture(tmp_path)

    result_path = workspace / "Harness_Result.json"
    result = json.loads(result_path.read_text())
    result["route"]["requested"] = "quick"
    result_path.write_text(json.dumps(result))

    assert not Contract_Criteria.result_matches_contract(workspace, expected, manifest)


def test_contract_result_requires_the_complete_public_shape(tmp_path):
    workspace, expected, manifest = _fixture(tmp_path)

    result_path = workspace / "Harness_Result.json"
    result = json.loads(result_path.read_text())
    del result["route"]["attempted"]
    result_path.write_text(json.dumps(result))

    assert not Contract_Criteria.result_matches_contract(workspace, expected, manifest)


def test_contract_diagnostics_distinguish_json_schema_semantics_and_artifacts(tmp_path):
    workspace, expected, manifest = _fixture(tmp_path)
    result_path = workspace / "Harness_Result.json"
    result_path.write_text("{")
    assert Contract_Criteria.result_contract_diagnostics(
        workspace, expected, manifest
    ) == ("result-json:/Harness_Result.json:malformed",)

    result = _result()
    result["route"]["actual_model"] = ""
    result_path.write_text(json.dumps(result))
    assert any(
        item == "result-schema:/route/actual_model:anyOf"
        for item in Contract_Criteria.result_contract_diagnostics(
            workspace, expected, manifest
        )
    )

    result = _result()
    result["route"]["requested"] = "quick"
    result_path.write_text(json.dumps(result))
    assert any(
        item == "result-semantics:/route/requested:mismatch"
        for item in Contract_Criteria.result_contract_diagnostics(
            workspace, expected, manifest
        )
    )

    (workspace / "Output.json").write_text('{"value":3}\n')
    result_path.write_text(json.dumps(_result()))
    assert any(
        item == "artifact:/Output.json:mismatch"
        for item in Contract_Criteria.result_contract_diagnostics(
            workspace, expected, manifest
        )
    )


def test_contract_diagnostics_are_bounded_to_twelve_entries(tmp_path):
    workspace, expected, manifest = _fixture(tmp_path)
    result = _result()
    result.update({"status": "invalid", "blockers": [""]})
    result["route"].update(
        {
            "requested": "invalid",
            "actual_model": "",
            "effort": "",
            "provider": "",
            "executor": "",
            "resolution": "invalid",
            "attempted": [""],
            "fallback_reason": "",
        }
    )
    result["artifacts"].update({"files": [""], "report": ""})
    result["evidence"].update(
        {"fixed_target": "", "checks": [""], "outcome": "invalid"}
    )
    result["telemetry"].update(
        {
            "attempts": -1,
            "elapsed": "",
            "verification_failures": -1,
            "token_or_quota_usage": "",
        }
    )
    result["shelby"].update(
        {"project_id": "", "run_id": "", "checkpoint_ids": [""]}
    )
    (workspace / "Harness_Result.json").write_text(json.dumps(result))

    assert (
        len(
            Contract_Criteria.result_contract_diagnostics(
                workspace, expected, manifest
            )
        )
        == 12
    )


def test_contract_result_prints_only_local_diagnostics(tmp_path, capsys):
    workspace, expected, manifest = _fixture(tmp_path)
    result = _result()
    result["route"]["requested"] = "quick"
    (workspace / "Harness_Result.json").write_text(json.dumps(result))

    assert not Contract_Criteria.result_matches_contract(workspace, expected, manifest)
    diagnostics = Contract_Criteria.result_contract_diagnostics(
        workspace, expected, manifest
    )
    assert capsys.readouterr().out.splitlines() == [
        f"harness-contract: {diagnostic}" for diagnostic in diagnostics
    ]


def test_contract_workflow_allows_extra_attempts_but_efficiency_rejects_them(tmp_path):
    workspace, expected, _ = _fixture(tmp_path)
    events = tmp_path / "Events.jsonl"
    events.write_text(
        json.dumps(
            {
                "sequence": 1,
                "action": "dispatch",
                "payload": {"route": "quick"},
                "matched": False,
                "expected_sequence": None,
            }
        )
        + "\n"
        + json.dumps(
            {
                "sequence": 2,
                "action": "dispatch",
                "payload": {"route": "bulk"},
                "matched": True,
                "expected_sequence": 1,
            }
        )
        + "\n"
    )

    assert Contract_Criteria.stub_calls_match(expected, events)
    assert not Contract_Criteria.stub_calls_are_bounded(expected, events)


def test_contract_efficiency_accepts_one_match_per_required_call(tmp_path):
    workspace, expected, _ = _fixture(tmp_path)
    events = tmp_path / "Events.jsonl"
    events.write_text(
        json.dumps(
            {
                "sequence": 1,
                "action": "dispatch",
                "payload": {"route": "bulk"},
                "matched": True,
                "expected_sequence": 1,
            }
        )
        + "\n"
    )

    assert Contract_Criteria.stub_calls_are_bounded(expected, events)


def test_contract_efficiency_does_not_penalize_an_omitted_workflow_call(tmp_path):
    workspace, expected, _ = _fixture(tmp_path)
    events = tmp_path / "Events.jsonl"
    events.write_text("")

    assert Contract_Criteria.stub_calls_are_bounded(expected, events)


def test_contract_scores_protected_tools_that_do_not_emit_expected_sequence(tmp_path):
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
    assert Contract_Criteria.stub_calls_are_bounded(expected, events)


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
