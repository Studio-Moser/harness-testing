"""Local native usage evidence; raw identities never belong in public reports.

Codex exposes cumulative session usage, not request IDs. Its monotonic deltas are
identified as such; Claude message updates replace one leaf's authoritative usage.
Root result summaries are reconciliation evidence only and are never added.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

_TOKEN_FIELDS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _usage(raw: dict, provider: str) -> dict:
    if provider == "claude":
        return dict(
            zip(
                _TOKEN_FIELDS,
                (
                    _count(raw.get("input_tokens")),
                    _count(raw.get("cache_read_input_tokens", 0)),
                    _count(raw.get("cache_creation_input_tokens", 0)),
                    _count(raw.get("output_tokens")),
                ),
                strict=True,
            )
        )
    total = _count(raw.get("inputTokens", raw.get("input_tokens")))
    cached = _count(raw.get("cachedInputTokens", raw.get("cached_input_tokens", 0)))
    written = _count(raw.get("cacheWriteInputTokens", raw.get("cache_write_input_tokens", 0)))
    return dict(
        zip(
            _TOKEN_FIELDS,
            (
                total - cached - written
                if None not in (total, cached, written) and total >= cached + written
                else None,
                cached,
                written,
                _count(raw.get("outputTokens", raw.get("output_tokens"))),
            ),
            strict=True,
        )
    )


def executor_condition(provider, identity, inventory):
    """Validate observed native identity without substituting requested values."""
    models = [
        row
        for row in inventory
        if row.get("provider") == provider and row.get("model") == identity.get("model")
    ]
    if not identity.get("model"):
        return "executor_model_unverified"
    if not models:
        return "executor_condition_mismatch"
    if identity.get("effort") is None:
        return "executor_effort_unverified"
    if not any(row.get("effort") == identity["effort"] for row in models):
        return "executor_condition_mismatch"
    return None


class ClaudeBackgroundTasks:
    """Track native terminal evidence separately from launch-tool acknowledgments."""

    def __init__(self):
        self.background_tools = set()
        self.task_by_tool = {}
        self.statuses = {}

    def observe(self, event):
        message = event.get("message", {})
        content = message.get("content", []) if isinstance(message, dict) else []
        for item in content if isinstance(content, list) else []:
            if (
                isinstance(item, dict)
                and item.get("type") == "tool_use"
                and item.get("name") in {"Agent", "Task"}
                and item.get("input", {}).get("run_in_background") is True
            ):
                self.background_tools.add(item.get("id"))
        if event.get("type") != "system":
            return
        subtype = event.get("subtype")
        if subtype not in {"task_started", "task_progress", "task_notification", "task_updated"}:
            return
        task = event.get("task_id")
        if not isinstance(task, str):
            return
        if event.get("tool_use_id"):
            self.task_by_tool[event["tool_use_id"]] = task
        status = (
            event.get("patch", {}).get("status")
            if subtype == "task_updated"
            else event.get("status")
        )
        if status in {"completed", "failed", "stopped", "killed"}:
            self.statuses[task] = status
        else:
            self.statuses.setdefault(task, "running")

    @property
    def pending(self):
        terminal = {"completed", "failed", "stopped", "killed"}
        return {task for task, status in self.statuses.items() if status not in terminal} | {
            "tool:" + str(tool)
            for tool in self.background_tools
            if self.statuses.get(self.task_by_tool.get(tool)) not in terminal
        }

    @property
    def interrupted(self):
        return any(status in {"failed", "stopped", "killed"} for status in self.statuses.values())


def collect_trial_evidence(
    provider: str,
    events: list[dict],
    *,
    root_session_id: str | None,
    status: str,
    duration_seconds: float,
    identities: dict | None = None,
    incomplete_reasons: list[str] | None = None,
    executor_inventory: list[dict] | None = None,
) -> dict:
    """Collect one explicit root tree. Repeated collection is deterministic.

    model_usage is the reportable token aggregate (exclusive ordinary input).
    calls/sessions/root_session_id are local provenance. session_usage uses safe
    root/child ordinals and does not reveal provider session or request IDs.
    """
    identities = {key: dict(value) for key, value in (identities or {}).items()}
    reasons = set(incomplete_reasons or [])
    if not root_session_id:
        reasons.add("missing_root_session")
    root = root_session_id or "unknown"
    identities.setdefault(root, {})
    parents = {root: None}
    leaves: dict[tuple, dict] = {}
    cumulative: dict[str, dict] = {}
    # Persisted Claude child events establish the identity of forwarded messages.
    message_sessions = {
        e["message"]["id"]: e["agentId"]
        for e in events
        if isinstance(e.get("message"), dict) and e["message"].get("id") and e.get("agentId")
    }
    started_tools, finished_tools = set(), set()
    background = ClaudeBackgroundTasks()
    for event in events:
        if provider == "claude":
            background.observe(event)
            message = event.get("message", {})
            if not isinstance(message, dict):
                continue
            for content in (
                message.get("content", []) if isinstance(message.get("content"), list) else []
            ):
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "tool_use" and content.get("name") in {"Agent", "Task"}:
                    started_tools.add(content.get("id"))
                if content.get("type") == "tool_result":
                    finished_tools.add(content.get("tool_use_id"))
            if event.get("type") != "assistant" or not message.get("id"):
                continue
            session = (
                message_sessions.get(message["id"])
                or event.get("agentId")
                or event.get("sessionId")
                or event.get("session_id")
                or root
            )
            if event.get("parent_tool_use_id") and session == root:
                session = "unresolved:" + str(event["parent_tool_use_id"])
                reasons.add("missing_child_transcript")
            parents.setdefault(session, root if session != root else None)
            model = message.get("model")
            identities.setdefault(session, {})["model"] = model
            key = (provider, session, message["id"])
            raw = message.get("usage")
            if raw is None:
                # Tool-only renderings can repeat a billed message without usage.
                if key in leaves:
                    continue
                raw = {}
            leaves[key] = {
                "session_id": session,
                "parent_session_id": parents[session],
                "provider": "anthropic",
                "request_id": message["id"],
                "identity_kind": "message",
                "model": model,
                "effort": identities[session].get("effort"),
                **_usage(raw, provider),
            }
            continue
        params = event.get("params", {})
        if not isinstance(params, dict):
            continue
        method = event.get("method")
        if method == "thread/started":
            thread = params.get("thread", {})
            session = thread.get("id")
            if session:
                parent = thread.get("parentThreadId")
                source = thread.get("source", {})
                if isinstance(source, dict):
                    sub = source.get("subAgent", {})
                    if isinstance(sub, dict):
                        parent = parent or sub.get("thread_spawn", {}).get("parent_thread_id")
                parents[session] = parent or (root if session != root else None)
                if thread.get("forkedFromId"):
                    reasons.add("fork_usage_scope_unverified")
        if method in {"item/started", "item/completed"}:
            item = params.get("item", {})
            if item.get("type") == "collabAgentToolCall":
                for session in item.get("receiverThreadIds", []):
                    parents.setdefault(session, item.get("senderThreadId") or root)
                    if method == "item/completed" and item.get("tool") == "spawnAgent":
                        # Pinned spawn completion uses the effective child snapshot.
                        identities.setdefault(session, {}).update(
                            {
                                key: value
                                for key, value in {
                                    "model": item.get("model"),
                                    "effort": item.get("reasoningEffort"),
                                }.items()
                                if value is not None
                            }
                        )
                if item.get("tool") == "spawnAgent":
                    if method == "item/started":
                        started_tools.add(item.get("id"))
                    elif item.get("status") == "completed":
                        finished_tools.add(item.get("id"))
                for session, child in item.get("agentsStates", {}).items():
                    identities.setdefault(session, {})["terminal_status"] = child.get("status")
                    if child.get("status") in {"errored", "notFound"}:
                        reasons.add("failed_child_usage_unverified")

        if method != "thread/tokenUsage/updated":
            continue
        session = params.get("threadId")
        if not session:
            reasons.add("missing_usage_identity")
            continue
        parents.setdefault(session, root if session != root else None)
        raw = params.get("tokenUsage", {}).get("total", {})
        current = _usage(raw, provider)
        previous = cumulative.get(session, dict.fromkeys(_TOKEN_FIELDS, 0))
        if any(current[k] is None for k in _TOKEN_FIELDS):
            reasons.add("partial_call_usage")
            continue
        if all(current[k] <= previous[k] for k in _TOKEN_FIELDS):
            continue  # Duplicate or replayed historical snapshot.
        if any(current[k] < previous[k] for k in _TOKEN_FIELDS):
            reasons.add("nonmonotonic_usage")
            continue
        cumulative[session] = current
        snapshot = ":".join(str(current[k]) for k in _TOKEN_FIELDS)
        identity = identities.get(session, {})
        leaves[(provider, session, snapshot)] = {
            "session_id": session,
            "parent_session_id": parents[session],
            "provider": "openai",
            "request_id": None,
            "usage_update_id": snapshot,
            "identity_kind": "cumulative_delta",
            "cumulative_usage": current,
            "turn_id": params.get("turnId"),
            "model": identity.get("model"),
            "effort": identity.get("effort"),
            **{k: current[k] - previous[k] for k in _TOKEN_FIELDS},
        }
    if background.pending:
        reasons.add("missing_background_terminal")
    if background.interrupted:
        reasons.add("interrupted_background_task")
    if started_tools - finished_tools:
        reasons.add("unresolved_child_start")
    children = set(parents) - {root}
    if len(children) < len(started_tools):
        reasons.add("missing_child_transcript")
    calls = list(leaves.values())
    if executor_inventory is not None:
        native_provider = "openai" if provider == "codex" else "anthropic"
        for session in children:
            reason = executor_condition(
                native_provider, identities.get(session, {}), executor_inventory
            )
            if reason:
                reasons.add(reason)
    if set(parents) - {c["session_id"] for c in calls}:
        reasons.add("missing_session_usage")
    if any(c.get("model") is None or any(c[k] is None for k in _TOKEN_FIELDS) for c in calls):
        reasons.add("partial_call_usage")
    # An interrupted provider request may have incurred unreported tokens.
    if status != "completed":
        reasons.add("interrupted_or_failed_trial")
    groups: dict[tuple, list] = defaultdict(list)
    session_groups: dict[tuple, list] = defaultdict(list)
    ordinals = {
        session: "root" if session == root else f"child_{index}"
        for index, session in enumerate([root] + sorted(children))
    }
    for call in calls:
        groups[(call["provider"], call["model"])].append(call)
        session_groups[
            (ordinals[call["session_id"]], call["provider"], call["model"], call["effort"])
        ].append(call)

    def total(rows, field):
        return (
            sum(row[field] for row in rows) if all(row[field] is not None for row in rows) else None
        )

    return {
        "schema_version": "1",
        "root_session_id": root_session_id,
        "status": status,
        "duration_seconds": duration_seconds,
        "usage_complete": bool(calls) and not reasons,
        "incomplete_reasons": sorted(reasons),
        "calls": calls,
        "sessions": [
            {"session_id": session, "parent_session_id": parent, **identities.get(session, {})}
            for session, parent in parents.items()
        ],
        "model_usage": [
            {"provider": key[0], "model": key[1], **{k: total(rows, k) for k in _TOKEN_FIELDS}}
            for key, rows in groups.items()
        ],
        "session_usage": [
            {
                "session": key[0],
                "provider": key[1],
                "model": key[2],
                "effort": key[3],
                **{k: total(rows, k) for k in _TOKEN_FIELDS},
            }
            for key, rows in session_groups.items()
        ],
    }


def read_codex_transcripts(session_dir, root_session_id):
    """Select an explicit root and descendants, never newest-file or --last."""
    import json

    records, parents = {}, {}
    for path in sorted(session_dir.rglob("*.jsonl")):
        events = []
        for line in path.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        metadata = next(
            (e.get("payload", {}) for e in events if e.get("type") == "session_meta"), {}
        )
        session = metadata.get("id")
        if not session:
            continue
        source = metadata.get("source", {})
        sub = source.get("subagent", source.get("subAgent", {})) if isinstance(source, dict) else {}
        spawn = sub.get("thread_spawn", {}) if isinstance(sub, dict) else {}
        parents[session] = metadata.get("parent_thread_id") or spawn.get("parent_thread_id")
        records[session] = events
    selected = {root_session_id}
    while True:
        children = {session for session, parent in parents.items() if parent in selected}
        if children <= selected:
            break
        selected |= children
    normalized, identities = [], {}
    for session in sorted(selected):
        if session not in records:
            continue
        normalized.append(
            {
                "method": "thread/started",
                "params": {"thread": {"id": session, "parentThreadId": parents[session]}},
            }
        )
        for event in records[session]:
            payload = event.get("payload", {})
            if event.get("type") == "turn_context":
                identities[session] = {
                    "model": payload.get("model"),
                    "effort": payload.get("effort"),
                }
            if event.get("type") == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                if info.get("total_token_usage"):
                    normalized.append(
                        {
                            "method": "thread/tokenUsage/updated",
                            "params": {
                                "threadId": session,
                                "turnId": payload.get("turn_id"),
                                "tokenUsage": {"total": info["total_token_usage"]},
                            },
                        }
                    )
    return normalized, identities


def merge_external_evidence(trial: dict, external: list[dict]) -> dict:
    """Add independently observed calls once; preserve the root clock/status."""
    if not external:
        return trial
    result = dict(trial)
    result["calls"] = list(trial["calls"])
    result["sessions"] = list(trial["sessions"])
    reasons = set(trial["incomplete_reasons"])
    for child in external:
        for call in child["calls"]:
            record = dict(call)
            if record["session_id"] == child["root_session_id"]:
                record.update(
                    parent_session_id=trial["root_session_id"], parent_relationship="trial_root"
                )
            result["calls"].append(record)
        for session in child["sessions"]:
            record = dict(session)
            if record["session_id"] == child["root_session_id"]:
                record.update(
                    parent_session_id=trial["root_session_id"], parent_relationship="trial_root"
                )
            result["sessions"].append(record)
        reasons.update(child["incomplete_reasons"])
    # Independently observed deltas can overlap. Reconcile their cumulative
    # endpoints across the session first, then derive each disjoint interval.
    calls, cumulative = {}, defaultdict(dict)
    for call in result["calls"]:
        session = (call["provider"], call["session_id"])
        if call.get("identity_kind") == "cumulative_delta":
            endpoint = call.get("cumulative_usage")
            if not isinstance(endpoint, dict) or any(
                _count(endpoint.get(k)) is None for k in _TOKEN_FIELDS
            ):
                reasons.add("missing_cumulative_endpoint")
            else:
                key = tuple(endpoint[k] for k in _TOKEN_FIELDS)
                previous = cumulative[session].get(key)
                if previous and previous["model"] != call["model"]:
                    reasons.add("conflicting_cumulative_model")
                cumulative[session][key] = call
                continue
        calls[(*session, call.get("request_id") or call.get("usage_update_id"))] = call
    for session, endpoints in cumulative.items():
        previous = dict.fromkeys(_TOKEN_FIELDS, 0)
        for key, call in sorted(endpoints.items(), key=lambda item: (sum(item[0]), item[0])):
            current = call["cumulative_usage"]
            if any(current[k] < previous[k] for k in _TOKEN_FIELDS):
                reasons.add("nonmonotonic_usage")
                continue
            calls[(*session, key)] = {
                **call,
                **{k: current[k] - previous[k] for k in _TOKEN_FIELDS},
            }
            previous = current
    result["calls"] = list(calls.values())
    sessions = {row["session_id"]: row for row in result["sessions"]}
    result["sessions"] = list(sessions.values())
    groups = defaultdict(list)
    session_groups = defaultdict(list)
    ordered = [trial["root_session_id"]] + sorted(set(sessions) - {trial["root_session_id"]})
    ordinals = {
        session: "root" if index == 0 else f"child_{index}" for index, session in enumerate(ordered)
    }
    for call in result["calls"]:
        groups[(call["provider"], call["model"])].append(call)
        session_groups[
            (ordinals[call["session_id"]], call["provider"], call["model"], call.get("effort"))
        ].append(call)

    def tokens(rows):
        return {
            field: sum(row[field] for row in rows)
            if all(row[field] is not None for row in rows)
            else None
            for field in _TOKEN_FIELDS
        }

    result["model_usage"] = [
        {"provider": key[0], "model": key[1], **tokens(rows)} for key, rows in groups.items()
    ]
    result["session_usage"] = [
        {"session": key[0], "provider": key[1], "model": key[2], "effort": key[3], **tokens(rows)}
        for key, rows in session_groups.items()
    ]
    result["incomplete_reasons"] = sorted(reasons)
    result["usage_complete"] = (
        trial["usage_complete"] and not reasons and all(row["usage_complete"] for row in external)
    )
    return result
