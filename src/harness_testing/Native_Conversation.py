"""Trial-local stdio driver for pinned native provider control protocols.

Uploaded with Scripted_User and Trial_Evidence; only Python's stdlib is needed in
containers. Provider credentials stay in the adapter's existing scoped lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path

if __package__:
    from .External_Codex import external_evidence, preflight_external_codex
    from .Scripted_User import select_reply, terminal_approval_request, validate_policy
    from .Trial_Evidence import (
        ClaudeBackgroundTasks,
        collect_trial_evidence,
        executor_condition,
        merge_external_evidence,
        read_codex_transcripts,
    )
else:
    from External_Codex import external_evidence, preflight_external_codex
    from Scripted_User import select_reply, terminal_approval_request, validate_policy
    from Trial_Evidence import (
        ClaudeBackgroundTasks,
        collect_trial_evidence,
        executor_condition,
        merge_external_evidence,
        read_codex_transcripts,
    )

_REMOTE_DIR = "/tmp/Harness_Native_Conversation"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def capture_committed_patch(workspace: Path, base_commit: str, destination: Path) -> None:
    """Write the upstream committed-only submission artifact without grading it."""
    if not _COMMIT.fullmatch(base_commit):
        raise ValueError("artifact_patch_base_commit_invalid")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as artifact:
        subprocess.run(
            ("git", "diff", "--binary", base_commit, "HEAD"),
            cwd=workspace,
            check=True,
            stdout=artifact,
            stderr=subprocess.DEVNULL,
        )


def validate_conversation(config: dict, provider: str) -> None:
    validate_policy(config["policy"])
    if type(config.get("timeout_seconds")) not in (int, float) or config["timeout_seconds"] <= 0:
        raise ValueError("native_timeout_invalid: positive timeout_seconds required")
    expected = "openai" if provider == "codex" else "anthropic"
    for entry in config.get("executor_inventory", []):
        if entry.get("provider") not in {"openai", "anthropic"}:
            raise ValueError("executor_provider_invalid")
        if (
            entry["provider"] == expected
            and config.get("runtime_version")
            and entry.get("runtime_version") != config["runtime_version"]
        ):
            raise ValueError("executor_runtime_version_mismatch")
        if entry["provider"] != expected and not (
            provider == "claude" and entry["provider"] == "openai"
        ):
            raise ValueError(
                "external_claude_adapter_unavailable: frozen Harness implements external Codex only"
            )


def approved_hooks_from_bundle(bundle: Path) -> list[dict]:
    """Freeze the native command-hook definitions and every plugin file digest."""
    provenance = json.loads((bundle / "Provenance.json").read_text())
    approved = []
    for surface in provenance.get("delivery_surfaces", []):
        if surface.get("surface") != "codex-plugin":
            continue
        relative = Path(surface["path"]).relative_to("/harness-arm")
        plugin = bundle / relative
        manifest_path = plugin / ".codex-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text())
        declarations = manifest.get("hooks")
        if declarations is None and (plugin / "hooks/hooks.json").exists():
            declarations = "./hooks/hooks.json"
        if not declarations:
            continue
        specs = []
        sources = declarations if isinstance(declarations, list) else [declarations]
        for declaration in sources:
            source = manifest_path
            if isinstance(declaration, str):
                source = (plugin / declaration).resolve()
                if not source.is_relative_to(plugin.resolve()):
                    raise ValueError("native_hook_source_escapes_plugin")
                declaration = json.loads(source.read_text())
            if not isinstance(declaration, dict) or not isinstance(declaration.get("hooks"), dict):
                raise ValueError("native_hook_definition_invalid")
            for event, groups in declaration["hooks"].items():
                for group in groups:
                    for hook in group["hooks"]:
                        if hook.get("type") != "command":
                            raise ValueError("native_hook_handler_unsupported")
                        specs.append(
                            {
                                "event": event[0].lower() + event[1:],
                                "command": hook["command"],
                                "matcher": group.get("matcher") or None,
                                "timeout": hook.get("timeout", hook.get("timeout_sec")),
                                "source": source.relative_to(plugin.resolve()).as_posix()
                                if source.is_absolute()
                                else source.relative_to(plugin).as_posix(),
                            }
                        )
        prefix = relative.as_posix() + "/"
        files = {
            key.removeprefix(prefix): digest
            for key, digest in provenance["generated_file_digests"].items()
            if key.startswith(prefix)
        }
        approved.append({"plugin_path": surface["path"], "files": files, "hooks": specs})
    return approved


def hook_trust_edits(
    approved: list[dict], result: dict, *, verify: dict | None = None
) -> list[dict]:
    """Match frozen local definitions to native keys/hashes; trust no other source."""
    listed = []
    for entry in result.get("data", []):
        if entry.get("errors") or entry.get("warnings"):
            raise ValueError("native_hook_discovery_incomplete")
        listed.extend(entry.get("hooks", []))
    edits = []
    matched = set()
    for plugin in approved:
        root = Path(plugin["plugin_path"])
        if not root.is_relative_to("/harness-arm/codex/provider-home/plugins/cache"):
            raise ValueError("native_hook_source_not_approved")
        for relative, digest in plugin["files"].items():
            path = root / relative
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("native_hook_file_escapes_plugin")
            data = (
                f"symlink:{os.readlink(path)}".encode() if path.is_symlink() else path.read_bytes()
            )
            if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("native_hook_bundle_changed")
        aliases = [
            root,
            Path("/tmp/codex-home") / root.relative_to("/harness-arm/codex/provider-home"),
        ]
        for spec in plugin["hooks"]:
            candidates = [
                hook
                for hook in listed
                if hook.get("source") == "plugin"
                and any(
                    hook.get("sourcePath") == str(alias / spec["source"])
                    and hook.get("command")
                    in {
                        spec["command"],
                        spec["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(alias)),
                    }
                    for alias in aliases
                )
                and hook.get("eventName") == spec["event"]
                and (hook.get("matcher") or None) == spec["matcher"]
                and (spec["timeout"] is None or hook.get("timeoutSec") == spec["timeout"])
            ]
            candidates = [hook for hook in candidates if hook.get("key") not in matched]
            if len(candidates) != 1:
                raise ValueError("native_hook_definition_mismatch")
            hook = candidates[0]
            key, digest = hook.get("key"), hook.get("currentHash")
            if not key or not digest:
                raise ValueError("native_hook_identity_missing")
            matched.add(key)
            if verify is not None and (
                verify.get(key) != digest
                or not hook.get("enabled")
                or hook.get("trustStatus") != "trusted"
            ):
                raise ValueError("native_hook_trust_not_effective")
            edits.append(
                {
                    "keyPath": "hooks.state." + json.dumps(key),
                    "mergeStrategy": "replace",
                    "value": {"enabled": True, "trusted_hash": digest},
                }
            )
    # Unexpected plugin/user/project hooks change the approved startup behavior.
    if any(hook.get("key") not in matched for hook in listed):
        raise ValueError("unapproved_native_hook_discovered")
    return edits


async def stage_controller(environment, config: dict) -> str:
    """Stage code and nonsecret frozen trial inputs outside the task workspace."""
    result = await environment.exec(f"mkdir -p {_REMOTE_DIR}", user="root")
    if result.return_code:
        raise RuntimeError("native_controller_staging_failed")
    for name in (
        "Native_Conversation.py",
        "Scripted_User.py",
        "Trial_Evidence.py",
        "External_Codex.py",
    ):
        await environment.upload_file(Path(__file__).with_name(name), f"{_REMOTE_DIR}/{name}")
    descriptor, name = tempfile.mkstemp(prefix="Harness_Native_Conversation_")
    source = Path(name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(config, handle)
        await environment.upload_file(source, f"{_REMOTE_DIR}/Trial_Config.json")
    finally:
        source.unlink(missing_ok=True)
    owner = (
        f"chown -R {shlex.quote(str(environment.default_user))} {_REMOTE_DIR} && "
        if environment.default_user is not None
        else ""
    )
    result = await environment.exec(
        f"{owner}chmod 700 {_REMOTE_DIR} && chmod 600 {_REMOTE_DIR}/*", user="root"
    )
    if result.return_code:
        raise RuntimeError("native_controller_staging_failed")
    return f"python3 {_REMOTE_DIR}/Native_Conversation.py {_REMOTE_DIR}/Trial_Config.json"


async def remove_controller(environment) -> None:
    result = await environment.exec(f"rm -rf -- {_REMOTE_DIR}", user="root")
    if result.return_code:
        raise RuntimeError("native_controller_cleanup_failed")


class Conversation:
    """Native wire state, with explicit root identity and deterministic replies."""

    def __init__(self, config: dict):
        self.config = config
        self.provider = config["provider"]
        self.root = config.get("root_session_id")
        self.status = "pending"
        self.reason = None
        self.interactions = 0
        self.counter = 0
        self.pending = {}
        self.identities = {}
        self.active_turns = {}
        self.background_tasks = ClaudeBackgroundTasks()
        self.text = ""
        self.decisions = []
        self.models = []
        self.root_finished = False
        self.hook_trust = None

    def rpc(self, method, params):
        self.counter += 1
        self.pending[self.counter] = method
        return {"id": self.counter, "method": method, "params": params}

    def start(self):
        if self.provider == "codex":
            return [
                self.rpc(
                    "initialize",
                    {
                        "clientInfo": {"name": "harness_comparison", "version": "1"},
                        "capabilities": {"experimentalApi": True},
                    },
                )
            ]
        self.root = self.root or str(uuid.uuid4())
        return [
            {
                "type": "control_request",
                "request_id": "initialize",
                "request": {"subtype": "initialize"},
            }
        ]

    def turn(self, text):
        self.text = ""
        if self.provider == "codex":
            return self.rpc(
                "turn/start",
                {
                    "threadId": self.root,
                    "model": self.config["model"],
                    "effort": self.config["effort"],
                    "input": [{"type": "text", "text": text, "text_elements": []}],
                },
            )
        return {
            "type": "user",
            "session_id": self.root,
            "message": {"role": "user", "content": text},
            "parent_tool_use_id": None,
        }

    def reply(self, text):
        result = select_reply(
            {"kind": "clarification", "text": text}, self.config["policy"], self.interactions
        )
        if result["status"] == "task_definition_gap":
            approval = select_reply(
                {"kind": "approval", "text": text}, self.config["policy"], self.interactions
            )
            if approval["status"] == "reply" or (
                approval["status"] == "authority_denied"
                and terminal_approval_request(text) == "external"
            ):
                result = approval
        if result["status"] == "reply":
            self.interactions += 1
        self.decisions.append({"interaction": self.interactions, **result})
        return result

    def fail(self, reason, status="infrastructure_failure"):
        self.status, self.reason = status, reason
        return []

    def finish_turn(self):
        reply = self.reply(self.text.strip())
        if reply["status"] == "reply":
            return [self.turn(reply["reply"])]
        request_kind = terminal_approval_request(self.text)
        if request_kind is not None:
            return self.fail(reply["status"], "task_definition_gap")
        if "?" in self.text or re.search(r"\b(awaiting|waiting for|need your)\b", self.text, re.I):
            return self.fail(reply["status"], "task_definition_gap")
        self.root_finished = True
        self.status = (
            "pending" if self.active_turns or self.background_tasks.pending else "completed"
        )
        return []

    def check_models(self, models):
        native_provider = "openai" if self.provider == "codex" else "anthropic"
        required = [{"model": self.config["model"], "effort": self.config["effort"]}] + [
            entry
            for entry in self.config.get("executor_inventory", [])
            if entry["provider"] == native_provider
        ]
        catalog = {}
        for model in models:
            for field in ("model", "id", "value", "resolvedModel"):
                if model.get(field):
                    catalog[model[field]] = model
        for entry in required:
            found = catalog.get(entry["model"])
            if not found:
                self.fail("executor_model_unavailable:" + entry["model"])
                return False
            levels = found.get("supportedReasoningEfforts", found.get("supportedEffortLevels", []))
            levels = [x.get("reasoningEffort") if isinstance(x, dict) else x for x in levels]
            if levels and entry.get("effort") not in levels:
                self.fail("executor_effort_unavailable:" + entry["model"])
                return False
        return True

    def handle(self, event):
        observed = {}
        if self.provider == "codex" and event.get("method") == "item/completed":
            item = event.get("params", {}).get("item", {})
            if item.get("type") == "collabAgentToolCall" and item.get("tool") == "spawnAgent":
                observed = {
                    session: {"model": item.get("model"), "effort": item.get("reasoningEffort")}
                    for session in item.get("receiverThreadIds", [])
                }
        elif self.provider == "claude" and event.get("type") == "assistant":
            session = (
                event.get("agentId")
                or event.get("sessionId")
                or event.get("session_id")
                or self.root
            )
            if event.get("parent_tool_use_id") and session == self.root:
                session = "unresolved:" + str(event["parent_tool_use_id"])
            if session != self.root:
                observed[session] = {"model": event.get("message", {}).get("model"), "effort": None}
        for session, identity in observed.items():
            self.identities.setdefault(session, {}).update(
                {k: v for k, v in identity.items() if v is not None}
            )
            if "executor_inventory" in self.config:
                inventory = self.config["executor_inventory"] + [
                    {
                        "provider": "openai" if self.provider == "codex" else "anthropic",
                        "model": self.config["model"],
                        "effort": self.config["effort"],
                    }
                ]
                reason = executor_condition(
                    "openai" if self.provider == "codex" else "anthropic",
                    self.identities[session],
                    inventory,
                )
                if reason == "executor_condition_mismatch":
                    return self.fail(reason)
        return self.handle_codex(event) if self.provider == "codex" else self.handle_claude(event)

    def start_thread(self):
        args = {
            "cwd": self.config.get("cwd", "/app"),
            "model": self.config["model"],
            "config": {"model_reasoning_effort": self.config["effort"]},
            "approvalPolicy": "never",
            "sandbox": "danger-full-access",
        }
        if self.root:
            args["threadId"] = self.root
            return [self.rpc("thread/resume", args)]
        args.update({"ephemeral": False, "allowProviderModelFallback": False})
        return [self.rpc("thread/start", args)]

    def handle_codex(self, event):
        method, params = event.get("method"), event.get("params", {})
        if method is None and "id" in event:
            requested = self.pending.pop(event["id"], None)
            if event.get("error"):
                return self.fail("native_rpc_error:" + str(requested))
            result = event.get("result", {})
            if requested == "initialize":
                return [
                    {"method": "initialized", "params": {}},
                    self.rpc("model/list", {"includeHidden": True, "limit": 100}),
                ]
            if requested == "model/list":
                self.models.extend(result.get("data", []))
                if result.get("nextCursor"):
                    return [
                        self.rpc(
                            "model/list",
                            {"includeHidden": True, "limit": 100, "cursor": result["nextCursor"]},
                        )
                    ]
                if not self.check_models(self.models):
                    return []
                if "approved_hooks" in self.config:
                    return [self.rpc("hooks/list", {"cwds": [self.config.get("cwd", "/app")]})]
                return self.start_thread()
            if requested == "hooks/list":
                try:
                    edits = hook_trust_edits(
                        self.config["approved_hooks"], result, verify=self.hook_trust
                    )
                except ValueError as error:
                    return self.fail(str(error))
                if self.hook_trust is not None or not edits:
                    return self.start_thread()
                self.hook_trust = {
                    json.loads(edit["keyPath"].removeprefix("hooks.state.")): edit["value"][
                        "trusted_hash"
                    ]
                    for edit in edits
                }
                return [self.rpc("config/batchWrite", {"edits": edits, "reloadUserConfig": True})]
            if requested == "config/batchWrite":
                return [self.rpc("hooks/list", {"cwds": [self.config.get("cwd", "/app")]})]
            if requested in {"thread/start", "thread/resume"}:
                root = result.get("thread", {}).get("id")
                if not root or (self.root and root != self.root):
                    return self.fail("root_session_identity_mismatch")
                if (
                    result.get("model") != self.config["model"]
                    or result.get("reasoningEffort") != self.config["effort"]
                ):
                    return self.fail("kickoff_identity_mismatch")
                self.root = root
                self.identities[root] = {
                    "model": result["model"],
                    "effort": result["reasoningEffort"],
                    "provider": result.get("modelProvider"),
                }
                return [self.turn(self.config["instruction"])]
            return []
        if method == "item/tool/requestUserInput":
            answers = {}
            for question in params.get("questions", []):
                reply = self.reply(question.get("question", ""))
                if reply["status"] != "reply":
                    self.fail(reply["status"], "task_definition_gap")
                    return [
                        {
                            "id": event["id"],
                            "error": {
                                "code": -32000,
                                "message": "No authored benchmark-user answer",
                            },
                        }
                    ]
                answers[question["id"]] = {"answers": [reply["reply"]]}
            return [{"id": event["id"], "result": {"answers": answers}}]
        if "id" in event and method:
            self.fail("native_authority_request_denied", "task_definition_gap")
            return [
                {
                    "id": event["id"],
                    "error": {
                        "code": -32000,
                        "message": "Benchmark user cannot grant tool authority",
                    },
                }
            ]
        if method == "turn/started":
            self.active_turns[params["threadId"]] = params["turn"]["id"]
        if method == "item/completed" and params.get("threadId") == self.root:
            item = params.get("item", {})
            if item.get("type") == "agentMessage":
                self.text = item.get("text", "")
        if method == "turn/completed":
            self.active_turns.pop(params.get("threadId"), None)
            if params.get("threadId") == self.root:
                if params.get("turn", {}).get("status") != "completed":
                    return self.fail("native_turn_failed", "agent_failed")
                return self.finish_turn()
            if self.root_finished and not self.active_turns:
                self.status = "completed"
        return []

    def handle_claude(self, event):
        self.background_tasks.observe(event)
        if self.root_finished and not self.background_tasks.pending:
            self.status = "completed"
        if event.get("type") == "control_response":
            response = event.get("response", {})
            if response.get("request_id") == "initialize":
                if response.get("subtype") != "success":
                    return self.fail("native_initialization_failed")
                if not self.check_models(response.get("response", {}).get("models", [])):
                    return []
                return [self.turn(self.config["instruction"])]
        if event.get("type") == "control_request":
            request = event.get("request", {})
            outcome = {
                "behavior": "deny",
                "message": "Benchmark user cannot grant tool authority",
                "interrupt": True,
            }
            if (
                request.get("subtype") == "can_use_tool"
                and request.get("tool_name") == "AskUserQuestion"
            ):
                original = request.get("input", {})
                answers = {}
                for question in original.get("questions", []):
                    reply = self.reply(question.get("question", ""))
                    if reply["status"] != "reply":
                        self.fail(reply["status"], "task_definition_gap")
                        break
                    answers[question["question"]] = reply["reply"]
                else:
                    outcome = {
                        "behavior": "allow",
                        "updatedInput": {**original, "answers": answers},
                    }
            else:
                self.fail("native_authority_request_denied", "task_definition_gap")
            return [
                {
                    "type": "control_response",
                    "response": {
                        "subtype": "success",
                        "request_id": event["request_id"],
                        "response": outcome,
                    },
                }
            ]
        if event.get("type") == "system" and event.get("subtype") == "init":
            if event.get("session_id") != self.root or event.get("model") != self.config["model"]:
                return self.fail("kickoff_identity_mismatch")
            self.identities[self.root] = {"model": event["model"], "effort": None}
        if event.get("type") == "assistant" and not event.get("parent_tool_use_id"):
            self.text = "\n".join(
                item.get("text", "")
                for item in event.get("message", {}).get("content", [])
                if item.get("type") == "text"
            )
        if event.get("type") == "result":
            if event.get("is_error") or event.get("subtype") != "success":
                return self.fail("native_turn_failed", "agent_failed")
            self.text = event.get("result") or self.text
            return self.finish_turn()
        return []

    def interrupt(self):
        if self.provider == "codex":
            return [
                self.rpc("turn/interrupt", {"threadId": thread, "turnId": turn})
                for thread, turn in self.active_turns.items()
            ]
        return [
            {
                "type": "control_request",
                "request_id": "interrupt",
                "request": {"subtype": "interrupt"},
            }
        ]


def _terminate_tree(process):
    # Linux children can start their own process groups; retain their PIDs before
    # terminating the native parent so reparenting cannot hide detached children.
    descendants = {process.pid}
    proc = Path("/proc")
    if proc.exists():
        parents = {}
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                parents[int(entry.name)] = int(
                    (entry / "stat").read_text().rsplit(")", 1)[1].split()[1]
                )
            except (OSError, ValueError, IndexError):
                continue
        while True:
            found = {pid for pid, parent in parents.items() if parent in descendants}
            if found <= descendants:
                break
            descendants |= found
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    for pid in descendants:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    # Kill remaining members after the leader exits as well. Darwin can report
    # EPERM for a group whose leader was just killed; Linux uses ESRCH.
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)


def run_controller(config: dict) -> dict:
    """Run a bounded native process; always retain stdout, stderr and evidence."""
    state = Conversation(config)
    log_dir = Path(config.get("log_dir", "/logs/agent"))
    log_dir.mkdir(parents=True, exist_ok=True)
    started, events, process = time.monotonic(), [], None
    trial_started = None
    finished = None
    incomplete = []
    outgoing = log_dir / "Native_Requests.jsonl"
    stdout = log_dir / ("claude-code.txt" if state.provider == "claude" else "codex.txt")
    stderr = log_dir / "Native_Stderr.txt"
    try:
        validate_conversation(config, state.provider)
        version = subprocess.run(
            [config["command"][0], "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        if config.get("runtime_version") and config["runtime_version"] not in version.split():
            raise ValueError("runtime_version_mismatch")
        external = [
            row
            for row in config.get("executor_inventory", [])
            if row["provider"] == "openai" and state.provider == "claude"
        ]
        native_env = os.environ.copy()
        if external:
            binary = shutil.which("codex")
            if not binary or not config.get("external_codex_home"):
                raise ValueError("external_codex_credentials_or_binary_missing")
            native_env["CODEX_HOME"] = config["external_codex_home"]
            preflight_external_codex(binary, external, native_env)
            config["external_codex_binary"] = binary
            config_path = Path(_REMOTE_DIR) / "Trial_Config.json"
            config_path.write_text(json.dumps(config))
            wrapper_dir = Path(_REMOTE_DIR) / "bin"
            wrapper_dir.mkdir(exist_ok=True)
            wrapper = wrapper_dir / "codex"
            wrapper.write_text(
                "#!/bin/sh\nexec python3 " + _REMOTE_DIR + '/External_Codex.py "$@"\n'
            )
            wrapper.chmod(0o700)
            native_env.update(
                {
                    "PATH": str(wrapper_dir) + os.pathsep + native_env["PATH"],
                    "HARNESS_CODEX_BIN": str(wrapper),
                    "HARNESS_NATIVE_CONFIG": str(config_path),
                }
            )
        initial = state.start()
        (log_dir / "Root_Identity.json").write_text(
            json.dumps(
                {"root_session_id": state.root, "deadline": started + config["timeout_seconds"]}
            )
        )
        command = list(config["command"])
        if state.provider == "claude":
            command += ["--resume" if config.get("root_session_id") else "--session-id", state.root]
        with (
            stderr.open("a") as errors,
            stdout.open("a") as capture,
            outgoing.open("a") as requests,
        ):
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=errors,
                cwd=config.get("cwd", "/app"),
                start_new_session=True,
                env=native_env,
            )
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            buffer = b""

            def send(messages):
                nonlocal trial_started
                for message in messages:
                    if (
                        message.get("method") in {"thread/start", "thread/resume", "turn/start"}
                        or message.get("type") == "user"
                    ) and time.monotonic() >= started + config["timeout_seconds"]:
                        raise TimeoutError("trial_time_limit")
                    if trial_started is None and (
                        message.get("method") in {"thread/start", "thread/resume"}
                        or message.get("type") == "user"
                    ):
                        trial_started = time.monotonic()
                    line = json.dumps(message) + "\n"
                    requests.write(line)
                    requests.flush()
                    process.stdin.write(line.encode())
                    process.stdin.flush()

            send(initial)
            while state.status == "pending":
                if time.monotonic() - started >= config["timeout_seconds"]:
                    state.fail("trial_time_limit", "timeout")
                    break
                if not selector.select(timeout=min(0.2, config["timeout_seconds"])):
                    if process.poll() is not None:
                        state.fail("native_process_exited_without_terminal_event", "agent_failed")
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    state.fail("native_process_exited_without_terminal_event", "agent_failed")
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    capture.write(line.decode(errors="replace") + "\n")
                    capture.flush()
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        incomplete.append("malformed_native_event")
                        continue
                    if not isinstance(event, dict):
                        incomplete.append("malformed_native_event")
                        continue
                    events.append(event)
                    if state.status == "pending":
                        send(state.handle(event))
            # Interrupt known active turns before killing the contained process tree.
            with suppress(BrokenPipeError, OSError):
                send(state.interrupt())
            _terminate_tree(process)
            finished = time.monotonic()
            remaining = buffer + process.stdout.read()
            if remaining:
                capture.write(remaining.decode(errors="replace"))
                for line in remaining.splitlines():
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            events.append(event)
                    except (ValueError, UnicodeDecodeError):
                        incomplete.append("malformed_native_event")
            selector.close()
    except TimeoutError:
        state.fail("trial_time_limit", "timeout")
    except Exception as error:
        # Provider stderr remains local; do not copy exception text containing
        # arbitrary tool output or credential paths into the reportable status.
        reason = str(error).split(":", 1)[0] if isinstance(error, ValueError) else ""
        state.fail(
            reason
            if re.fullmatch(r"[a-z_]+", reason)
            else "native_controller_failed:" + type(error).__name__
        )
    finally:
        if process is not None and process.poll() is None:
            _terminate_tree(process)
        if state.provider == "claude":
            session_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(log_dir / "sessions")))
            for path in sorted(session_dir.glob("projects/**/*.jsonl")):
                for line in path.read_text(errors="replace").splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        incomplete.append("malformed_session_transcript")
                        continue
                    if isinstance(event, dict):
                        events.append(event)
        if state.provider == "codex":
            session_dir = Path(os.environ.get("CODEX_HOME", "/tmp/codex-home")) / "sessions"
            retained, observed = read_codex_transcripts(session_dir, state.root)
            events.extend(retained)
            for session, identity in observed.items():
                state.identities.setdefault(session, {}).update(
                    {key: value for key, value in identity.items() if value is not None}
                )
        if state.active_turns:
            incomplete.append("unresolved_active_turn")
        base_commit = config.get("artifact_patch_base_commit")
        if base_commit is not None:
            try:
                capture_committed_patch(
                    Path(config.get("cwd", "/app")),
                    str(base_commit),
                    Path("/logs/artifacts/model.patch"),
                )
            except (OSError, subprocess.CalledProcessError, ValueError):
                incomplete.append("committed_patch_capture_failed")
        evidence = collect_trial_evidence(
            state.provider,
            events,
            root_session_id=state.root,
            status=state.status,
            duration_seconds=(finished or time.monotonic()) - (trial_started or started),
            identities=state.identities,
            incomplete_reasons=incomplete
            + ([state.reason] if state.reason == "executor_condition_mismatch" else []),
            executor_inventory=(
                config["executor_inventory"]
                + [
                    {
                        "provider": "openai" if state.provider == "codex" else "anthropic",
                        "model": config["model"],
                        "effort": config["effort"],
                    }
                ]
            )
            if "executor_inventory" in config
            else None,
        )
        if config.get("external_codex_home"):
            sessions = Path(config["external_codex_home"]) / "sessions"
            if sessions.is_dir():
                shutil.copytree(sessions, log_dir / "external_sessions", dirs_exist_ok=True)
        evidence = merge_external_evidence(evidence, external_evidence(log_dir))
        evidence.update(
            {
                "contender_id": config.get("contender_id"),
                "terminal_reason": state.reason,
                "runtime_version": config.get("runtime_version"),
                "interaction_count": state.interactions,
                "child_count": max(0, len(evidence["sessions"]) - 1),
                "provisioning_seconds": (trial_started or started) - started,
            }
        )
        (log_dir / "Trial_Evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        (log_dir / "Scripted_User_Decisions.json").write_text(
            json.dumps(state.decisions, indent=2) + "\n"
        )
    return evidence


if __name__ == "__main__":

    def interrupted(signum, frame):
        raise TimeoutError("controller interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    run_controller(json.loads(Path(sys.argv[1]).read_text()))
