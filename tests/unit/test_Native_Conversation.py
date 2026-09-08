import pytest

from harness_testing.Native_Conversation import Conversation
from harness_testing.Scripted_User import terminal_approval_request


def config(provider):
    return {
        "provider": provider,
        "model": "root-model",
        "effort": "high",
        "instruction": "Do the task",
        "timeout_seconds": 5,
        "policy": {
            "schema_version": "1",
            "interaction_limit": 4,
            "facts": {"go": "Proceed"},
            "rules": [
                {"id": "go", "kind": "approval", "pattern": "Ready to proceed\\?", "fact": "go"}
            ],
        },
    }


def test_codex_turns_always_address_explicit_root_after_child():
    state = Conversation(config("codex"))
    state.root = "root"
    state.identities["root"] = {"model": "root-model", "effort": "high"}
    state.handle(
        {
            "method": "thread/started",
            "params": {"thread": {"id": "later-child", "parentThreadId": "root"}},
        }
    )
    state.handle(
        {
            "method": "item/completed",
            "params": {
                "threadId": "root",
                "item": {"type": "agentMessage", "text": "Ready to proceed?"},
            },
        }
    )
    outbound = state.handle(
        {
            "method": "turn/completed",
            "params": {"threadId": "root", "turn": {"id": "first", "status": "completed"}},
        }
    )
    assert outbound[0]["method"] == "turn/start"
    assert outbound[0]["params"]["threadId"] == "root"
    assert outbound[0]["params"]["model"] == "root-model"
    assert outbound[0]["params"]["effort"] == "high"
    assert outbound[0]["params"]["input"][0]["text"] == "Proceed"


def test_native_pending_requests_keep_request_identity_and_claude_original_input():
    state = Conversation(config("claude"))
    request = {
        "type": "control_request",
        "request_id": "request-9",
        "request": {
            "subtype": "can_use_tool",
            "tool_name": "AskUserQuestion",
            "input": {
                "questions": [
                    {
                        "question": "Ready to proceed?",
                        "options": [{"label": "Proceed", "description": "go"}],
                    }
                ],
                "metadata": {"keep": True},
            },
        },
    }
    reply = state.handle(request)[0]
    assert reply["response"]["request_id"] == "request-9"
    updated = reply["response"]["response"]["updatedInput"]
    assert updated["metadata"] == {"keep": True}
    assert updated["answers"] == {"Ready to proceed?": "Proceed"}
    state = Conversation(config("codex"))
    reply = state.handle(
        {
            "id": "server-9",
            "method": "item/tool/requestUserInput",
            "params": {
                "threadId": "child",
                "questions": [{"id": "q1", "question": "Ready to proceed?"}],
            },
        }
    )[0]
    assert reply == {"id": "server-9", "result": {"answers": {"q1": {"answers": ["Proceed"]}}}}


def test_unknown_question_and_tool_permission_fail_closed():
    state = Conversation(config("codex"))
    state.handle(
        {
            "id": 1,
            "method": "item/tool/requestUserInput",
            "params": {"questions": [{"id": "q", "question": "What is an unauthored fact?"}]},
        }
    )
    assert state.status == "task_definition_gap"
    state = Conversation(config("claude"))
    reply = state.handle(
        {
            "type": "control_request",
            "request_id": "permission",
            "request": {
                "subtype": "can_use_tool",
                "tool_name": "Bash",
                "input": {"command": "publish"},
            },
        }
    )
    assert reply[0]["response"]["response"]["behavior"] == "deny"


@pytest.mark.parametrize(
    ("text", "interactions", "reason"),
    [
        ("Approve this design and I\u2019ll implement it.", 0, "task_definition_gap"),
        ("Please approve this deployment.", 0, "authority_denied"),
        ("Please confirm the result.", 0, "task_definition_gap"),
        ("Please approve this plan.", 4, "interaction_limit"),
        ("Please approve this deployment.", 4, "interaction_limit"),
        ("Implemented the approved plan.", 0, None),
    ],
)
def test_terminal_approval_requests_keep_report_status_and_reason(text, interactions, reason):
    state = Conversation(config("codex"))
    state.text = text
    state.interactions = interactions

    assert state.finish_turn() == []
    assert state.status == ("completed" if reason is None else "task_definition_gap")
    assert state.reason == reason


@pytest.mark.parametrize(
    "text",
    [
        "Design:\n\nPlease confirm this design and I\u2019ll implement it.",
        "I will update the source value, then run the checks.\n\nApprove this approach?",
        "Plan:\n\nPlease approve this plan so I can proceed.",
        "Design:\n\nPlease confirm this design and I\u2019ll continue.",
        "Please approve this plan so I can branch and implement.",
        "Please approve this plan so I can update src/lib.rs.",
        "Please approve this plan before I release v1.2.",
    ],
)
def test_frozen_routine_approval_continues_the_native_root(text):
    import json
    from pathlib import Path

    task = "react-saved-view-feature"
    policy_path = Path(__file__).parents[2] / "tasks/workflow" / task / "Scripted User.json"
    state = Conversation({**config("codex"), "policy": json.loads(policy_path.read_text())})
    state.root = "root"
    state.text = text

    outbound = state.finish_turn()

    assert outbound[0]["method"] == "turn/start"
    assert outbound[0]["params"]["threadId"] == "root"
    assert outbound[0]["params"]["input"][0]["text"].startswith("Proceed with the original")


@pytest.mark.parametrize(
    "text",
    [
        "I will update the source value, then run the checks.\n\nApprove this approach?",
        "Plan:\n\nPlease approve this plan so I can proceed.",
        "Design:\n\nPlease confirm this design and I\u2019ll continue.",
        "Please approve this plan so I can branch and implement.",
        "Please approve this plan so I can update src/lib.rs.",
        "Please approve this plan before I release v1.2.",
    ],
)
def test_terminal_routine_approval_is_a_routine_request(text):
    assert terminal_approval_request(text) == "routine"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Implemented the approved plan.", None),
        ("I no longer need you to approve this plan.", None),
        ("Please approve this plan so I can deploy.", "external"),
        ("Please approve this approach and publish it.", "external"),
        ("Please approve this plan for publication.", "external"),
        ("Please approve this plan so I can upload logs.", "external"),
        ("Please approve this plan for sending credentials.", "external"),
        ("Please approve this plan with additional permissions.", "external"),
        ("Please approve this plan with broader authority.", "external"),
        ("Please approve this plan outside the original scope.", "external"),
        ("Please approve this plan? Implemented it; all tests passed.", None),
    ],
)
def test_terminal_approval_rejects_completed_and_broader_authority(text, expected):
    assert terminal_approval_request(text) == expected


def test_expanded_authority_approval_stays_blocked_without_an_interaction():
    import json
    from pathlib import Path

    policy_path = (
        Path(__file__).parents[2]
        / "tasks/workflow/react-saved-view-feature/Scripted User.json"
    )
    state = Conversation({**config("codex"), "policy": json.loads(policy_path.read_text())})
    state.root = "root"
    state.text = "Please approve this plan with additional permissions."

    assert state.finish_turn() == []
    assert state.status == "task_definition_gap"
    assert state.reason == "authority_denied"
    assert state.interactions == 0


def test_initialization_is_before_first_model_request():
    state = Conversation(config("codex"))
    first = state.start()
    assert first[0]["method"] == "initialize"
    assert not any(item.get("method") == "turn/start" for item in first)
    state = Conversation(config("claude"))
    first = state.start()
    assert first[0]["request"]["subtype"] == "initialize"
    assert first[0]["type"] == "control_request"


@pytest.mark.parametrize("value", [True, -1, 1.0, float("nan"), "600", [], {}])
def test_provider_recovery_allowance_rejects_invalid_shapes(value):
    from harness_testing.Native_Conversation import validate_conversation

    with pytest.raises(ValueError, match="native_provider_recovery_invalid"):
        validate_conversation({**config("codex"), "provider_recovery_seconds": value}, "codex")


def test_provider_recovery_allowance_is_codex_only():
    from harness_testing.Native_Conversation import validate_conversation

    with pytest.raises(ValueError, match="native_provider_recovery_unsupported"):
        validate_conversation({**config("claude"), "provider_recovery_seconds": 1}, "claude")


def test_codex_transport_error_uses_one_recovery_allowance_across_children(tmp_path):
    import sys

    from harness_testing.Native_Conversation import run_controller

    server = tmp_path / "Recovery_Server.py"
    server.write_text("""import json, sys, time
mode = sys.argv[1]
emit = lambda event: print(json.dumps(event), flush=True)
def transport(thread_id, turn_id):
    emit({
        "method": "error",
        "params": {
            "threadId": thread_id,
            "turnId": turn_id,
            "willRetry": True,
            "error": {
                "codexErrorInfo": {
                    "responseStreamDisconnected": {"httpStatusCode": None}
                }
            },
        },
    })
def completed(thread_id, turn_id):
    emit({
        "method": "turn/completed",
        "params": {
            "threadId": thread_id,
            "turn": {"id": turn_id, "status": "completed"},
        },
    })
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "model/list":
        result = {
            "data": [
                {
                    "model": "root-model",
                    "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
                }
            ]
        }
    elif method == "thread/start":
        result = {
            "thread": {"id": "root"},
            "model": "root-model",
            "reasoningEffort": "high",
        }
    else:
        result = {}
    if method == "turn/start":
        emit({
            "method": "turn/started",
            "params": {"threadId": "root", "turn": {"id": "root-turn"}},
        })
        emit({
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "root",
                "turnId": "root-turn",
                "tokenUsage": {"total": {"inputTokens": 3, "outputTokens": 2}},
            },
        })
        if mode in {"child", "repeat"}:
            emit({
                "method": "turn/started",
                "params": {"threadId": "child", "turn": {"id": "child-turn"}},
            })
            thread_id, turn_id = "child", "child-turn"
        else:
            thread_id, turn_id = "root", "root-turn"
        if mode != "no-error":
            transport(thread_id, turn_id)
        if mode == "repeat":
            time.sleep(0.05)
            transport("child", "child-turn")
            time.sleep(1.4)
        else:
            time.sleep(0.45 if mode in {"recovered", "child"} else 0.8)
        emit({
            "method": "item/completed",
            "params": {
                "threadId": "root",
                "item": {"type": "agentMessage", "text": "Implemented."},
            },
        })
        completed("root", "root-turn")
        if mode == "child":
            completed("child", "child-turn")
    if "id" in request:
        emit({"id": request["id"], "result": result})
""")

    def run(mode, *, recovery=0):
        return run_controller(
            {
                **config("codex"),
                "command": [sys.executable, str(server), mode],
                "cwd": str(tmp_path),
                "log_dir": str(tmp_path / mode),
                "timeout_seconds": 0.25,
                "provider_recovery_seconds": recovery,
            }
        )

    recovered = run("recovered", recovery=1)
    assert recovered["status"] == "completed"
    assert recovered["provider_recovery"] == {
        "allowance_seconds": 1,
        "transport_error_count": 1,
        "extension_applied": True,
    }

    child = run("child", recovery=1)
    assert child["status"] == "completed"
    assert child["provider_recovery"]["transport_error_count"] == 1
    assert child["provider_recovery"]["extension_applied"] is True

    repeated = run("repeat", recovery=1)
    assert repeated["status"] == "infrastructure_failure"
    assert repeated["terminal_reason"] == "provider_transport_interrupted"
    assert repeated["provider_recovery"]["transport_error_count"] == 2
    assert repeated["provider_recovery"]["extension_applied"] is True

    unchanged = run("no-error")
    assert unchanged["status"] == "timeout"
    assert unchanged["provider_recovery"] == {
        "allowance_seconds": 0,
        "transport_error_count": 0,
        "extension_applied": False,
    }

    expired = run("recovered", recovery=0)
    assert expired["status"] == "infrastructure_failure"
    assert expired["terminal_reason"] == "provider_transport_interrupted"
    assert expired["usage_complete"] is False


def test_codex_transport_error_requires_active_typed_provider_event():
    settings = {**config("codex"), "provider_recovery_seconds": 1}
    state = Conversation(settings)
    state.root = "root"
    state.active_turns["root"] = "turn"
    state.handle(
        {
            "method": "error",
            "params": {
                "threadId": "root",
                "turnId": "turn",
                "willRetry": False,
                "error": {
                    "codexErrorInfo": {
                        "responseStreamDisconnected": {"httpStatusCode": None}
                    }
                },
            },
        }
    )
    assert state.status == "infrastructure_failure"
    assert state.reason == "provider_transport_interrupted"
    assert state.transport_error_count == 1

    state = Conversation(settings)
    state.root = "root"
    state.active_turns["root"] = "turn"
    state.handle(
        {
            "method": "error",
            "params": {
                "threadId": "root",
                "turnId": "turn",
                "willRetry": True,
                "error": {
                    "codexErrorInfo": {
                        "responseStreamDisconnected": {"httpStatusCode": 401}
                    }
                },
            },
        }
    )
    assert state.status == "pending"
    assert state.transport_error_count == 0
    assert state.provider_recovery_applied is False

    for retry in (None, "true", 1):
        state = Conversation(settings)
        state.root = "root"
        state.active_turns["root"] = "turn"
        state.handle(
            {
                "method": "error",
                "params": {
                    "threadId": "root",
                    "turnId": "turn",
                    "willRetry": retry,
                    "error": {
                        "codexErrorInfo": {
                            "responseStreamDisconnected": {"httpStatusCode": None}
                        }
                    },
                },
            }
        )
        assert state.status == "pending"
        assert state.transport_error_count == 0
        assert state.provider_recovery_applied is False

    state = Conversation(settings)
    state.root = "root"
    state.active_turns["root"] = "turn"
    state.handle(
        {
            "method": "error",
            "params": {
                "threadId": "root",
                "turnId": "turn",
                "willRetry": True,
                "error": {
                    "codexErrorInfo": {
                        "responseStreamDisconnected": {
                            "httpStatusCode": None,
                            "unexpected": "value",
                        }
                    }
                },
            },
        }
    )
    assert state.status == "pending"
    assert state.transport_error_count == 0
    assert state.provider_recovery_applied is False

    state = Conversation(settings)
    state.root = "root"
    state.active_turns["child"] = "turn"
    state.handle(
        {
            "method": "turn/completed",
            "params": {
                "threadId": "child",
                "turn": {
                    "id": "turn",
                    "status": "failed",
                    "error": {
                        "codexErrorInfo": {
                            "responseTooManyFailedAttempts": {"httpStatusCode": None}
                        }
                    },
                },
            },
        }
    )
    assert state.status == "infrastructure_failure"
    assert state.reason == "provider_transport_interrupted"
    assert state.transport_error_count == 1


def test_controller_runs_two_native_wire_turns_and_preserves_timeout_usage(tmp_path):
    import json
    import sys

    from harness_testing.Native_Conversation import run_controller

    server = tmp_path / "Fixture_Server.py"
    server.write_text("""import json, sys, time
turn = 0
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    result = {}
    if method == "model/list":
        result = {"data": [{"model": "root-model",
                            "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}]}
    elif method == "thread/start":
        result = {"thread": {"id": "root"}, "model": "root-model", "reasoningEffort": "high"}
    elif method == "turn/start":
        assert request["params"]["threadId"] == "root"
        turn += 1
        print(json.dumps({"method": "turn/started", "params": {
            "threadId": "root", "turn": {"id": str(turn)}}}), flush=True)
        print(json.dumps({"method": "thread/tokenUsage/updated", "params": {
            "threadId": "root", "turnId": str(turn), "tokenUsage": {
                "total": {"inputTokens": turn*10, "outputTokens": turn*2}}}}), flush=True)
        text = "Ready to proceed?" if turn == 1 else "Implemented and checked."
        print(json.dumps({"method": "item/completed", "params": {
            "threadId": "root", "item": {"type": "agentMessage", "text": text}}}), flush=True)
        if "timeout" in sys.argv and turn == 2:
            time.sleep(10)
        print(json.dumps({"method": "turn/completed", "params": {
            "threadId": "root", "turn": {"id": str(turn), "status": "completed"}}}), flush=True)
    if "id" in request:
        print(json.dumps({"id": request["id"], "result": result}), flush=True)
""")
    for timeout in (False, True):
        logs = tmp_path / str(timeout)
        settings = {
            **config("codex"),
            "command": [sys.executable, str(server)] + (["timeout"] if timeout else []),
            "cwd": str(tmp_path),
            "log_dir": str(logs),
            "timeout_seconds": 0.4 if timeout else 5,
        }
        evidence = run_controller(settings)
        assert evidence["status"] == ("timeout" if timeout else "completed")
        assert sum(row["output_tokens"] for row in evidence["model_usage"]) == 4
        assert evidence["usage_complete"] is not timeout
        requests = [
            json.loads(line) for line in (logs / "Native_Requests.jsonl").read_text().splitlines()
        ]
        turns = [request for request in requests if request.get("method") == "turn/start"]
        assert len(turns) == 2
        assert turns[1]["params"]["threadId"] == "root"
        assert (logs / "codex.txt").read_text()
        assert (
            json.loads((logs / "Trial_Evidence.json").read_text())["status"] == evidence["status"]
        )


def test_committed_artifact_patch_excludes_uncommitted_work(tmp_path):
    import subprocess

    from harness_testing.Native_Conversation import capture_committed_patch

    subprocess.run(("git", "init", "--quiet", tmp_path), check=True)
    subprocess.run(("git", "-C", tmp_path, "config", "user.name", "Harness Test"), check=True)
    subprocess.run(
        ("git", "-C", tmp_path, "config", "user.email", "harness@example.invalid"),
        check=True,
    )
    tracked = tmp_path / "Tracked.txt"
    tracked.write_text("base\n")
    subprocess.run(("git", "-C", tmp_path, "add", "Tracked.txt"), check=True)
    subprocess.run(("git", "-C", tmp_path, "commit", "--quiet", "-m", "base"), check=True)
    base = subprocess.run(
        ("git", "-C", tmp_path, "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked.write_text("committed\n")
    subprocess.run(("git", "-C", tmp_path, "commit", "-am", "submitted", "--quiet"), check=True)
    (tmp_path / "Uncommitted.txt").write_text("excluded\n")
    patch = tmp_path / "logs" / "artifacts" / "model.patch"

    capture_committed_patch(tmp_path, base, patch)

    contents = patch.read_text()
    assert "Tracked.txt" in contents
    assert "Uncommitted.txt" not in contents


def test_models_are_checked_before_turn_and_explicit_resume_is_preserved():
    state = Conversation({**config("codex"), "root_session_id": "saved-root"})
    init = state.start()[0]
    model_request = state.handle({"id": init["id"], "result": {}})[1]
    request = state.handle(
        {"id": model_request["id"], "result": {"data": [{"model": "root-model"}]}}
    )[0]
    assert request["method"] == "thread/resume"
    assert request["params"]["threadId"] == "saved-root"
    assert "path" not in request["params"]
    assert "history" not in request["params"]
    assert state.handle({"id": request["id"], "result": {"thread": {"id": "wrong"}}}) == []
    assert state.reason == "root_session_identity_mismatch"


def test_frozen_hook_trust_matches_exact_source_command_and_rechecks_hash(tmp_path, monkeypatch):
    import hashlib
    import json
    from pathlib import Path

    import pytest

    from harness_testing.Native_Conversation import approved_hooks_from_bundle, hook_trust_edits

    relative = "codex/provider-home/plugins/cache/experiment-pm/pm/1.0"
    plugin = tmp_path / relative
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / "hooks").mkdir()
    contents = {
        ".codex-plugin/plugin.json": json.dumps({"name": "pm"}),
        "hooks/hooks.json": json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "${CLAUDE_PLUGIN_ROOT}"
                                    "/scripts/check-prereqs.sh local",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
    }
    for name, data in contents.items():
        (plugin / name).write_text(data)
    digests = {
        f"{relative}/{name}": "sha256:" + hashlib.sha256(data.encode()).hexdigest()
        for name, data in contents.items()
    }
    (tmp_path / "Provenance.json").write_text(
        json.dumps(
            {
                "delivery_surfaces": [
                    {"surface": "codex-plugin", "path": "/harness-arm/" + relative}
                ],
                "generated_file_digests": digests,
            }
        )
    )
    approved = approved_hooks_from_bundle(tmp_path)
    assert len(approved) == 1
    original_read = Path.read_bytes
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda path: (
            original_read(tmp_path / path.relative_to("/harness-arm"))
            if path.is_relative_to("/harness-arm")
            else original_read(path)
        ),
    )
    hook = {
        "key": "native.key",
        "currentHash": "native-hash",
        "source": "plugin",
        "sourcePath": "/tmp/codex-home/plugins/cache/experiment-pm/pm/1.0/hooks/hooks.json",
        "command": contents and "${CLAUDE_PLUGIN_ROOT}/scripts/check-prereqs.sh local",
        "eventName": "sessionStart",
        "matcher": None,
        "enabled": False,
        "trustStatus": "untrusted",
    }
    result = {"data": [{"hooks": [hook], "warnings": [], "errors": []}]}
    edits = hook_trust_edits(approved, result)
    assert edits == [
        {
            "keyPath": 'hooks.state."native.key"',
            "mergeStrategy": "replace",
            "value": {"enabled": True, "trusted_hash": "native-hash"},
        }
    ]
    hook.update(enabled=True, trustStatus="trusted")
    hook_trust_edits(approved, result, verify={"native.key": "native-hash"})
    hook["command"] = (
        "/tmp/codex-home/plugins/cache/experiment-pm/pm/1.0/scripts/check-prereqs.sh local"
    )
    hook_trust_edits(approved, result, verify={"native.key": "native-hash"})
    hook["command"] = (
        "/harness-arm/codex/provider-home/plugins/cache/experiment-pm/pm/1.0/"
        "scripts/check-prereqs.sh local"
    )
    with pytest.raises(ValueError, match="definition_mismatch"):
        hook_trust_edits(approved, result)
    hook["command"] = "different command"
    with pytest.raises(ValueError, match="definition_mismatch"):
        hook_trust_edits(approved, result)
    hook["source"] = "user"
    with pytest.raises(ValueError, match="definition_mismatch"):
        hook_trust_edits(approved, result)


def test_inventory_does_not_hide_kickoff_and_runtime_versions_must_match():
    import pytest

    from harness_testing.Native_Conversation import validate_conversation

    settings = {
        **config("codex"),
        "runtime_version": "0.150.1",
        "executor_inventory": [
            {
                "provider": "openai",
                "model": "child-model",
                "effort": "low",
                "runtime_version": "0.150.1",
            }
        ],
    }
    state = Conversation(settings)
    assert not state.check_models([{"model": "child-model"}])
    assert state.reason == "executor_model_unavailable:root-model"
    settings["executor_inventory"][0]["runtime_version"] = "wrong"
    with pytest.raises(ValueError, match="executor_runtime_version_mismatch"):
        validate_conversation(settings, "codex")


def test_claude_root_waits_for_background_native_terminal_notification():
    state = Conversation(config("claude"))
    state.root = "root"
    state.handle(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "agent",
                        "name": "Agent",
                        "input": {"run_in_background": True},
                    }
                ]
            },
        }
    )
    state.handle(
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "agent", "content": "launched"}]
            },
        }
    )
    state.handle({"type": "result", "subtype": "success", "result": "Completed."})
    assert state.status == "pending"
    state.handle(
        {"type": "system", "subtype": "task_started", "task_id": "child", "tool_use_id": "agent"}
    )
    state.handle(
        {
            "type": "system",
            "subtype": "task_updated",
            "task_id": "child",
            "patch": {"status": "completed"},
        }
    )
    assert state.status == "completed"


def test_native_child_effective_identity_enforces_frozen_pool():
    for model, effort, mismatch in [
        ("child-model", "low", False),
        ("other", "low", True),
        ("child-model", "high", True),
        ("child-model", None, False),
    ]:
        settings = config("codex")
        settings["executor_inventory"] = [
            {"provider": "openai", "model": "child-model", "effort": "low"}
        ]
        state = Conversation(settings)
        state.root = "root"
        event = {
            "method": "item/completed",
            "params": {
                "threadId": "root",
                "item": {
                    "type": "collabAgentToolCall",
                    "tool": "spawnAgent",
                    "receiverThreadIds": ["child"],
                    "model": model,
                    "reasoningEffort": effort,
                },
            },
        }
        assert state.handle(event) == []
        assert (state.reason == "executor_condition_mismatch") is mismatch
        assert state.identities["child"].get("effort") == effort

    settings = config("claude")
    settings["executor_inventory"] = [
        {"provider": "anthropic", "model": "child-model", "effort": "low"}
    ]
    state = Conversation(settings)
    state.root = "root"
    state.handle(
        {
            "type": "assistant",
            "session_id": "root",
            "parent_tool_use_id": "tool-child",
            "message": {"model": "unapproved", "content": []},
        }
    )
    assert state.reason == "executor_condition_mismatch"


def test_claude_controller_waits_for_background_terminal_or_times_out(tmp_path):
    import json
    import sys

    from harness_testing.Native_Conversation import run_controller

    server = tmp_path / "Background_Server.py"
    server.write_text("""import json,sys,time
emit=lambda event: print(json.dumps(event),flush=True)
for line in sys.stdin:
    request=json.loads(line)
    if request.get("type")=="control_request":
        emit({"type":"control_response","response":{"request_id":"initialize","subtype":"success","response":{"models":[{"model":"root-model"}]}}})
    if request.get("type")!="user":continue
    root=request["session_id"]
    emit({"type":"system","subtype":"init","session_id":root,"model":"root-model"})
    emit({"type":"assistant","session_id":root,"message":{"id":"parent","model":"root-model","usage":{"input_tokens":10,"output_tokens":2},"content":[{"type":"tool_use","id":"launch","name":"Agent","input":{"run_in_background":True}}]}})
    emit({"type":"user","session_id":root,"message":{"content":[{"type":"tool_result","tool_use_id":"launch","content":"launched"}]}})
    emit({"type":"system","subtype":"task_started","task_id":"child","tool_use_id":"launch"})
    emit({"type":"result","session_id":root,"subtype":"success","result":"Completed."})
    time.sleep(10 if "timeout" in sys.argv else 0.15)
    emit({"type":"assistant","agentId":"child","sessionId":root,"message":{"id":"child-message","model":"child-model","usage":{"input_tokens":5,"output_tokens":3}}})
    emit({"type":"system","subtype":"task_notification","task_id":"child","tool_use_id":"launch","status":"completed"})
""")
    for timeout in (False, True):
        logs = tmp_path / str(timeout)
        evidence = run_controller(
            {
                **config("claude"),
                "command": [sys.executable, str(server)] + (["timeout"] if timeout else []),
                "cwd": str(tmp_path),
                "log_dir": str(logs),
                "timeout_seconds": 0.4 if timeout else 5,
            }
        )
        assert evidence["status"] == ("timeout" if timeout else "completed")
        assert evidence["usage_complete"] is not timeout
        assert ("missing_background_terminal" in evidence["incomplete_reasons"]) is timeout
        assert sum(row["output_tokens"] for row in evidence["model_usage"]) == (2 if timeout else 5)
        assert json.loads((logs / "Trial_Evidence.json").read_text()) == evidence


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_local_handoff_resumes_same_root_and_requires_final_acknowledgment(provider):
    import json
    from pathlib import Path

    path = Path(__file__).parents[2] / "tasks/workflow/rust-quoted-value-parser/Scripted User.json"
    state = Conversation(config(provider) | {"policy": json.loads(path.read_text())})
    state.root = "root"
    state.interactions = 1
    state.text = (
        "Implementation complete. What would you like to do?\n\n"
        "1. Push and create a Pull Request\n"
        "2. Keep the branch as-is (I'll handle it later)\n"
        "3. Discard this work\n\nWhich option?"
    )
    outbound = state.finish_turn()
    assert len(outbound) == 1
    reply = outbound[0]
    if provider == "codex":
        assert reply["method"] == "turn/start"
        assert reply["params"]["threadId"] == "root"
        assert reply["params"]["model"] == "root-model"
        assert reply["params"]["effort"] == "high"
        text = reply["params"]["input"][0]["text"]
    else:
        assert reply["session_id"] == "root"
        text = reply["message"]["content"]
    assert text == (
        "Keep the branch and workspace as-is. Do not merge, push, publish, discard changes, "
        "or remove the worktree. Report the local handoff and stop."
    )
    assert state.interactions == 2
    assert not state.root_finished
    assert state.status != "completed"
    assert state.decisions[-1]["rule_id"] == "local-handoff"
    state.text = "The branch and workspace are preserved locally. Handoff complete."
    assert state.finish_turn() == []
    assert state.root_finished
    assert state.status == "completed"
