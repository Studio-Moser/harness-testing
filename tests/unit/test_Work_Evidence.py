import json
from types import SimpleNamespace

import pytest

from harness_testing.Collaboration_Grading import _action_evidence, _work_evidence


def trajectory():
    return {
        "steps": [
            {
                "reasoning": "PRIVATE REASONING",
                "tool_calls": [
                    {
                        "tool_call_id": "read",
                        "function_name": "read_file",
                        "arguments": {"path": "src/cache.js"},
                    },
                    {
                        "tool_call_id": "search",
                        "function_name": "search",
                        "arguments": {"query": "cache invalidation"},
                    },
                    {
                        "tool_call_id": "test",
                        "function_name": "exec",
                        "arguments": {"cmd": "npm test"},
                    },
                    {
                        "tool_call_id": "private",
                        "function_name": "read_file",
                        "arguments": {"path": "/Users/private/secrets"},
                    },
                ],
                "observation": {
                    "results": [
                        {
                            "source_call_id": "test",
                            "content": "# tests 10\n# pass 9\n# fail 1\nPRIVATE RAW OUTPUT",
                            "extra": {"exit_code": 1},
                        }
                    ]
                },
            }
        ]
    }


def test_action_projection_retains_research_targets_and_observed_test_summary_only():
    actions = _action_evidence(trajectory())
    assert actions[0]["targets"] == {"path": "src/cache.js"}
    assert actions[1]["targets"] == {"query": "cache invalidation"}
    assert actions[2]["command"] == "npm test"
    assert actions[2]["success"] is False
    assert actions[2]["test_summary"] == ["# tests 10", "# pass 9", "# fail 1"]
    assert actions[3]["targets"] == {}
    assert "PRIVATE" not in json.dumps(actions)
    assert actions[-1]["ordinal"] == 4


def command_trajectory(commands, output="", exit_code=0):
    return {"steps": [{
        "tool_calls": [{"tool_call_id": str(i), "function_name": "shell",
                        "arguments": {"cmd": command}}],
        "observation": {"results": [{"source_call_id": str(i), "content": output,
                                     "extra": {"exit_code": exit_code}}]},
    } for i, command in enumerate(commands)]}


def test_private_grading_keeps_checks_with_relative_imports_and_masks_scratch_paths():
    commands = [
        '/bin/bash -lc \'npm test > /tmp/private-name.log 2>&1; cat /tmp/private-name.log\'',
        'node --input-type=module -e \'import { toggleDone } from "./src/Completion.js";\'',
        'cat /tmp/private-name.log && git diff --check > /dev/null',
        'cat "/Users/Private Person/secret-project/results.txt"',
        'node -e \'import("../src/Completion.js")\'',
        'cat /harness-arm/AGENTS.md && cd /tmp',
    ]
    actions = _action_evidence(command_trajectory(commands))
    assert all(a["command"] is not None for a in actions)
    assert "npm test" in actions[0]["command"]
    assert actions[1]["command"] == commands[1]
    assert actions[4]["command"] == commands[4]
    assert actions[0]["command"].count("SCRATCH_PATH_1") == 2
    assert "SCRATCH_PATH_1" in actions[2]["command"]
    assert "NULL_DEVICE" in actions[2]["command"]
    rendered = json.dumps(actions)
    for forbidden in (
        "private-name", "Private Person", "secret-project", "/Users", "/tmp", "/harness-arm"
    ):
        assert forbidden not in rendered


def test_private_grading_keeps_long_inline_checks_but_secrets_stay_omitted():
    long_check = "node -e '" + "assert.ok(true);" * 200 + "'"
    actions = _action_evidence(command_trajectory([
        long_check, "API_KEY=sk-abcdefghijkl npm test", "cat ../../Users/private/file",
        "x" * 100_001, 'node -e \'const config = {"password": "do-not-retain"}\'',
        'cat "C:\\Users\\private\\file"',
        r'cat "\\server\share\private"',
    ]))
    assert actions[0]["command"] == long_check
    assert all(a["command"] is None and a["omissions"] for a in actions[1:])
    assert "sk-abcdefghijkl" not in json.dumps(actions)
    assert "do-not-retain" not in json.dumps(actions)


def test_private_code_evidence_is_not_mistaken_for_public_prose_paths():
    from harness_testing.Public_Safety import public_safety_errors

    commands = [
        r'''node -e 'console.log(/^\d+$/.test("12"))' ''',
        r'''python3 -c 'print("\\n\\t")' ''',
        r'''node -e 'render("\\multicolumn{2}{r}{x}")' ''',
        'node -e \'/** comment */ const x = "../src/Completion.js"\'',
        r'''text(await tools.exec_command({cmd:"node -e 'const x={p:\"test\"}'"}));''',
    ]
    actions = _action_evidence(command_trajectory(commands))
    assert [a["command"] for a in actions] == commands
    # Public safety remains strict. Private input fidelity must not relax exports.
    assert public_safety_errors({"command_output": commands})


@pytest.mark.parametrize("summary", [
    "ℹ tests 4\nℹ pass 4\nℹ fail 0",
    "\x1b[32mTest Files  2 passed (2)\x1b[0m\nTests  8 passed (8)",
    "test result: ok. 8 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s",
    "Test Suites: 2 passed, 2 total\nTests: 8 passed, 8 total",
])
def test_numeric_test_formats_survive_without_raw_output(summary):
    actions = _action_evidence(command_trajectory(
        ["npm test"], summary + "\nPRIVATE OUTPUT\nsecret=never-retain\n", exit_code=1))
    assert actions[0]["test_summary"]
    assert "PRIVATE" not in json.dumps(actions) and "never-retain" not in json.dumps(actions)
    assert actions[0]["success"] is False  # Numeric summaries never override exit evidence.


def test_wrapper_code_and_results_are_private_inspectable_not_guessed_success():
    code = ('text(await tools.exec_command({cmd:"npm test"})); '
            'image((await tools.view_image({path:`/tmp/proof/${view}.png`})).image_url);')
    blocks = [
        {
            "type": "input_text",
            "text": json.dumps({"exit_code": 0, "output": "Tests  8 passed (8)\nPRIVATE OUTPUT"}),
        },
        {
            "type": "input_text",
            "text": json.dumps({"exit_code": 1, "output": "# fail 1\npassword=secret"}),
        },
        {"type": "input_image", "image_url": "PRIVATE IMAGE BYTES"},
    ]
    data = {
        "steps": [
            {
                "tool_calls": [
                    {
                        "tool_call_id": "wrapper",
                        "function_name": "exec",
                        "arguments": {"input": code},
                    }
                ],
                "observation": {
                    "results": [{"source_call_id": "wrapper", "content": repr(blocks)}]
                },
            }
        ]
    }
    action = _action_evidence(data)[0]
    assert "npm test" in action["command"] and "view_image" in action["command"]
    assert "/tmp/proof" not in action["command"]
    assert action["success"] is None
    assert action["test_summary"] == ["Tests  8 passed (8)", "# fail 1"]
    assert action["wrapper_results"] == [{"block": 0, "exit_code": 0}, {"block": 1, "exit_code": 1}]
    assert action["returned_image_count"] == 1
    assert "PRIVATE OUTPUT" not in json.dumps(action) and "PRIVATE IMAGE" not in json.dumps(action)
    assert "password=secret" not in json.dumps(action)


@pytest.mark.parametrize(
    "content",
    [
        "not a literal",
        "__import__('os').system('false')",
        repr([{"type": "input_text", "text": '{"output":"exit_code: 0"}'}]),
    ],
)
def test_wrapper_unknown_results_do_not_fabricate_success(content):
    data = {
        "steps": [
            {
                "tool_calls": [
                    {
                        "tool_call_id": "wrapper",
                        "function_name": "exec",
                        "arguments": {"input": "await tools.exec_command({cmd: 'npm test'})"},
                    }
                ],
                "observation": {"results": [{"source_call_id": "wrapper", "content": content}]},
            }
        ]
    }
    action = _action_evidence(data)[0]
    assert action["success"] is None
    assert action["wrapper_results"] == []


def test_wrapper_secrets_remain_omitted():
    data = {
        "steps": [
            {
                "tool_calls": [
                    {
                        "function_name": "exec",
                        "arguments": {
                            "input": ('await tools.exec_command('
                                      '{cmd: "API_KEY=sk-abcdefghijkl npm test"})')
                        },
                    }
                ]
            }
        ]
    }
    action = _action_evidence(data)[0]
    assert action["command"] is None and action["omissions"]


@pytest.mark.parametrize("length,status", [(250_000, "complete"), (2_000_001, "partial")])
def test_large_evidence_is_chunked_or_explicitly_partial_not_discarded(
    tmp_path, monkeypatch, length, status
):
    from harness_testing import Code_Reviews, Config

    monkeypatch.setattr(
        Code_Reviews, "_manifest_for_report", lambda *_: {"digest": "sha256:" + "a" * 64}
    )
    monkeypatch.setattr(
        Code_Reviews, "_trial_inputs", lambda *_: {"patch": b"x" * length, "base_files": {}}
    )
    monkeypatch.setattr(Code_Reviews, "_trial_job", lambda *_: "job.json")
    monkeypatch.setattr(Config, "load_job", lambda *_: SimpleNamespace(job_name="fixture"))
    path = tmp_path / "jobs/raw/fixture/trial/agent/trajectory.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(trajectory()))
    result = _work_evidence(tmp_path, {}, {})
    assert result["status"] == status
    assert len("".join(result["patch_chunks"])) == min(length, 2_000_000)
    assert result["patch_characters"] == length
    assert result["actions"][0]["targets"]["path"] == "src/cache.js"
    assert bool(result["limitations"]) == (status == "partial")
    assert result["unavailable_dimensions"] == (
        ["regression_coverage", "requirements_fit"] if status == "partial" else []
    )


def native_logs(tmp_path):
    evidence = {"status": "completed", "child_count": 0, "root_session_id": "root",
                "sessions": [{"session_id": "root"}]}
    (tmp_path / "Trial_Evidence.json").write_text(json.dumps(evidence))
    (tmp_path / "Root_Identity.json").write_text(json.dumps({"root_session_id": "root"}))
    item = {"id": "call", "type": "commandExecution", "command": "npm test"}
    events = [
        {"method": "turn/started", "params": {"threadId": "root", "turn": {"id": "turn"}}},
        {"method": "item/started", "params": {
            "threadId": "root", "turnId": "turn", "item": item}},
        {"method": "item/completed", "params": {
            "threadId": "root", "turnId": "turn", "item": item | {
                "status": "completed", "exitCode": 0,
                "aggregatedOutput": "# tests 1\n# pass 1\nPRIVATE RAW OUTPUT",
                "reasoning": "PRIVATE REASONING"}}},
        {"method": "turn/completed", "params": {
            "threadId": "root", "turn": {"id": "turn", "status": "completed"}}},
    ]
    return evidence, events


@pytest.mark.parametrize(
    "tamper", [None, "truncated", "child", "unknown", "duplicate", "root", "identity"]
)
def test_native_command_recovery_is_complete_or_unavailable(tmp_path, tamper):
    from harness_testing.Collaboration_Grading import _native_action_trajectory

    evidence, events = native_logs(tmp_path)
    if tamper == "truncated":
        events.pop()
    elif tamper == "child":
        evidence["child_count"] = 1
        (tmp_path / "Trial_Evidence.json").write_text(json.dumps(evidence))
    elif tamper == "unknown":
        events[1]["params"]["item"]["type"] = "unknownTool"
        events[2]["params"]["item"]["type"] = "unknownTool"
    elif tamper == "duplicate":
        events.append(events[2])
    elif tamper == "root":
        events[2]["params"]["threadId"] = "other"
    elif tamper == "identity":
        (tmp_path / "Root_Identity.json").write_text(json.dumps({"root_session_id": "other"}))
    path = tmp_path / "codex.txt"
    path.write_text("\n".join(json.dumps(e) for e in events))
    before = path.read_bytes()
    if tamper:
        with pytest.raises(ValueError):
            _native_action_trajectory(tmp_path)
    else:
        (tmp_path / "Root_Identity.json").write_text(json.dumps({"root_session_id": None}))
        restored, raw = _native_action_trajectory(tmp_path)
        actions = _action_evidence(restored)
        assert raw == before
        assert len(actions) == 1 and actions[0]["success"] is True
        assert actions[0]["test_summary"] == ["# tests 1", "# pass 1"]
        assert "PRIVATE" not in json.dumps(actions)
    assert path.read_bytes() == before
