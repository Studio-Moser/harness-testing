from harness_testing.Trial_Evidence import collect_trial_evidence


def assistant(session, message, model, usage, **extra):
    return {
        "type": "assistant",
        "sessionId": session,
        "message": {"id": message, "model": model, "usage": usage},
        **extra,
    }


def test_leaf_usage_deduplicates_stream_and_root_aggregate():
    event = assistant(
        "root",
        "m1",
        "large",
        {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 5},
    )
    child = assistant(
        "root", "m2", "small", {"input_tokens": 50, "output_tokens": 10}, agentId="child"
    )
    events = [
        event,
        event,
        child,
        {"type": "result", "usage": {"input_tokens": 155, "output_tokens": 30}},
    ]
    evidence = collect_trial_evidence(
        "claude", events, root_session_id="root", status="completed", duration_seconds=14
    )
    assert evidence["duration_seconds"] == 14
    assert sum(c["output_tokens"] for c in evidence["calls"]) == 30
    assert len(evidence["calls"]) == 2
    assert evidence["calls"][1]["parent_session_id"] == "root"
    assert evidence["model_usage"][0]["input_tokens"] == 100
    assert (
        collect_trial_evidence(
            "claude", events * 2, root_session_id="root", status="completed", duration_seconds=14
        )["model_usage"]
        == evidence["model_usage"]
    )


def test_codex_repeated_cumulative_updates_are_exclusive_and_missing_child_incomplete():
    def usage(total):
        return {
            "method": "thread/tokenUsage/updated",
            "params": {"threadId": "root", "turnId": "turn", "tokenUsage": {"total": total}},
        }

    first = usage(
        {
            "inputTokens": 100,
            "cachedInputTokens": 20,
            "outputTokens": 10,
            "reasoningOutputTokens": 4,
        }
    )
    second = usage(
        {
            "inputTokens": 150,
            "cachedInputTokens": 25,
            "outputTokens": 15,
            "reasoningOutputTokens": 8,
        }
    )
    child = {
        "method": "thread/started",
        "params": {"thread": {"id": "child", "parentThreadId": "root"}},
    }
    evidence = collect_trial_evidence(
        "codex",
        [first, first, second, first, child],
        root_session_id="root",
        status="timeout",
        duration_seconds=3,
        identities={"root": {"model": "large", "effort": "high"}},
    )
    assert sum(c["input_tokens"] for c in evidence["calls"]) == 125
    assert sum(c["cache_read_tokens"] for c in evidence["calls"]) == 25
    assert sum(c["output_tokens"] for c in evidence["calls"]) == 15
    assert evidence["usage_complete"] is False
    assert "missing_session_usage" in evidence["incomplete_reasons"]
    assert evidence["status"] == "timeout"


def test_unknown_usage_does_not_become_zero():
    event = assistant("root", "m", "large", {"input_tokens": None, "output_tokens": 3})
    evidence = collect_trial_evidence(
        "claude", [event], root_session_id="root", status="agent_failed", duration_seconds=1
    )
    assert not evidence["usage_complete"]
    assert evidence["calls"][0]["input_tokens"] is None


def test_persisted_codex_root_is_explicit_and_child_model_is_observed(tmp_path):
    import json

    from harness_testing.Trial_Evidence import read_codex_transcripts

    def write(name, session, parent, model):
        rows = [
            {
                "type": "session_meta",
                "payload": {
                    "id": session,
                    "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent}}},
                },
            },
            {"type": "turn_context", "payload": {"model": model, "effort": "medium"}},
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 12,
                            "cached_input_tokens": 2,
                            "cache_write_input_tokens": 1,
                            "output_tokens": 3,
                        }
                    },
                },
            },
        ]
        (tmp_path / name).write_text("\n".join(json.dumps(row) for row in rows))

    write("A.jsonl", "root", None, "large")
    write("Z.jsonl", "child", "root", "small")
    write("ZZ.jsonl", "unrelated", None, "other")
    events, identities = read_codex_transcripts(tmp_path, "root")
    evidence = collect_trial_evidence(
        "codex",
        events,
        root_session_id="root",
        status="completed",
        duration_seconds=2,
        identities=identities,
    )
    assert {row["model"] for row in evidence["calls"]} == {"large", "small"}
    assert sum(row["input_tokens"] for row in evidence["calls"]) == 18
    assert sum(row["cache_write_tokens"] for row in evidence["calls"]) == 2


def claude_background_events():
    return [
        {
            "type": "assistant",
            "session_id": "root",
            "message": {
                "id": "parent-launch",
                "model": "root-model",
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "content": [
                    {
                        "type": "tool_use",
                        "id": "agent-tool",
                        "name": "Agent",
                        "input": {"run_in_background": True},
                    }
                ],
            },
        },
        {
            "type": "user",
            "session_id": "root",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "agent-tool",
                        "content": "Agent launched successfully in background. Task ID: child",
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "agentId": "child",
            "sessionId": "root",
            "message": {
                "id": "child-partial",
                "model": "child-model",
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        },
        {"type": "result", "subtype": "success", "session_id": "root", "result": "Completed."},
    ]


def test_background_launch_acknowledgment_is_not_child_completion():
    events = claude_background_events()
    evidence = collect_trial_evidence(
        "claude", events, root_session_id="root", status="completed", duration_seconds=1
    )
    assert not evidence["usage_complete"]
    assert "missing_background_terminal" in evidence["incomplete_reasons"]
    events.append(
        {
            "type": "system",
            "subtype": "task_notification",
            "task_id": "child",
            "tool_use_id": "agent-tool",
            "status": "completed",
        }
    )
    completed = collect_trial_evidence(
        "claude", events, root_session_id="root", status="completed", duration_seconds=1
    )
    assert completed["usage_complete"]


def test_overlapping_cumulative_observations_reconcile_endpoints_once():
    from harness_testing.Trial_Evidence import merge_external_evidence

    def totals(values):
        return collect_trial_evidence(
            "codex",
            [
                {
                    "method": "thread/tokenUsage/updated",
                    "params": {
                        "threadId": "external-root",
                        "tokenUsage": {"total": {"inputTokens": value, "outputTokens": value}},
                    },
                }
                for value in values
            ],
            root_session_id="external-root",
            status="completed",
            duration_seconds=1,
            identities={"external-root": {"model": "child-model", "effort": "low"}},
        )

    parent = collect_trial_evidence(
        "claude",
        [assistant("root", "parent", "root-model", {"input_tokens": 10, "output_tokens": 2})],
        root_session_id="root",
        status="completed",
        duration_seconds=1,
    )
    for observations, expected in [
        ([totals([10, 20]), totals([30, 10, 20, 30])], 30),
        ([totals([10, 20]), totals([20])], 20),
    ]:
        for ordered in (observations, list(reversed(observations)), observations * 2):
            merged = merge_external_evidence(parent, ordered)
            child = next(row for row in merged["model_usage"] if row["model"] == "child-model")
            assert child["input_tokens"] == expected
            assert child["output_tokens"] == expected
            assert merged["usage_complete"]


def test_native_child_pool_validation_preserves_unknown_effort():
    inventory = [{"provider": "anthropic", "model": "child-model", "effort": "low"}]
    for model, expected in [
        ("child-model", "executor_effort_unverified"),
        ("unapproved", "executor_condition_mismatch"),
    ]:
        events = [
            {
                "type": "assistant",
                "agentId": "child",
                "sessionId": "root",
                "message": {
                    "id": "child-message",
                    "model": model,
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                },
            }
        ]
        evidence = collect_trial_evidence(
            "claude",
            events,
            root_session_id="root",
            status="completed",
            duration_seconds=1,
            executor_inventory=inventory,
        )
        assert expected in evidence["incomplete_reasons"]
        assert evidence["usage_complete"] is False
        assert evidence["calls"][0]["effort"] is None
