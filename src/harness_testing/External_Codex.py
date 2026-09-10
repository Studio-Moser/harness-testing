"""Observe Harness's native external Codex stdio seam without replacing it.

HARNESS_CODEX_BIN and PATH point to this transparent wrapper. Authority, prompts,
review snapshots and completion decisions remain owned by the frozen dispatcher.
"""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path


def _messages(process, timeout):
    """Read a single native response with a bounded stdio buffer."""
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    buffer = b""
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if not selector.select(min(0.2, max(0, deadline - time.monotonic()))):
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                return
            buffer += chunk
            if len(buffer) > 16 * 1024 * 1024:
                raise ValueError("external_protocol_line_limit")
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                yield json.loads(line)
        raise ValueError("external_catalog_timeout")
    finally:
        selector.close()


def preflight_external_codex(binary: str, inventory: list[dict], env: dict) -> None:
    """Verify pinned executable and its own model catalog without a model turn."""
    env = {
        key: value for key, value in env.items() if not key.startswith(("ANTHROPIC_", "CLAUDE_"))
    }
    version = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=True, timeout=10, env=env
    ).stdout.split()
    if any(row.get("runtime_version") not in version for row in inventory):
        raise ValueError("external_runtime_version_mismatch")
    process = subprocess.Popen(
        [binary, "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:

        def send(event):
            process.stdin.write((json.dumps(event) + "\n").encode())
            process.stdin.flush()

        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "harness_external_preflight", "version": "1"}},
            }
        )
        models = []
        for event in _messages(process, 15):
            if event.get("error"):
                raise ValueError("external_catalog_unavailable")
            if event.get("id") == 1:
                send({"method": "initialized", "params": {}})
                send(
                    {
                        "id": 2,
                        "method": "model/list",
                        "params": {"includeHidden": True, "limit": 100},
                    }
                )
            if event.get("id") == 2:
                result = event.get("result", {})
                models.extend(result.get("data", []))
                if result.get("nextCursor"):
                    send(
                        {
                            "id": 2,
                            "method": "model/list",
                            "params": {
                                "includeHidden": True,
                                "limit": 100,
                                "cursor": result["nextCursor"],
                            },
                        }
                    )
                    continue
                for row in inventory:
                    model = next(
                        (item for item in models if item.get("model") == row["model"]), None
                    )
                    if model is None:
                        raise ValueError("external_model_unavailable")
                    levels = [
                        item["reasoningEffort"]
                        for item in model.get("supportedReasoningEfforts", [])
                    ]
                    if levels and row["effort"] not in levels:
                        raise ValueError("external_effort_unavailable")
                return
        raise ValueError("external_catalog_unavailable")
    finally:
        process.terminate()
        process.wait(timeout=5)


def validate_external_request(event: dict, inventory: list[dict]) -> None:
    """Admit only frozen model/effort work; never rewrite authority or prompts."""
    method = event.get("method")
    if method in {"thread/start", "thread/resume"} and event.get("params", {}).get("model") not in {
        row["model"] for row in inventory
    }:
        raise ValueError("external_model_not_approved")
    if method == "turn/start":
        params = event.get("params", {})
        if (params.get("model"), params.get("effort")) not in {
            (row["model"], row["effort"]) for row in inventory
        }:
            raise ValueError("external_model_effort_not_approved")
    if method and method not in {
        "initialize",
        "initialized",
        "thread/start",
        "thread/resume",
        "thread/read",
        "turn/start",
        "turn/interrupt",
        "model/list",
    }:
        raise ValueError("external_control_method_not_approved")


def observe_codex(config: dict, arguments: list[str], *, stdin=None, stdout=None) -> int:
    """Proxy app-server bytes, retaining every native event before forwarding it."""
    binary = config["external_codex_binary"]
    if arguments != ["app-server", "--stdio"]:
        # Actual Harness's model-free executable/schema probes pass unchanged.
        if arguments in [["--version"], ["--help"]] or arguments[:2] == [
            "app-server",
            "generate-json-schema",
        ]:
            return subprocess.call(
                [binary, *arguments],
                env={
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith(("ANTHROPIC_", "CLAUDE_"))
                },
            )
        raise ValueError("external_codex_transport_unsupported")
    stdin, stdout = stdin or sys.stdin.buffer, stdout or sys.stdout.buffer
    directory = Path(config.get("log_dir", "/logs/agent")) / "executors" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    runtime = json.loads(
        (Path(config.get("log_dir", "/logs/agent")) / "Root_Identity.json").read_text()
    )
    (directory / "Ownership.json").write_text(
        json.dumps(
            {
                "root_session_id": runtime["root_session_id"],
                "parent_relationship": "trial_root",
                "provider": "codex",
            }
        )
    )
    inventory = [row for row in config["executor_inventory"] if row["provider"] == "openai"]
    process = subprocess.Popen(
        [binary, *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("ANTHROPIC_", "CLAUDE_"))
        },
    )
    selector = selectors.DefaultSelector()
    selector.register(stdin, selectors.EVENT_READ, "request")
    selector.register(process.stdout, selectors.EVENT_READ, "event")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"request": b"", "event": b""}
    status, reason = "agent_failed", None
    active_turns, pending_turns = {}, {}
    try:
        with (
            (directory / "Trace.jsonl").open("a") as trace,
            (directory / "Stderr.txt").open("ab") as errors,
        ):
            while selector.get_map():
                if process.poll() is not None and not any(
                    key.data == "event" for key in selector.get_map().values()
                ):
                    break
                if time.monotonic() >= runtime["deadline"]:
                    status, reason = "timeout", "trial_time_limit"
                    break
                for key, _ in selector.select(0.2):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        if key.data == "request":
                            process.stdin.close()
                        continue
                    if key.data == "stderr":
                        errors.write(data)
                        errors.flush()
                        continue
                    buffers[key.data] += data
                    if len(buffers[key.data]) > 16 * 1024 * 1024:
                        raise ValueError("external_protocol_line_limit")
                    while b"\n" in buffers[key.data]:
                        line, buffers[key.data] = buffers[key.data].split(b"\n", 1)
                        event = json.loads(line)
                        if key.data == "request":
                            if time.monotonic() >= runtime["deadline"]:
                                raise TimeoutError("trial_time_limit")
                            validate_external_request(event, inventory)
                            if event.get("method") == "turn/start":
                                pending_turns[event["id"]] = event["params"]["threadId"]
                        else:
                            params = event.get("params", {})
                            if event.get("method") == "turn/started":
                                active_turns[params["threadId"]] = params["turn"]["id"]
                            if event.get("id") in pending_turns:
                                thread = pending_turns.pop(event["id"])
                                turn = event.get("result", {}).get("turn", {}).get("id")
                                if turn:
                                    active_turns[thread] = turn
                            if event.get("method") == "turn/completed":
                                active_turns.pop(params.get("threadId"), None)
                        trace.write(json.dumps({"direction": key.data, "event": event}) + "\n")
                        trace.flush()
                        if key.data == "event" and event.get("method") == "turn/completed":
                            status = (
                                "completed"
                                if event.get("params", {}).get("turn", {}).get("status")
                                == "completed"
                                else "agent_failed"
                            )
                        target = process.stdin if key.data == "request" else stdout
                        target.write(line + b"\n")
                        target.flush()
            if any(buffers.values()):
                status, reason = "infrastructure_failure", "external_truncated_protocol"
    except (ValueError, OSError, TimeoutError) as error:
        status = "timeout" if isinstance(error, TimeoutError) else "infrastructure_failure"
        reason = str(error) if isinstance(error, ValueError) else type(error).__name__
    finally:
        selector.close()
        if process.poll() is None:
            if not process.stdin.closed:
                for thread, turn in active_turns.items():
                    try:
                        process.stdin.write(
                            (
                                json.dumps(
                                    {
                                        "id": "harness-interrupt-" + uuid.uuid4().hex,
                                        "method": "turn/interrupt",
                                        "params": {"threadId": thread, "turnId": turn},
                                    }
                                )
                                + "\n"
                            ).encode()
                        )
                        process.stdin.flush()
                    except (BrokenPipeError, OSError):
                        break
            if __package__:
                from .Native_Conversation import _terminate_tree
            else:
                from Native_Conversation import _terminate_tree
            _terminate_tree(process)
        (directory / "Status.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "reason": reason,
                    "incomplete_reasons": ["unresolved_active_turn"] if active_turns else [],
                }
            )
        )
    return 0 if status == "completed" else 1


def external_evidence(log_dir: Path) -> list[dict]:
    """Collect retained proxy traces even if timeout prevented the final record."""
    if __package__:
        from .Trial_Evidence import collect_trial_evidence, read_codex_transcripts
    else:
        from Trial_Evidence import collect_trial_evidence, read_codex_transcripts
    evidence = []
    for directory in sorted((log_dir / "executors").glob("*")):
        records = []
        for line in (
            (directory / "Trace.jsonl").read_text().splitlines()
            if (directory / "Trace.jsonl").exists()
            else []
        ):
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        pending, identities, roots = {}, {}, []
        events = []
        for record in records:
            event = record["event"]
            if record["direction"] == "request":
                pending[event.get("id")] = event
                continue
            events.append(event)
            request = pending.pop(event.get("id"), {})
            if request.get("method") in {"thread/start", "thread/resume"}:
                result = event.get("result", {})
                root = result.get("thread", {}).get("id")
                if root:
                    roots.append(root)
                    identities[root] = {
                        "model": result.get("model"),
                        "effort": result.get("reasoningEffort"),
                    }
            if request.get("method") == "turn/start":
                params = request["params"]
                identities.setdefault(params["threadId"], {})["effort"] = None
                # Effort is requested only unless the response explicitly reports it.
                if event.get("result", {}).get("reasoningEffort"):
                    identities.setdefault(params["threadId"], {})["effort"] = event["result"][
                        "reasoningEffort"
                    ]
        if not roots and not any(
            record["event"].get("method") in {"thread/start", "turn/start"} for record in records
        ):
            continue  # Native availability probe; no admitted model work.
        status_path = directory / "Status.json"
        terminal = (
            json.loads(status_path.read_text()) if status_path.exists() else {"status": "timeout"}
        )
        status = terminal["status"]
        if roots:
            retained, observed = read_codex_transcripts(log_dir / "external_sessions", roots[0])
            events.extend(retained)
            for session, identity in observed.items():
                identities.setdefault(session, {}).update(
                    {key: value for key, value in identity.items() if value is not None}
                )
        result = collect_trial_evidence(
            "codex",
            events,
            root_session_id=roots[0] if roots else None,
            status=status,
            duration_seconds=0,
            identities=identities,
            incomplete_reasons=terminal.get("incomplete_reasons", []),
        )
        result["parent_relationship"] = "trial_root"
        evidence.append(result)
    return evidence


if __name__ == "__main__":

    def interrupted(signum, frame):
        raise TimeoutError("external executor interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    config = json.loads(Path(os.environ["HARNESS_NATIVE_CONFIG"]).read_text())
    try:
        sys.exit(observe_codex(config, sys.argv[1:]))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(69)
