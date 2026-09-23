import json
from pathlib import Path

import pytest

from harness_testing.Comparison_Tasks import materialize_comparison_tasks


def test_variant_keeps_oracle_and_protection_but_changes_prompt(tmp_path):
    source = tmp_path / "tasks/workflow/fixture-task"
    (source / "tests").mkdir(parents=True)
    (source / "task.toml").write_text('version = "1.0"\n')
    (source / "instruction.md").write_text("Run the gate exactly once.")
    (source / "Comparison Instruction.md").write_text("Fix the requested behavior.")
    (source / "Scripted User.json").write_text(
        json.dumps({"schema_version": "1", "interaction_limit": 12, "facts": {}, "rules": []})
    )
    (source / "tests/Protected_Files.json").write_text('{"protected": true}')
    dataset = materialize_comparison_tasks(tmp_path, ["fixture-task"])
    prompt = (dataset / "fixture-task/instruction.md").read_text()
    assert prompt.startswith("Fix the requested behavior.\n\n")
    assert "Existing test files are read-only" in prompt
    assert "including when adding or strengthening assertions" in prompt
    assert "If you write tests, put them in new, separate test files" in prompt
    assert (dataset / "fixture-task/Comparison Instruction.md").read_text() == prompt
    assert (dataset / "fixture-task/tests/Protected_Files.json").read_bytes() == (
        source / "tests/Protected_Files.json"
    ).read_bytes()
    assert (source / "instruction.md").read_text() == "Run the gate exactly once."
    assert materialize_comparison_tasks(tmp_path, ["fixture-task"]) == dataset
    (source / "Comparison Instruction.md").write_text("Different request.")
    assert materialize_comparison_tasks(tmp_path, ["fixture-task"]) != dataset


def test_all_existing_comparison_tasks_have_frozen_valid_user_policy():
    from harness_testing.Scripted_User import validate_policy

    root = Path(__file__).parents[2]
    tasks = list((root / "tasks/workflow").glob("*/task.toml"))
    assert len(tasks) == 20
    for task in tasks:
        assert (task.parent / "Comparison Instruction.md").read_text().strip()
        validate_policy(json.loads((task.parent / "Scripted User.json").read_text()))


def test_traversal_and_nonworkflow_tasks_rejected(tmp_path):
    with pytest.raises(ValueError):
        materialize_comparison_tasks(tmp_path, ["../contract"])


def test_ambiguous_feature_has_useful_frozen_reply_not_extra_authority():
    from harness_testing.Scripted_User import select_reply

    task = Path(__file__).parents[2] / "tasks/workflow/react-saved-view-feature"
    policy = json.loads((task / "Scripted User.json").read_text())
    response = select_reply(
        {
            "kind": "clarification",
            "text": (
                "Should saved selections survive reload, and what is the invalid-data fallback?"
            ),
        },
        policy,
        0,
    )
    assert response["status"] == "reply"
    assert "dashboard.saved-view" in response["reply"]
    assert "leave storage untouched" in response["reply"]
    assert "If getItem throws, silently return `all`" in response["reply"]
    assert "if setItem throws, silently keep the selected view in memory" in response["reply"]
    assert "including `all`" in response["reply"]
    assert "no trimming, case conversion, or JSON encoding" in response["reply"]
    prompt = (task / "Comparison Instruction.md").read_text()
    assert "dashboard.saved-view" not in prompt
    assert "which view states" not in prompt
    assert "already define the supported view states" in prompt
    approval = select_reply({"kind": "approval", "text": "May I proceed?"}, policy, 0)
    assert approval["rule_id"] == "routine-plan"
    assert "additional spending" in approval["reply"]
    contract = json.loads((task / "Communication Contract.json").read_text())
    assert contract["expectations"]["questions"]["minimum"] == 1
    assert contract["expectations"]["approval_requests"]["maximum"] == 0


def test_research_policy_supports_every_pinned_l4_task():
    from harness_testing.Comparison_Tasks import research_scripted_user_policy
    from harness_testing.Materialize import DEEPSWE_TASK_IDS

    for task in DEEPSWE_TASK_IDS:
        assert research_scripted_user_policy([task])["rules"]
    with pytest.raises(ValueError, match="pinned"):
        research_scripted_user_policy(["not-pinned"])


def test_quill_removal_clarification_is_frozen_and_task_specific():
    from harness_testing.Comparison_Tasks import research_scripted_user_policy
    from harness_testing.Materialize import DEEPSWE_TASK_IDS
    from harness_testing.Scripted_User import select_reply

    question = {
        "kind": "clarification",
        "text": "Does removing the active editor mean DOM removal or adding quill.destroy()?",
    }
    for task in DEEPSWE_TASK_IDS:
        policy = research_scripted_user_policy([task])
        reply = select_reply(question, policy, 0)
        if task == "quill-shared-toolbar-focus":
            assert reply["rule_id"] == "editor-removal"
            assert "removing its container from the DOM" in reply["reply"]
            assert "do not add a new public" in reply["reply"]
            assert select_reply(question, policy, 1)["status"] == "interaction_limit"
        else:
            assert reply["status"] == "task_definition_gap"
            assert "editor-removal" not in policy["facts"]
        assert (
            select_reply(question | {"actions": ["publish"]}, policy, 0)["status"]
            == "authority_denied"
        )


@pytest.mark.parametrize("action", ["publish", "deploy", "spend", "ship", "release"])
def test_research_approval_cannot_authorize_external_actions(action):
    from harness_testing.Comparison_Tasks import research_scripted_user_policy
    from harness_testing.Scripted_User import select_reply, terminal_approval_request

    policy = research_scripted_user_policy(["quill-shared-toolbar-focus"])
    text = f"Reply yes to approve this plan and I will {action}."
    assert terminal_approval_request(text) == "external"
    assert (
        select_reply({"kind": "approval", "text": text}, policy, 0)["status"] == "authority_denied"
    )
    assert (
        select_reply(
            {"kind": "clarification", "text": "Which hidden tests should I target?"}, policy, 0
        )["status"]
        == "task_definition_gap"
    )


def test_research_overlay_preserves_source_and_verifier_and_freezes_review_prompt(tmp_path):
    from harness_testing.Code_Reviews import _task_instruction
    from harness_testing.Comparison_Tasks import materialize_research_comparison_tasks
    from harness_testing.Materialize import _file_digests, _tree_digest

    task_id = "quill-shared-toolbar-focus"
    source = tmp_path / "source" / task_id
    (source / "tests").mkdir(parents=True)
    (source / "instruction.md").write_text("Fix the shared toolbar.\n")
    (source / "task.toml").write_text('[metadata]\nbase_commit_hash = "' + "a" * 40 + '"\n')
    (source / "pre_artifacts.sh").write_text("original committed-only capture\n")
    (source / "tests/test.patch").write_text("immutable verifier\n")
    (source / "instruction.md").chmod(0o444)
    source.chmod(0o555)
    original = _tree_digest(source)
    dataset = materialize_research_comparison_tasks(tmp_path, source.parent, [task_id])
    target = dataset / task_id
    prompt = (target / "instruction.md").read_text()
    assert prompt.startswith("Fix the shared toolbar.\n\n")
    assert "Existing test files are read-only" in prompt
    assert "new, separate test files" in prompt
    assert "test-runner, package, dependency-lock, or build" in prompt
    assert "including a linked worktree" in prompt
    assert "timeout remains a timeout" in prompt
    assert "cp -a /app/node_modules WORKTREE/" in prompt
    assert "cp -a /app/packages/quill/node_modules WORKTREE/packages/quill/" in prompt
    assert "Do not move dependencies out of /app" in prompt
    assert "xvfb-run -a" in prompt
    assert json.loads((target / "Submission Contract.json").read_text()) == {
        "protocol": "worktree-snapshot-v1", "base_commit": "a" * 40,
    }
    assert (target / "pre_artifacts.sh").read_text() == (
        "#!/bin/sh\nset -eu\ntest -f /logs/artifacts/model.patch\n"
    )
    assert _tree_digest(source) == original
    assert (source / "instruction.md").stat().st_mode & 0o777 == 0o444
    assert source.stat().st_mode & 0o777 == 0o555
    assert _file_digests(source / "tests") == _file_digests(target / "tests")
    assert (source / "task.toml").read_bytes() == (target / "task.toml").read_bytes()
    manifest = {
        "provenance": {
            "experiment": {
                "conditions": {
                    "task_variant": "deepswe",
                    "task_digests": {task_id: _tree_digest(target)},
                }
            }
        }
    }
    _, reviewed = _task_instruction(tmp_path, manifest, task_id, target)
    assert reviewed.decode() == prompt
    assert materialize_research_comparison_tasks(tmp_path, source.parent, [task_id]) == dataset
    (target / "instruction.md").write_text("tampered")
    with pytest.raises(ValueError, match="frozen task digest"):
        _task_instruction(tmp_path, manifest, task_id, target)
    with pytest.raises(ValueError, match="changed after materialization"):
        materialize_research_comparison_tasks(tmp_path, source.parent, [task_id])


def test_active_badge_prompt_delivers_explicit_test_file_boundary(tmp_path):
    import shutil

    from harness_testing.Workflow_Criteria import protected_files_intact

    task_id = "react-active-badge-count"
    source = Path(__file__).parents[2] / "tasks/workflow" / task_id
    copied = tmp_path / "tasks/workflow" / task_id
    shutil.copytree(source, copied)
    dataset = materialize_comparison_tasks(tmp_path, [task_id])
    task = dataset / task_id
    prompt = (task / "instruction.md").read_text()
    assert "Add regression coverage in a new test file" in prompt
    assert "Leave existing test files byte-for-byte unchanged" in prompt
    workspace = task / "environment"
    manifest = task / "tests/Protected_Files.json"
    assert protected_files_intact(workspace, manifest)
    (workspace / "src/domain/Active_Count.test.ts").write_text("// new regression coverage\n")
    assert protected_files_intact(workspace, manifest)
    existing = workspace / "src/App.test.tsx"
    existing.write_text(existing.read_text() + "\n// even additive edits are protected\n")
    assert not protected_files_intact(workspace, manifest)

