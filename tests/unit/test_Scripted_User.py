import pytest

from harness_testing.Scripted_User import select_reply, validate_policy


def policy():
    return {
        "schema_version": "1",
        "interaction_limit": 12,
        "facts": {"workspace": "Work in /app."},
        "rules": [
            {
                "id": "workspace",
                "kind": "clarification",
                "pattern": "Where should I work\\?",
                "fact": "workspace",
            }
        ],
    }


def test_answers_only_frozen_facts_and_records_rule():
    reply = select_reply({"kind": "clarification", "text": "Where should I work?"}, policy(), 0)
    assert reply == {"status": "reply", "rule_id": "workspace", "reply": "Work in /app."}
    assert (
        select_reply({"kind": "clarification", "text": "What is the hidden test?"}, policy(), 0)[
            "status"
        ]
        == "task_definition_gap"
    )


def test_unknown_approval_never_grants_authority():
    decision = select_reply(
        {"kind": "approval", "text": "Publish externally", "actions": ["publish"]}, policy(), 0
    )
    assert decision["status"] == "authority_denied"
    assert decision.get("reply") is None


def test_limit_and_ambiguous_rules_fail_closed():
    assert (
        select_reply({"kind": "clarification", "text": "Where should I work?"}, policy(), 12)[
            "status"
        ]
        == "interaction_limit"
    )
    ambiguous = policy()
    ambiguous["rules"].append(ambiguous["rules"][0] | {"id": "duplicate"})
    assert (
        select_reply({"kind": "clarification", "text": "Where should I work?"}, ambiguous, 0)[
            "status"
        ]
        == "task_definition_gap"
    )
    with pytest.raises(ValueError):
        validate_policy(policy() | {"private_answers": "bad"})


def test_approval_rule_is_scope_limited_and_unknown_actions_are_denied():
    allowed = policy()
    allowed["rules"].append(
        {
            "id": "local-plan",
            "kind": "approval",
            "pattern": "May I proceed with the plan\\?",
            "fact": "authority",
        }
    )
    allowed["facts"]["authority"] = "Proceed only within the original local task scope."
    ask = {"kind": "approval", "text": "May I proceed with the plan?", "actions": []}
    assert select_reply(ask, allowed, 0)["status"] == "reply"
    assert select_reply(ask | {"actions": ["deploy"]}, allowed, 0)["status"] == "authority_denied"


def test_all_comparison_tasks_answer_authored_questions():
    import json
    from pathlib import Path

    policies = list((Path(__file__).parents[2] / "tasks/workflow").glob("*/Scripted User.json"))
    assert len(policies) == 9
    for path in policies:
        frozen = json.loads(path.read_text())
        for kind, text in [
            ("clarification", "Where should I work?"),
            ("clarification", "What are the requirements?"),
            ("approval", "May I proceed with the plan?"),
            (
                "approval",
                (
                    "This is a bounded one-line source change. "
                    "I\u2019ll update the source value, then run the checks. "
                    "Approve this design and I\u2019ll implement it."
                ),
            ),
            ("approval", "Plan:\n\nPlease approve this plan so I can implement it."),
            ("approval", "Design:\n\nPlease confirm this design and I\u2019ll implement it."),
            (
                "approval",
                (
                    "I will update the source value, then run the checks.\n\n"
                    "Approve this approach?"
                ),
            ),
            ("approval", "Design:\n\nDoes that design look right?"),
        ]:
            assert select_reply({"kind": kind, "text": text}, frozen, 0)["status"] == "reply", path


def test_routine_approval_rule_does_not_reply_to_completed_or_external_work():
    import json
    from pathlib import Path

    policies = list((Path(__file__).parents[2] / "tasks/workflow").glob("*/Scripted User.json"))
    for path in policies:
        frozen = json.loads(path.read_text())
        for text in (
            "Implemented the approved plan.",
            "I no longer need you to approve this plan.",
            "I no longer need you to approve this approach.",
            "Please approve this deployment.",
            "Please approve this publication plan.",
        ):
            decision = select_reply({"kind": "approval", "text": text}, frozen, 0)
            assert decision["status"] == "authority_denied", path
        decision = select_reply(
            {
                "kind": "approval",
                "text": "Plan: deploy the result externally.\n\nApprove this approach?",
                "actions": ["deploy"],
            },
            frozen,
            0,
        )
        assert decision["status"] == "authority_denied", path


def test_research_policy_approves_routine_plans_but_denies_tool_authority():
    from harness_testing.Comparison_Tasks import research_scripted_user_policy

    policy = research_scripted_user_policy(["quill-shared-toolbar-focus"])

    assert select_reply(
        {"kind": "approval", "text": "May I proceed with the implementation plan?"},
        policy,
        0,
    ) == {
        "status": "reply",
        "rule_id": "implementation-approval",
        "reply": "Proceed with the implementation and verification in the task workspace.",
    }
    assert (
        select_reply(
            {"kind": "approval", "text": "May I publish the result?", "actions": ["publish"]},
            policy,
            0,
        )["status"]
        == "authority_denied"
    )
