import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from harness_testing import Workflow_Criteria


def _write_trajectory(path: Path, commands: list[str]) -> None:
    calls = [
        {
            "tool_call_id": "edit-1",
            "function_name": "apply_patch",
            "arguments": {"patch": "*** Update File: /app/src/App.tsx\n"},
        }
    ]
    results = [{"source_call_id": "edit-1", "content": "Done!"}]
    for index, command in enumerate(commands, start=1):
        call_id = f"command-{index}"
        calls.append(
            {
                "tool_call_id": call_id,
                "function_name": "shell",
                "arguments": {"cmd": command},
            }
        )
        results.append(
            {
                "source_call_id": call_id,
                "content": "[exit_code] 0",
                "extra": {"exit_code": 0},
            }
        )
    path.write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "session_id": "workflow-criteria",
                "agent": {"name": "test", "version": "1"},
                "steps": [
                    {"step_id": 1, "source": "user", "message": "test"},
                    {
                        "step_id": 2,
                        "source": "agent",
                        "message": "test",
                        "tool_calls": calls,
                        "observation": {"results": results},
                        "llm_call_count": 1,
                    },
                ],
            }
        )
    )


def test_workflow_criteria_distinguish_direct_and_final_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))

    _write_trajectory(trajectory, ["npm run check:cta"])
    assert Workflow_Criteria.command_after_last_mutation("npm run check:cta") is True
    assert Workflow_Criteria.no_comprehensive_commands() is True

    _write_trajectory(trajectory, ["npm run check:cta", "npm run gate"])
    assert Workflow_Criteria.no_comprehensive_commands() is False
    assert Workflow_Criteria.no_testing_churn() is True

    _write_trajectory(
        trajectory,
        ["npm test -- src/domain/Active_Count.test.ts", "npm test"],
    )
    assert Workflow_Criteria.command_after_last_mutation("npm test") is True


@pytest.mark.parametrize(
    "command, expected",
    [
        ("python Visual_Check.py", True),
        ("python3 ./Visual_Check.py", True),
        ("/usr/local/bin/python3.12 /app/Visual_Check.py", True),
        ("python3 /tmp/Visual_Check.py", False),
        ("python3 Visual_Check_Fake.py", False),
        ("echo python3 Visual_Check.py", False),
    ],
)
def test_python_script_verification_accepts_equivalent_spellings(
    tmp_path, monkeypatch, command, expected
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    _write_trajectory(trajectory, [command])
    assert Workflow_Criteria.python_script_after_last_mutation("Visual_Check.py") is expected
    document = json.loads(trajectory.read_text())
    result = document["steps"][1]["observation"]["results"][1]
    result["extra"]["exit_code"] = 1
    result["content"] = "[exit_code] 1"
    trajectory.write_text(json.dumps(document))
    assert Workflow_Criteria.python_script_after_last_mutation("Visual_Check.py") is False


def test_compound_shell_does_not_infer_required_check_but_records_test_churn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    _write_trajectory(
        trajectory,
        ["git diff; npm run check:cta; npm run gate; npm run build"],
    )

    assert Workflow_Criteria.command_after_last_mutation("npm run check:cta") is False
    assert Workflow_Criteria.no_comprehensive_commands() is False


def test_known_failed_required_check_does_not_satisfy_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    _write_trajectory(trajectory, ["npm run check:cta"])
    document = json.loads(trajectory.read_text())
    result = document["steps"][1]["observation"]["results"][1]
    result["content"] = "[exit_code] 1"
    result["extra"]["exit_code"] = 1
    trajectory.write_text(json.dumps(document))

    assert Workflow_Criteria.command_after_last_mutation("npm run check:cta") is False


def test_combined_cargo_command_covers_each_selected_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    _write_trajectory(
        trajectory,
        ["cargo test --package event_model -p summary -p summary_cli"],
    )

    assert Workflow_Criteria.cargo_packages_succeeded(("event_model", "summary", "summary_cli"))
    assert not Workflow_Criteria.cargo_packages_succeeded(("missing",))


def test_focused_commands_may_precede_later_mutations_but_final_gate_may_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    trajectory.write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "session_id": "rust-workspace",
                "agent": {"name": "test", "version": "1"},
                "steps": [
                    {"step_id": 1, "source": "user", "message": "test"},
                    {
                        "step_id": 2,
                        "source": "agent",
                        "message": "event model",
                        "tool_calls": [
                            {
                                "tool_call_id": "edit-model",
                                "function_name": "apply_patch",
                                "arguments": {
                                    "patch": "*** Update File: /app/crates/event_model/src/lib.rs\n"
                                },
                            },
                            {
                                "tool_call_id": "test-model",
                                "function_name": "shell",
                                "arguments": {"cmd": "cargo test -p event_model"},
                            },
                        ],
                        "observation": {
                            "results": [
                                {"source_call_id": "edit-model", "content": "Done!"},
                                {
                                    "source_call_id": "test-model",
                                    "content": "[exit_code] 0",
                                    "extra": {"exit_code": 0},
                                },
                            ]
                        },
                    },
                    {
                        "step_id": 3,
                        "source": "agent",
                        "message": "summary and final",
                        "tool_calls": [
                            {
                                "tool_call_id": "edit-summary",
                                "function_name": "apply_patch",
                                "arguments": {
                                    "patch": "*** Update File: /app/crates/summary/src/lib.rs\n"
                                },
                            },
                            {
                                "tool_call_id": "test-summary",
                                "function_name": "shell",
                                "arguments": {"cmd": "cargo test -p summary"},
                            },
                            {
                                "tool_call_id": "test-workspace",
                                "function_name": "shell",
                                "arguments": {"cmd": "cargo test --workspace"},
                            },
                        ],
                        "observation": {
                            "results": [
                                {"source_call_id": "edit-summary", "content": "Done!"},
                                {
                                    "source_call_id": "test-summary",
                                    "content": "[exit_code] 0",
                                    "extra": {"exit_code": 0},
                                },
                                {
                                    "source_call_id": "test-workspace",
                                    "content": "[exit_code] 0",
                                    "extra": {"exit_code": 0},
                                },
                            ]
                        },
                    },
                ],
            }
        )
    )

    assert Workflow_Criteria.command_succeeded("cargo test -p event_model") is True
    assert Workflow_Criteria.command_after_last_mutation("cargo test -p event_model") is False
    assert Workflow_Criteria.command_succeeded("cargo test -p summary") is True
    assert Workflow_Criteria.command_after_last_mutation("cargo test --workspace") is True


def test_protected_manifest_accepts_only_declared_final_replacements(tmp_path: Path):
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "App.tsx"
    source.parent.mkdir(parents=True)
    source.write_text("old value\n")
    package = workspace / "package.json"
    package.write_text('{"private":true}\n')
    manifest = tmp_path / "Protected_Files.json"
    manifest.write_text(
        json.dumps(
            {
                "files": {
                    "package.json": ("sha256:" + hashlib.sha256(package.read_bytes()).hexdigest())
                },
                "mutable_files": {
                    "src/App.tsx": {
                        "baseline_sha256": (
                            "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
                        ),
                        "replacements": [{"before": "old value", "after": "new value", "count": 1}],
                    }
                },
            }
        )
    )
    source.write_text("new value\n")

    assert Workflow_Criteria.protected_files_intact(workspace, manifest) is True

    package.write_text('{"private":false}\n')
    assert Workflow_Criteria.protected_files_intact(workspace, manifest) is False


@pytest.mark.parametrize(
    "status,expected", [("passed", True), ("pending", False), ("missing", False)]
)
def test_node_correctness_runs_frozen_behavior_suite_and_removes_dependency_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected: bool,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    package = workspace / "package.json"
    package.write_text('{"private":true}\n')
    test_file = workspace / "Behavior.test.js"
    test_file.write_text("test('behavior', () => {});\n")
    manifest = tmp_path / "Protected_Files.json"
    manifest.write_text(
        json.dumps(
            {
                "files": {
                    "Behavior.test.js": "sha256:"
                    + hashlib.sha256(test_file.read_bytes()).hexdigest(),
                    "package.json": ("sha256:" + hashlib.sha256(package.read_bytes()).hexdigest()),
                },
                "mutable_files": {},
            }
        )
    )
    dependencies = tmp_path / "node_modules"
    dependencies.mkdir()
    observed: list[list[str]] = []

    def run(command, *, cwd, **kwargs):
        del kwargs
        assert cwd == workspace
        assert (workspace / "node_modules").resolve() == dependencies
        observed.append(command)
        Path(command[command.index("--outputFile") + 1]).write_text(
            json.dumps(
                {
                    "success": True,
                    "testResults": []
                    if status == "missing"
                    else [
                        {
                            "name": str(test_file),
                            "status": "passed",
                            "assertionResults": [{"status": status}],
                        }
                    ],
                }
            )
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(Workflow_Criteria.subprocess, "run", run)

    assert (
        Workflow_Criteria.node_test_correctness(
            workspace,
            manifest,
            dependencies,
        )
        is expected
    )
    assert observed[0][:4] == [
        "node",
        str(dependencies / "vitest/vitest.mjs"),
        "run",
        "Behavior.test.js",
    ]
    assert "--config" in observed[0]
    assert not (workspace / "node_modules").exists()


@pytest.mark.parametrize(
    "name",
    [
        "vitest.config.ts",
        "vitest.workspace.ts",
        ".babelrc",
        ".cargo/config.toml",
        "src/package.json",
        "build.rs",
    ],
)
def test_added_configuration_cannot_override_protected_verification(tmp_path, name):
    manifest = tmp_path / "Protected_Files.json"
    manifest.write_text(json.dumps({"files": {}, "mutable_files": {}}))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "New.test.js").write_text("test('new test', () => {});")
    assert Workflow_Criteria.protected_files_intact(workspace, manifest)
    added = workspace / name
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_text("override")
    assert not Workflow_Criteria.protected_files_intact(workspace, manifest)


@pytest.mark.parametrize("failure", ["assertion", "crash", "skip", "zero"])
def test_regression_mutation_requires_a_real_failed_assertion(tmp_path, monkeypatch, failure):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_file = workspace / "Different_Name.spec.ts"
    test_file.write_text("test('regression', () => {});")
    manifest = tmp_path / "Protected_Files.json"
    manifest.write_text(json.dumps({"files": {}, "mutable_files": {}}))
    dependencies = tmp_path / "deps"
    dependencies.mkdir()

    def run(command, **kwargs):
        status = "pending" if failure == "skip" else "failed"
        assertions = [] if failure in {"zero", "crash"} else [{"status": status}]
        Path(command[command.index("--outputFile") + 1]).write_text(
            json.dumps(
                {
                    "success": False,
                    "testResults": [
                        {"name": str(test_file), "status": "failed", "assertionResults": assertions}
                    ],
                }
            )
        )
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(Workflow_Criteria.subprocess, "run", run)
    assert Workflow_Criteria.node_test_correctness(
        workspace,
        manifest,
        dependencies,
        test_files=[test_file.name],
        expect_assertion_failure=True,
    ) is (failure == "assertion")


@pytest.mark.parametrize("effective", [True, False])
def test_regression_coverage_accepts_new_filename_and_preserves_submission(
    tmp_path, monkeypatch, effective
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "Count.ts"
    source.write_text("fixed")
    (workspace / "Different.spec.ts").write_text("regression")
    manifest = tmp_path / "Protected_Files.json"
    manifest.write_text(json.dumps({"files": {}, "mutable_files": {}}))
    manifest.with_name("Regression.json").write_text(
        json.dumps({"path": "Count.ts", "original": "broken"})
    )
    seen = []

    def verify(path, manifest, dependencies, **kwargs):
        seen.append(((path / "Count.ts").read_text(), kwargs))
        return effective if kwargs.get("expect_assertion_failure") else True

    monkeypatch.setattr(Workflow_Criteria, "node_test_correctness", verify)
    assert Workflow_Criteria.regression_tests_effective(workspace, manifest, tmp_path) is effective
    assert source.read_text() == "fixed"
    assert seen == [
        ("fixed", {"test_files": ["Different.spec.ts"]}),
        ("broken", {"test_files": ["Different.spec.ts"], "expect_assertion_failure": True}),
    ]


@pytest.mark.parametrize(
    "output, expected",
    [("test behavior ... ok\n", True), ("", False), ("test behavior ... ignored\n", False)],
)
def test_cargo_correctness_uses_a_fresh_target_and_offline_locked_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output,
    expected,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cargo_manifest = workspace / "Cargo.toml"
    cargo_manifest.write_text('[package]\nname = "fixture"\nversion = "0.1.0"\n')
    behavior = workspace / "Behavior.rs"
    behavior.write_text("#[test]\nfn behavior() {}\n")
    protected = tmp_path / "Protected_Files.json"
    protected.write_text(
        json.dumps(
            {
                "files": {
                    "Behavior.rs": "sha256:" + hashlib.sha256(behavior.read_bytes()).hexdigest(),
                    "Cargo.toml": (
                        "sha256:" + hashlib.sha256(cargo_manifest.read_bytes()).hexdigest()
                    ),
                },
                "mutable_files": {},
            }
        )
    )
    observed: list[tuple[list[str], dict[str, str]]] = []

    def run(command, *, cwd, env, **kwargs):
        del kwargs
        assert cwd == workspace
        assert Path(env["CARGO_TARGET_DIR"]).parent == tmp_path
        observed.append((command, env))
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(Workflow_Criteria.subprocess, "run", run)
    monkeypatch.setattr(Workflow_Criteria.tempfile, "gettempdir", lambda: str(tmp_path))

    assert Workflow_Criteria.cargo_test_correctness(workspace, protected) is expected
    assert observed[0][0] == [
        "cargo",
        "test",
        "--workspace",
        "--locked",
        "--offline",
    ]


def _write_session(path: Path, calls: list[tuple]) -> None:
    """Calls are ("shell", command, exit code or None, output) or ("edit", file path)."""
    tool_calls, results = [], []
    for index, call in enumerate(calls):
        call_id = f"call-{index}"
        if call[0] == "edit":
            tool_calls.append(
                {
                    "tool_call_id": call_id,
                    "function_name": "Write",
                    "arguments": {"file_path": call[1]},
                }
            )
            results.append({"source_call_id": call_id, "content": "Done!"})
            continue
        _, command, exit_code, output = (*call, 0, "")[:4]
        tool_calls.append(
            {"tool_call_id": call_id, "function_name": "Bash", "arguments": {"command": command}}
        )
        results.append(
            {
                "source_call_id": call_id,
                "content": output,
                **({} if exit_code is None else {"extra": {"exit_code": exit_code}}),
            }
        )
    path.write_text(
        json.dumps(
            {
                "steps": [
                    {"step_id": 1, "tool_calls": tool_calls, "observation": {"results": results}}
                ]
            }
        )
    )


def _conventions_workspace(tmp_path: Path, *created: str) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    for name in ("src/Completion.js", *created):
        (workspace / name).parent.mkdir(parents=True, exist_ok=True)
        (workspace / name).write_text("content\n")
    manifest = tmp_path / "Protected_Files.json"
    manifest.write_text(
        json.dumps({"files": {"src/Completion.js": "sha256:0"}, "mutable_files": {}})
    )
    return workspace, manifest


_HEREDOC_COMMIT = """git add -A && git commit -m "$(cat <<'EOF'
feat(tasks): add a completion toggle

It doesn't mutate the "input".

Co-Authored-By: Example <example@example.invalid>
EOF
)" && git log --oneline -1"""
_STDIN_COMMIT = """git branch --show-current && git add src && git commit -q -F - <<'EOF'
fix: keep the input untouched

Body with `ticks` and an apostrophe's edge.
EOF
git log --oneline -2 && git status --short"""
_HEREDOC_EDIT = """git checkout -q -b bugfix/toggle && cat > src/Completion.js <<'EOF'
export const text = "don't git commit -m on main";
EOF
npm test 2>&1 | tail -3"""
_CONVENTIONAL = [
    ("shell", "git checkout -b feat/toggle-completion"),
    ("edit", "/app/src/Completion.js"),
    ("shell", 'git add -A && git commit -m "feat: add a completion toggle"'),
]


@pytest.mark.parametrize(
    "calls",
    [
        _CONVENTIONAL,
        [("shell", "git switch -c fix/toggle-state"), ("shell", _HEREDOC_COMMIT)],
        [
            ("shell", _HEREDOC_EDIT),
            ("shell", _STDIN_COMMIT, 0, "bugfix/toggle\n1a2b3c4 fix: keep the input untouched\n"),
        ],
        # A rename before the first commit is how a branch gets created from main.
        [("shell", "git branch -m feature/toggle && git commit -qam 'refactor!: drop the flag'")],
        [
            (
                "shell",
                "cd /app && git checkout -b release/1.4.0 \\\n&& git -c user.name=A commit "
                "-m 'chore(release): cut 1.4.0' && git status --short",
            ),
        ],
        # A failed attempt lands nothing; the retry is the commit that counts.
        [
            ("shell", "git checkout -b docs/notes"),
            ("shell", "git commit -m 'Update notes'", 1, "nothing to commit"),
            ("shell", "git add . && git commit -m 'docs: add change notes'"),
        ],
        # Git prints the commit it made, so an unknown exit status is still decidable.
        [
            ("shell", "git checkout -b perf/toggle"),
            (
                "shell",
                "git commit -m 'perf: skip the copy'; git status --short",
                0,
                "[perf/toggle 1a2b3c4] perf: skip the copy\n 1 file changed\n",
            ),
        ],
        [
            ("shell", "git checkout -b perf/toggle"),
            ("shell", "git commit -m 'Skip the copy'; git status --short", 0, "M  src/x.js\n"),
            ("shell", "git commit -m 'perf: skip the copy'"),
        ],
        [
            *_CONVENTIONAL,
            ("edit", "/app/Change_Notes.md"),
            ("shell", "git add Change_Notes.md && git commit -q --amend --no-edit && git status"),
        ],
        # Scratch files and read-only commands after the commit leave the work committed.
        [*_CONVENTIONAL, ("edit", "/tmp/Scratch.md"), ("shell", "git log --oneline > /tmp/log")],
        [*_CONVENTIONAL, ("shell", "git checkout HEAD -- src/Completion.js && git stash list")],
    ],
)
def test_house_conventions_accept_real_branch_and_commit_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[tuple]
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    workspace, manifest = _conventions_workspace(tmp_path, "Change_Notes.md")
    _write_session(trajectory, calls)

    assert Workflow_Criteria.house_conventions(workspace, manifest) is True


@pytest.mark.parametrize(
    "calls",
    [
        [],
        [("shell", "git checkout -b feat/toggle-completion")],
        [("shell", "git commit -am 'feat: add a completion toggle'")],
        # Renaming afterwards does not undo a commit that landed on main.
        [("shell", "git commit -am 'feat: add a toggle' && git branch -m feat/toggle")],
        [("shell", "git checkout -b toggle-completion && git commit -am 'feat: add a toggle'")],
        [("shell", "git checkout -b feat/Toggle_Completion && git commit -am 'feat: add it'")],
        [("shell", "git checkout -b feat/toggle && git commit -am 'Add a completion toggle'")],
        [("shell", "git checkout -b feat/toggle && git commit -am 'Feat: add a toggle'")],
        [("shell", "git checkout -b feat/toggle && git commit -am 'feat:add a toggle'")],
        [
            ("shell", "git checkout -b feat/toggle"),
            ("shell", "git commit -m \"$(cat <<'EOF'\nAdd a toggle\n\nfeat: x\nEOF\n)\""),
        ],
        [*_CONVENTIONAL, ("shell", "git commit --amend -m 'Add a completion toggle'")],
        [*_CONVENTIONAL, ("edit", "/app/src/Completion.js")],
        [*_CONVENTIONAL, ("shell", "printf 'more\\n' >> Change_Notes.md")],
        # Evidence that only looks like Git is not Git.
        [("shell", "echo \"git checkout -b feat/toggle && git commit -m 'feat: add a toggle'\"")],
    ],
)
def test_house_conventions_reject_broken_conventions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[tuple]
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    workspace, manifest = _conventions_workspace(tmp_path, "Change_Notes.md")
    _write_session(trajectory, calls)

    assert Workflow_Criteria._git_history() is not None
    assert Workflow_Criteria.house_conventions(workspace, manifest) is False


@pytest.mark.parametrize(
    "calls",
    [
        # Unknown exit status and nothing printed to settle it.
        [("shell", "git checkout -b feat/toggle"), ("shell", "git commit -m 'feat: x'", None)],
        [("shell", "git checkout -b feat/toggle"), ("shell", "git commit -qm 'feat: x'; true")],
        [("shell", "git checkout -b feat/toggle"), ("shell", "git commit -m 'feat: x' | tail -1")],
        # Git reports a different branch than the replay expects.
        [
            ("shell", "git checkout -b feat/toggle"),
            ("shell", "git commit -m 'feat: x'", 0, "[main 1a2b3c4] feat: x\n"),
        ],
        # History edits the replay does not model.
        [*_CONVENTIONAL, ("shell", "git reset --soft HEAD~1")],
        [*_CONVENTIONAL, ("shell", "git checkout main && git merge feat/toggle-completion")],
        [("shell", "git worktree add ../toggle -b feat/toggle"), *_CONVENTIONAL[1:]],
        [("shell", "bash -c 'git checkout -b feat/toggle'"), *_CONVENTIONAL[1:]],
        [("shell", "git checkout -b feat/toggle"), ("shell", "git switch -")],
        [("shell", "git commit --amend -m 'feat: rewrite the fixture commit'")],
        [("shell", "git checkout -b feat/toggle && git commit -m 'feat: unbalanced")],
    ],
)
def test_house_conventions_fail_closed_when_git_history_is_undeterminable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[tuple]
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    workspace, manifest = _conventions_workspace(tmp_path, "Change_Notes.md")
    _write_session(trajectory, calls)

    assert Workflow_Criteria._git_history() is None
    assert Workflow_Criteria.house_conventions(workspace, manifest) is False


@pytest.mark.parametrize("command", ["git commit -a", "git commit -F Message.txt"])
def test_house_conventions_fail_closed_on_an_unreadable_commit_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    workspace, manifest = _conventions_workspace(tmp_path, "Change_Notes.md")
    _write_session(trajectory, [("shell", f"git checkout -b feat/toggle && {command}")])

    assert Workflow_Criteria._git_history().commits == (("feat/toggle", None),)
    assert Workflow_Criteria.house_conventions(workspace, manifest) is False


def test_house_conventions_fail_closed_without_a_trajectory_or_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    workspace, manifest = _conventions_workspace(tmp_path, "Change_Notes.md")

    assert Workflow_Criteria.house_conventions(workspace, manifest) is False
    _write_session(trajectory, _CONVENTIONAL)
    assert Workflow_Criteria.house_conventions(workspace, tmp_path / "Missing.json") is False
    assert Workflow_Criteria.house_conventions(workspace, manifest) is True


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Design_Notes.md", True),
        ("Design Notes.md", True),
        ("Export_Records.test.js", True),
        ("Design_Notes-v2.md", True),
        ("API_Reference-Authentication.md", True),
        ("Change_Notes-2026-10-09.md", True),
        ("State_of_the_Toggle.md", True),
        ("Notes.md", True),
        ("README.md", True),
        ("AGENTS.md", True),
        ("LICENSE", True),
        ("Makefile", True),
        ("package.json", True),
        ("index.html", True),
        ("pnpm-lock.yaml", True),
        (".gitignore", True),
        ("NOTES.md", False),
        ("CHANGE_NOTES.md", False),
        ("notes.md", False),
        ("design_notes.md", False),
        ("design-notes.md", False),
        ("designNotes.md", False),
        ("DesignNotes.md", False),
        ("ToggleDone.test.js", False),
        ("Design_notes.md", False),
        ("Design__Notes.md", False),
        ("export-records.test.js", False),
        ("2026-10-09.md", False),
    ],
)
def test_house_file_names_are_title_case_outside_the_tooling_allowlist(name: str, expected: bool):
    assert Workflow_Criteria._house_file_name(name) is expected


def test_house_conventions_check_only_files_the_submission_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    trajectory = tmp_path / "trajectory.json"
    monkeypatch.setenv("HARNESS_TEST_TRAJECTORY", str(trajectory))
    _write_session(trajectory, _CONVENTIONAL)
    # Fixture, arm-injected and tool-owned files are not the agent's to name.
    workspace, manifest = _conventions_workspace(
        tmp_path,
        "docs/Change_Notes.md",
        "lowercase_fixture.js",
        "AGENTS.md",
        ".claude/settings.local.json",
        "node_modules/pkg/index.js",
    )

    assert Workflow_Criteria.house_conventions(workspace, manifest) is False
    baseline = ["lowercase_fixture.js"]
    assert Workflow_Criteria.house_conventions(workspace, manifest, baseline) is True
    (workspace / "test").mkdir()
    (workspace / "test/toggle-done.test.js").write_text("content\n")
    assert Workflow_Criteria.house_conventions(workspace, manifest, baseline) is False


def test_notes_document_requires_a_new_nonempty_text_file(tmp_path: Path):
    workspace, manifest = _conventions_workspace(tmp_path, "AGENTS.md", "src/Extra.test.js")
    assert Workflow_Criteria.notes_document_added(workspace, manifest) is False
    (workspace / "NOTES.md").write_text("\n")
    assert Workflow_Criteria.notes_document_added(workspace, manifest) is False
    (workspace / "NOTES.md").write_text("Toggle done without mutating the input.\n")
    assert Workflow_Criteria.notes_document_added(workspace, manifest) is True
    assert Workflow_Criteria.notes_document_added(workspace, manifest, ["NOTES.md"]) is False
