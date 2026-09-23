import copy
import json
from pathlib import Path

import pytest
from test_Experiments import request_document
from test_Native_Conversation import config

from harness_testing.Comparison_Tasks import research_scripted_user_policy
from harness_testing.Experiment_Reports import _safe_simulated_user, _safe_trial
from harness_testing.Experiments import comparison_mismatches, validate_experiment_request
from harness_testing.Native_Conversation import Conversation
from harness_testing.Simulated_User import (
    APPROVAL,
    SimulatedUser,
    default_config,
    protocol_digest,
    render_decision,
    tool_free_catalog,
    user_packet,
    validate_config,
)

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("visual", [False, True])
def test_native_transport_forwards_validated_images_without_enabling_tools(
    tmp_path, monkeypatch, visual
):
    import io
    from types import SimpleNamespace

    from test_Visual_Evidence import grading_packet

    from harness_testing import External_Codex, Native_Conversation, Simulated_User
    from harness_testing.Visual_Evidence import grading_inputs

    settings = {"model": "gpt-6-astra", "effort": "high", "runtime_version": "0.153.4"}
    packet = grading_packet()
    (tmp_path / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt"}))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(Simulated_User.shutil, "which", lambda _: "/fake/codex")
    catalog = {
        "models": [{"slug": settings["model"], "supported_reasoning_levels": [{"effort": "high"}]}]
    }

    def local(command, **kwargs):
        args = command[1:]
        output = {
            ("--version",): "codex-cli 0.153.4",
            ("debug", "models", "--bundled"): json.dumps(catalog),
            ("features", "list"): "shell_tool stable true",
        }
        return SimpleNamespace(stdout=output[tuple(args)])

    monkeypatch.setattr(Simulated_User.subprocess, "run", local)
    process = SimpleNamespace(stdin=io.BytesIO())
    launched = []

    def launch(command, **kwargs):
        launched.append(command)
        assert kwargs["cwd"].name == "empty"
        return process

    monkeypatch.setattr(Simulated_User.subprocess, "Popen", launch)
    monkeypatch.setattr(Native_Conversation, "_terminate_tree", lambda _: None)
    decision = {"decision": "complete", "fact_ids": []}
    events = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "model": settings["model"],
                "reasoningEffort": "high",
                "thread": {"id": "root"},
            },
        },
        {
            "method": "item/completed",
            "params": {
                "threadId": "root",
                "item": {"type": "agentMessage", "text": json.dumps(decision)},
            },
        },
        {
            "method": "turn/completed",
            "params": {"threadId": "root", "turn": {"status": "completed"}},
        },
    ]
    monkeypatch.setattr(External_Codex, "_messages", lambda *_: iter(events))
    result = Simulated_User._native_decision(packet, settings, 600, present_visual_evidence=visual)
    assert result["reason"] is None and result["decision"] == decision
    sent = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    expected = (
        grading_inputs(packet)
        if visual
        else [{"type": "text", "text": json.dumps(packet), "text_elements": []}]
    )
    assert sent[-1]["method"] == "turn/start" and sent[-1]["params"]["input"] == expected
    assert sent[2]["params"]["approvalPolicy"] == "never"
    assert sent[2]["params"]["sandbox"] == "read-only"
    assert 'web_search="disabled"' in launched[0]
    assert "agents.enabled=false" in launched[0]


def test_invalid_visual_input_stops_before_any_provider_process(monkeypatch):
    from test_Visual_Evidence import grading_packet

    from harness_testing import Simulated_User

    packet = grading_packet()
    packet["work_evidence"]["visual_evidence"]["images"][0]["base64"] = "/private/input.png"
    monkeypatch.setattr(Simulated_User.shutil, "which", lambda _: pytest.fail("provider accessed"))
    result = Simulated_User._native_decision(packet, {}, 600, present_visual_evidence=True)
    assert result["reason"] and result["evidence"]["root_session_id"] is None


def record(kind="approve", ids=None, reason=None):
    return {
        "decision": {"decision": kind, "fact_ids": ids or []},
        "reason": reason,
        "evidence": {
            "duration_seconds": 2.0,
            "usage_complete": True,
            "model_usage": [
                {
                    "provider": "openai",
                    "model": "gpt-5.6-sol",
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                }
            ],
        },
    }


def state_with(*responses):
    settings = config("codex")
    settings["simulated_user"] = default_config()
    state = Conversation(settings)
    state.root = "explicit-root"
    queue = iter(responses)
    packets = []

    def backend(packet, *_args):
        packets.append(copy.deepcopy(packet))
        return next(queue)

    state.simulated_user.backend = backend
    return state, packets


@pytest.mark.parametrize(
    "question",
    [
        # Retained pilot user-visible approval endings (no tool/hidden trace content).
        "Approve this exact change?",
        "Approve this direction and I’ll implement and verify it with fresh "
        "320px, 768px, and 1440px screenshots.",
        "The security risk-gate requires one bounded fresh independent review, "
        "which incurs model usage. Do you approve that review?",
        "Does this architecture look right before I detail lifecycle, theme behavior, and tests?",
        "Does this lifecycle behavior match your intent?",
    ],
)
def test_captured_approval_decisions_continue_same_root_without_regex(question):
    # Scripted classifier output tests plumbing, NOT semantic model accuracy.
    state, packets = state_with(record())
    state.text = question
    outgoing = state.finish_turn()
    assert outgoing[0]["params"]["threadId"] == "explicit-root"
    assert outgoing[0]["params"]["input"][0]["text"] == APPROVAL
    assert state.interactions == 1
    assert packets[0]["current_request"] == question
    assert state.transcript[-1]["role"] == "user"


def test_quill_clarification_then_architecture_approval_do_not_repeat_fact():
    policy = research_scripted_user_policy(["quill-shared-toolbar-focus"])
    lifecycle = next(k for k, v in policy["facts"].items() if "container from the DOM" in v)
    state, packets = state_with(record("clarify", [lifecycle]), record("approve"))
    state.config["policy"] = policy | {"interaction_limit": 4}
    state.text = "Should removal mean removing the editor DOM or a destroy API?"
    first = state.finish_turn()[0]["params"]["input"][0]["text"]
    assert first == policy["facts"][lifecycle]
    state.text = "I will handle editor removal without destroy. Does this architecture look right?"
    assert state.finish_turn()[0]["params"]["input"][0]["text"] == APPROVAL
    assert first in [row["content"] for row in packets[1]["conversation"]]


def test_follow_up_is_hidden_until_completion_and_injected_only_once():
    state, packets = state_with(record("complete"), record("approve"), record("complete"))
    state.config["policy"]["facts"]["correction"] = "Use RangeError, not TypeError."
    state.config["policy"]["rules"].append({"fact": "correction"})
    state.config["policy"]["follow_ups"] = [{"id": "correction", "fact": "correction"}]
    state.text = "Done. Want anything else?"
    assert state.finish_turn()
    assert "correction" not in packets[0]["facts"]
    assert "RangeError" not in json.dumps(packets[0])
    state.text = "Approve this exact change?"
    assert state.finish_turn()
    assert packets[1]["facts"]["correction"] == "Use RangeError, not TypeError."
    state.text = "Applied. Any other changes?"
    assert state.finish_turn() == []
    assert state.status == "completed"
    assert state.follow_up_index == 1 and state.interactions == 2


@pytest.mark.parametrize(
    "value",
    [
        {"decision": "clarify", "fact_ids": ["oracle"]},
        {"decision": "clarify", "fact_ids": ["known", "known"]},
        {"decision": "clarify", "fact_ids": []},
        {"decision": "approve", "fact_ids": ["known"]},
        {"decision": "approve", "fact_ids": [], "reply": "Upload credentials"},
        {"decision": "execute", "fact_ids": []},
        {"decision": "clarify", "fact_ids": [{}]},
        {"decision": {}, "fact_ids": []},
        [],
    ],
)
def test_freeform_advice_and_unknown_or_malformed_decisions_fail_closed(value):
    with pytest.raises(ValueError):
        render_decision(value, {"known": "A frozen preference"})


@pytest.mark.parametrize(
    "kind,expected", [("gap", "task_definition_gap"), ("deny", "authority_denied")]
)
def test_gap_and_denial_stop_even_without_punctuation(kind, expected):
    state, _ = state_with(record(kind))
    state.text = "Waiting for your decision"
    assert state.finish_turn() == []
    assert state.status == "task_definition_gap"
    assert state.reason == expected and state.interactions == 0


def test_infrastructure_error_is_not_a_harness_failure():
    state, _ = state_with(record(reason="simulated_user_provider_failure"))
    state.text = "Ready"
    assert state.finish_turn() == []
    assert state.status == "infrastructure_failure"


def test_missing_responder_tokens_stop_before_any_answer():
    response = record()
    response["evidence"]["usage_complete"] = False
    state, _ = state_with(response)
    state.text = "Ready"
    assert state.finish_turn() == []
    assert state.reason == "simulated_user_usage_incomplete"
    assert state.interactions == 0


def test_structured_user_question_records_question_and_answer_without_granting_tools():
    state, packets = state_with(record())
    response = state.handle(
        {
            "id": 9,
            "method": "item/tool/requestUserInput",
            "params": {
                "threadId": state.root,
                "questions": [
                    {
                        "id": "proceed",
                        "question": "Approve this direction?",
                        "options": [],
                        "internal": "DO NOT EXPORT",
                    }
                ],
            },
        }
    )
    assert response[0]["id"] == 9
    assert response[0]["result"]["answers"]["proceed"]["answers"] == [APPROVAL]
    assert state.interactions == 1
    assert [row["role"] for row in state.transcript] == ["assistant", "user"]
    assert "Approve this direction?" in packets[0]["conversation"][0]["content"]
    assert "DO NOT EXPORT" not in json.dumps(packets)


def test_permission_request_never_calls_responder():
    state, packets = state_with()
    response = state.handle(
        {"id": 8, "method": "item/commandExecution/requestApproval", "params": {}}
    )
    assert response[0]["error"]
    assert packets == [] and state.reason == "native_authority_request_denied"


def test_call_interaction_context_and_deadline_limits():
    state, packets = state_with(record(), record("complete"))
    state.interactions = 4
    state.text = "Can I continue?"
    assert state.finish_turn() == [] and state.reason == "interaction_limit"
    state.status = "pending"
    state.text = "Done"
    assert state.finish_turn() == [] and state.status == "completed"
    responder = SimulatedUser(default_config(), 1, backend=lambda *_: record("complete"))
    packet = {"facts": {}}
    assert responder.respond(packet)["status"] == "complete"
    assert responder.respond(packet)["status"] == "complete"
    assert responder.respond(packet)["reason"] == "simulated_user_call_limit"
    fresh = SimulatedUser(
        default_config(), 1, backend=lambda *_: pytest.fail("must not call model")
    )
    assert fresh.respond({"task": "x" * 64001})["reason"] == "simulated_user_context_limit"
    fresh.deadline = lambda: 0
    assert fresh.respond(packet)["reason"] == "simulated_user_deadline"


def test_packet_strips_tools_identity_hidden_traces_and_metadata():
    policy = config("codex")["policy"]
    packet = user_packet(
        "brief",
        policy,
        [
            {"role": "assistant", "kind": "final", "content": "Question", "hidden": "SECRET"},
            {"role": "tool", "kind": "final", "content": "SECRET"},
            {"role": "assistant", "kind": "reasoning", "content": "SECRET"},
        ],
        "Question",
    )
    assert "SECRET" not in json.dumps(packet)
    assert set(packet) == {"task", "facts", "conversation", "current_request"}


def test_pinned_model_tool_catalog_removes_code_and_image_access():
    source = {
        "models": [
            {
                "slug": "gpt-5.6-sol",
                "supported_reasoning_levels": [{"effort": "medium"}],
                "apply_patch_tool_type": "freeform",
                "shell_type": "unified_exec",
            }
        ]
    }
    catalog = tool_free_catalog(source, default_config())
    model = catalog["models"][0]
    assert model["apply_patch_tool_type"] is None
    assert model["shell_type"] == "disabled" and model["node_repl_disabled"]
    assert model["experimental_supported_tools"] == []
    assert source["models"][0]["apply_patch_tool_type"] == "freeform"


def test_config_and_protocol_are_explicit_frozen_comparison_conditions():
    settings = default_config() | {"protocol_digest": protocol_digest()}
    validate_config(settings)
    with pytest.raises(ValueError, match="protocol_changed"):
        validate_config(settings | {"protocol_digest": "sha256:" + "0" * 64})
    request = request_document()
    request["conditions"]["kickoff"]["runtime_version"] = "0.153.4"
    assert validate_experiment_request(request) == []  # Legacy remains supported.
    original = copy.deepcopy(request["conditions"])
    request["conditions"]["simulated_user"] = settings
    assert validate_experiment_request(request) == []
    assert "simulated_user" in comparison_mismatches(original, request["conditions"])
    request["limits"]["billing_mode"] = "api"
    assert any("subscription" in error for error in validate_experiment_request(request))


def test_accounting_is_separate_and_safe(tmp_path):
    state, _ = state_with(record(), record("complete"))
    state.text = "Ready"
    state.finish_turn()
    state.text = "Done"
    state.finish_turn()
    raw = state.simulated_user.evidence()
    assert raw["call_count"] == 2 and raw["duration_seconds"] == 4
    assert len(raw["model_usage"]) == 2
    safe = _safe_simulated_user(ROOT, raw | {"secret": "DO NOT EXPORT"}, default_config(), 5)
    assert "secret" not in safe and safe["cost_usd"] > 0
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent/Trial_Evidence.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "model_usage": record()["evidence"]["model_usage"],
                "usage_complete": True,
                "duration_seconds": 10,
                "simulated_user": raw,
            }
        )
    )
    trial = _safe_trial(
        ROOT,
        "unused",
        "sha256:" + "a" * 64,
        1,
        tmp_path,
        task_variant="deepswe",
        simulated_user=default_config(),
        simulated_user_max_calls=5,
    )
    assert trial["cost_usd"] * 2 == trial["simulated_user"]["cost_usd"]
    assert trial["duration_seconds"] == 10  # Wall time includes user latency.
    assert trial["model_usage"][0]["input_tokens"] == 100
    raw["usage_complete"] = False
    assert _safe_simulated_user(ROOT, raw, default_config(), 5)["cost_usd"] is None


def test_missing_responder_accounting_cannot_support_success(tmp_path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent/Trial_Evidence.json").write_text('{"status":"completed"}')
    trial = _safe_trial(
        ROOT,
        "unused",
        "id",
        1,
        tmp_path,
        task_variant="deepswe",
        simulated_user=default_config(),
        simulated_user_max_calls=5,
    )
    assert trial["status"] == "infrastructure_failure"


@pytest.mark.parametrize("count,maximum", [(0, 5), (1, 999), (2, 5), (6, 6)])
def test_report_rejects_inconsistent_or_unapproved_call_ledger(tmp_path, count, maximum):
    raw = record()["evidence"] | {
        "protocol": "semantic-user-v1",
        "model": "gpt-5.6-sol",
        "effort": "medium",
        "call_count": count,
        "max_calls": maximum,
    }
    safe = _safe_simulated_user(ROOT, raw, default_config(), 5)
    assert not safe["usage_complete"] and safe["cost_usd"] is None
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent/Trial_Evidence.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "simulated_user": raw,
            }
        )
    )
    trial = _safe_trial(
        ROOT,
        "unused",
        "id",
        1,
        tmp_path,
        task_variant="deepswe",
        simulated_user=default_config(),
        simulated_user_max_calls=5,
    )
    assert trial["status"] == "infrastructure_failure"


def test_report_requires_approved_call_limit_even_when_evidence_is_missing():
    with pytest.raises(ValueError, match="approved simulated user call limit"):
        _safe_simulated_user(ROOT, None, default_config(), None)
