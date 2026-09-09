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
            ("approval", "Shall I implement and verify this minimal fix?"),
            (
                "approval",
                (
                    "This is a bounded one-line source change. "
                    "I\u2019ll update the source value, then run the checks. "
                    "Approve this design and I\u2019ll implement it."
                ),
            ),
            ("approval", "Plan:\n\nPlease approve this plan so I can implement it."),
            ("approval", "Plan:\n\nPlease approve this plan so I can proceed."),
            ("approval", "Design:\n\nPlease confirm this design and I\u2019ll implement it."),
            ("approval", "Design:\n\nPlease confirm this design and I\u2019ll continue."),
            ("approval", "Please approve this plan so I can branch and implement."),
            ("approval", "Please approve this plan so I can update src/lib.rs."),
            ("approval", "Please approve this plan before I release v1.2."),
            (
                "approval",
                (
                    "The plan only changes the local display. "
                    "Please approve this plan while I prepare it."
                ),
            ),
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
            "Please approve this plan so I can deploy.",
            "Please approve this plan so I can proceed with deployment.",
            "Please approve this plan so I can continue and publish.",
            "Please approve this plan so I can implement it and spend money.",
            "I will proceed with the local change.",
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
        decision = select_reply(
            {
                "kind": "approval",
                "text": "Please approve this plan so I can proceed.",
                "actions": ["deploy"],
            },
            frozen,
            0,
        )
        assert decision["status"] == "authority_denied", path


def test_local_development_matcher_is_strict_and_legacy_patterns_still_work():
    local = policy()
    local["facts"]["authority"] = "Proceed within the original local task."
    local["rules"].append(
        {
            "id": "local",
            "kind": "approval",
            "matcher": "local-development-approval",
            "fact": "authority",
        }
    )
    for text in (
        "Please approve this plan so I can branch and implement.",
        "This plan changes one local value. Please confirm this approach when ready.",
        "May I continue with this plan after the check?",
        "Shall I implement and verify this minimal fix?",
        "The plan says do not publish. Please approve this plan while I prepare it.",
    ):
        assert select_reply({"kind": "approval", "text": text}, local, 0)["status"] == "reply"
    for text in (
        "I no longer need you to approve this plan.",
        "Implemented the approved plan.",
        "Please approve this plan so I can deploy.",
        "Please approve this plan and publish it.",
        "Please approve this plan for publication.",
        "Please approve this plan so I can upload logs.",
        "Please approve this plan for sending credentials.",
        "Please confirm receipt before I approve this plan.",
        "Please approve extra authority to confirm this plan.",
        "Please approve this plan with additional permissions.",
        "Please approve this plan with broader authority.",
        "Please approve this plan outside the original scope.",
        "Shall I implement and publish this minimal fix?",
        "Please approve this proposal.",
    ):
        assert (
            select_reply({"kind": "approval", "text": text}, local, 0)["status"]
            == "authority_denied"
        )
    legacy = policy()
    legacy["facts"]["authority"] = "Proceed within the original local task."
    legacy["rules"].append(
        {
            "id": "legacy",
            "kind": "approval",
            "pattern": "Ready to proceed\\?",
            "fact": "authority",
        }
    )
    assert (
        select_reply({"kind": "approval", "text": "Ready to proceed?"}, legacy, 0)["status"]
        == "reply"
    )


def test_matcher_policy_shape_is_exclusive_in_runtime_and_schema():
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    local = {
        "id": "local",
        "kind": "approval",
        "matcher": "local-development-approval",
        "fact": "authority",
    }
    valid = policy()
    valid["facts"]["authority"] = "Proceed locally."
    valid["rules"].append(local)
    validate_policy(valid)
    schema_path = Path(__file__).parents[2] / "policy/Scripted User.schema.json"
    schema = json.loads(schema_path.read_text())
    validator = Draft202012Validator(schema)
    assert validator.is_valid(valid)
    for rule in (
        local | {"pattern": "Ready\\?"},
        {key: value for key, value in local.items() if key != "matcher"},
        local | {"matcher": "unknown"},
        local | {"kind": "clarification"},
    ):
        invalid = valid | {"rules": [valid["rules"][0], rule]}
        with pytest.raises(ValueError):
            validate_policy(invalid)
        assert not validator.is_valid(invalid)


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


# Synthetic completion menu: no private run transcript or task solution.
HANDOFF_MENU = (
    "Checks passed.\n\nImplementation complete. What would you like to do?\n\n"
    "1. Merge back to main locally\n"
    "2. Push and create a Pull Request\n"
    "3. Keep the branch as-is (I'll handle it later)\n\n"
    "Which option?"
)
HANDOFF_REPLY = (
    "Keep the branch and workspace as-is. Do not merge, push, publish, discard changes, "
    "or remove the worktree. Report the local handoff and stop."
)


def test_all_task_policies_answer_only_explicit_local_branch_handoffs():
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    root = Path(__file__).parents[2]
    validator = Draft202012Validator(
        json.loads((root / "policy/Scripted User.schema.json").read_text())
    )
    for path in (root / "tasks/workflow").glob("*/Scripted User.json"):
        frozen = json.loads(path.read_text())
        assert validator.is_valid(frozen)
        for text in (HANDOFF_MENU, HANDOFF_MENU.replace("3. Keep", "4) Keep")):
            assert select_reply({"kind": "clarification", "text": text}, frozen, 1) == {
                "status": "reply",
                "rule_id": "local-handoff",
                "reply": HANDOFF_REPLY,
            }
        for text in (
            "",
            "Which option?",
            "Keep the branch as-is?",
            HANDOFF_MENU.replace("Implementation complete.", "Implementation blocked."),
            HANDOFF_MENU.replace("Keep the branch as-is", "Discard the branch"),
            HANDOFF_MENU.replace("(I'll handle it later)", "and push it"),
            HANDOFF_MENU + " Please approve publication?",
            HANDOFF_MENU + "x" * 8192,
        ):
            assert (
                select_reply({"kind": "clarification", "text": text}, frozen, 1)["status"]
                == "task_definition_gap"
            )
        assert (
            select_reply(
                {"kind": "clarification", "text": HANDOFF_MENU, "actions": ["push"]}, frozen, 1
            )["status"]
            == "authority_denied"
        )
        assert (
            select_reply({"kind": "clarification", "text": HANDOFF_MENU}, frozen, 12)["status"]
            == "interaction_limit"
        )
        legacy = frozen | {"rules": [r for r in frozen["rules"] if r["id"] != "local-handoff"]}
        assert (
            select_reply({"kind": "clarification", "text": HANDOFF_MENU}, legacy, 1)["status"]
            == "task_definition_gap"
        )
        invalid = frozen | {
            "rules": [
                {
                    "id": "bad",
                    "kind": "approval",
                    "matcher": "local-branch-handoff",
                    "fact": "task",
                }
            ]
        }
        assert not validator.is_valid(invalid)
        with pytest.raises(ValueError):
            validate_policy(invalid)
