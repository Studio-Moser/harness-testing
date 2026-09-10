import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness_testing.External_Codex import (
    external_evidence,
    preflight_external_codex,
    validate_external_request,
)
from harness_testing.Trial_Evidence import collect_trial_evidence, merge_external_evidence


def inventory():
    return [
        {
            "provider": "openai",
            "runtime_version": "0.150.1",
            "model": "child-model",
            "effort": "low",
        }
    ]


def fixture_binary(tmp_path):
    path = tmp_path / "Native_Codex.py"
    path.write_text("""#!/usr/bin/env python3
import json, os, sys, time
if sys.argv[1:] == ["--version"]:
    print("codex-cli 0.150.1")
    sys.exit(0)
assert "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    result = {}
    if method == "model/list":
        result = {"data": [{"model": "child-model",
            "supportedReasoningEfforts": [{"reasoningEffort": "low"}]}]}
    elif method == "thread/start":
        assert request["params"]["approvalPolicy"] == "never"
        assert request["params"]["sandbox"] == "read-only"
        result = {"thread": {"id": "external-root"}, "model": "child-model"}
    elif method == "turn/start":
        assert request["params"]["effort"] == "low"
        print(json.dumps({"method": "thread/tokenUsage/updated", "params": {
            "threadId": "external-root", "tokenUsage": {"total": {
                "inputTokens": 10, "cachedInputTokens": 2, "outputTokens": 5}}}}), flush=True)
        if request["params"].get("test_timeout"):
            time.sleep(10)
        print(json.dumps({"method": "turn/completed", "params": {
            "threadId": "external-root", "turn": {
                "id": "turn", "status": "completed"}}}), flush=True)
    if "id" in request:
        print(json.dumps({"id": request["id"], "result": result}), flush=True)
""")
    path.chmod(0o700)
    return path


def test_secondary_native_catalog_and_runtime_are_checked_without_turn(tmp_path):
    binary = fixture_binary(tmp_path)
    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": "not-for-codex"}
    preflight_external_codex(str(binary), inventory(), env)
    with pytest.raises(ValueError, match="runtime_version_mismatch"):
        preflight_external_codex(str(binary), [{**inventory()[0], "runtime_version": "wrong"}], env)
    with pytest.raises(ValueError, match="external_model_unavailable"):
        preflight_external_codex(str(binary), [{**inventory()[0], "model": "missing"}], env)


@pytest.mark.parametrize("timeout", [False, True])
def test_external_native_stdio_is_preserved_and_ephemeral_usage_retained(tmp_path, timeout):
    binary = fixture_binary(tmp_path)
    config = {
        "external_codex_binary": str(binary),
        "executor_inventory": inventory(),
        "log_dir": str(tmp_path),
    }
    settings = tmp_path / "Config.json"
    settings.write_text(json.dumps(config))
    (tmp_path / "Root_Identity.json").write_text(
        json.dumps(
            {
                "root_session_id": "claude-root",
                "deadline": time.monotonic() + (0.5 if timeout else 5),
            }
        )
    )
    requests = [
        {"id": 1, "method": "initialize", "params": {}},
        {
            "id": 2,
            "method": "thread/start",
            "params": {
                "model": "child-model",
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "ephemeral": True,
            },
        },
        {
            "id": 3,
            "method": "turn/start",
            "params": {
                "threadId": "external-root",
                "model": "child-model",
                "effort": "low",
                "test_timeout": timeout,
            },
        },
    ]
    process = subprocess.run(
        [sys.executable, "-m", "harness_testing.External_Codex", "app-server", "--stdio"],
        input="".join(json.dumps(row) + "\n" for row in requests),
        text=True,
        capture_output=True,
        timeout=8,
        env={
            **os.environ,
            "HARNESS_NATIVE_CONFIG": str(settings),
            "CLAUDE_CODE_OAUTH_TOKEN": "not-for-codex",
        },
    )
    assert process.returncode == (1 if timeout else 0), process.stderr
    observed = external_evidence(tmp_path)
    assert len(observed) == 1
    assert observed[0]["calls"][0]["input_tokens"] == 8
    assert observed[0]["calls"][0]["output_tokens"] == 5
    assert observed[0]["usage_complete"] is not timeout
    traces = [
        json.loads(line)
        for path in tmp_path.glob("executors/*/Trace.jsonl")
        for line in path.read_text().splitlines()
    ]
    assert [row["event"] for row in traces if row["direction"] == "request"] == requests
    parent = collect_trial_evidence(
        "claude",
        [
            {
                "type": "assistant",
                "session_id": "claude-root",
                "message": {
                    "id": "message",
                    "model": "root-model",
                    "usage": {"input_tokens": 20, "output_tokens": 4},
                },
            }
        ],
        root_session_id="claude-root",
        status="completed",
        duration_seconds=8,
    )
    merged = merge_external_evidence(parent, observed + observed)
    assert sum(row["output_tokens"] for row in merged["model_usage"]) == 9
    assert merged["duration_seconds"] == 8
    assert (
        next(row for row in merged["calls"] if row["session_id"] == "external-root")[
            "parent_session_id"
        ]
        == "claude-root"
    )
    assert (
        next(row for row in merged["sessions"] if row["session_id"] == "external-root")[
            "parent_session_id"
        ]
        == "claude-root"
    )


def test_unapproved_external_work_is_rejected_before_forwarding():
    with pytest.raises(ValueError, match="model_effort_not_approved"):
        validate_external_request(
            {"method": "turn/start", "params": {"model": "child-model", "effort": "high"}},
            inventory(),
        )
    with pytest.raises(ValueError, match="control_method_not_approved"):
        validate_external_request({"method": "account/login/start", "params": {}}, inventory())


def test_root_controller_stages_transparent_external_route_and_merges_usage(tmp_path, monkeypatch):
    import shutil

    import harness_testing.Native_Conversation as native

    secondary = fixture_binary(tmp_path)
    executables = tmp_path / "executables"
    executables.mkdir()
    (executables / "codex").symlink_to(secondary)
    monkeypatch.setenv("PATH", str(executables) + os.pathsep + os.environ["PATH"])
    controller_dir = tmp_path / "controller"
    controller_dir.mkdir()
    monkeypatch.setattr(native, "_REMOTE_DIR", str(controller_dir))
    for name in (
        "Native_Conversation.py",
        "External_Codex.py",
        "Trial_Evidence.py",
        "Scripted_User.py",
    ):
        shutil.copyfile(Path(native.__file__).with_name(name), controller_dir / name)
    primary = tmp_path / "Primary_Claude.py"
    primary.write_text("""import json, os, subprocess, sys
session = sys.argv[sys.argv.index("--session-id") + 1]
for line in sys.stdin:
    request = json.loads(line)
    if request.get("request", {}).get("subtype") == "initialize":
        print(json.dumps({"type": "control_response", "response": {"subtype": "success",
            "request_id": "initialize", "response": {"models": [{"value": "root-model"}]}}}),
            flush=True)
    elif request.get("type") == "user":
        rows = [
            {"id": 1, "method": "initialize", "params": {}},
            {"id": 2, "method": "thread/start", "params": {"model": "child-model",
                "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": True}},
            {"id": 3, "method": "turn/start", "params": {"threadId": "external-root",
                "model": "child-model", "effort": "low"}},
        ]
        output = subprocess.run([os.environ["HARNESS_CODEX_BIN"], "app-server", "--stdio"],
            input="".join(json.dumps(row)+"\\n" for row in rows), text=True, capture_output=True)
        assert output.returncode == 0, output.stderr
        assert "turn/completed" in output.stdout
        print(json.dumps({"type": "assistant", "session_id": session, "message": {
            "id": "m1", "model": "root-model", "usage": {
                "input_tokens": 20, "output_tokens": 4}}}), flush=True)
        print(json.dumps({"type": "result", "subtype": "success",
            "result": "Completed and verified."}), flush=True)
""")
    config = {
        "provider": "claude",
        "model": "root-model",
        "effort": "high",
        "instruction": "Do the task",
        "timeout_seconds": 8,
        "command": [sys.executable, str(primary)],
        "cwd": str(tmp_path),
        "log_dir": str(tmp_path / "logs"),
        "external_codex_home": str(tmp_path / "secondary-home"),
        "executor_inventory": inventory(),
        "policy": {"schema_version": "1", "interaction_limit": 3, "facts": {}, "rules": []},
    }
    evidence = native.run_controller(config)
    assert evidence["status"] == "completed", evidence
    assert evidence["usage_complete"]
    assert {row["provider"] for row in evidence["model_usage"]} == {"openai", "anthropic"}
    assert sum(row["output_tokens"] for row in evidence["model_usage"]) == 9
    assert evidence["child_count"] == 1
