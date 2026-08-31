"""Protected deterministic HTTP stub used by Harness contract tasks."""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class ScenarioServer(ThreadingHTTPServer):
    scenario: dict[str, Any]
    events_path: Path
    events_lock: threading.Lock


def _contains(value: object, required: object) -> bool:
    if isinstance(required, dict):
        return isinstance(value, dict) and all(
            key in value and _contains(value[key], child)
            for key, child in required.items()
        )
    if isinstance(required, list):
        if not isinstance(value, list) or len(value) != len(required):
            return False

        def match(index: int, remaining: tuple[int, ...]) -> bool:
            if index == len(required):
                return True
            return any(
                _contains(value[candidate], required[index])
                and match(index + 1, remaining[:offset] + remaining[offset + 1 :])
                for offset, candidate in enumerate(remaining)
            )

        return match(0, tuple(range(len(value))))
    if isinstance(required, bool) or isinstance(value, bool):
        return type(value) is type(required) and value == required
    return value == required


def _path_value(value: object, dotted_path: str) -> tuple[bool, object]:
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _same_json_shape(value: object, reference: object) -> bool:
    if isinstance(reference, bool):
        return isinstance(value, bool)
    if isinstance(reference, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(reference, str):
        return isinstance(value, str) and bool(value.strip())
    if isinstance(reference, list):
        return (
            isinstance(value, list)
            and (not reference or bool(value))
            and all(
                any(_same_json_shape(item, candidate) for candidate in reference)
                for item in value
            )
        )
    if isinstance(reference, dict):
        return isinstance(value, dict) and (not reference or bool(value))
    return value is None


def _valid_required_path(
    payload: object, expected_payload: object, dotted_path: str
) -> bool:
    present, value = _path_value(payload, dotted_path)
    expected_present, reference = _path_value(expected_payload, dotted_path)
    return present and expected_present and _same_json_shape(value, reference)


def _contract_action(scenario: dict[str, Any], action: object) -> dict[str, Any] | None:
    contract = scenario.get("contract")
    actions = contract.get("actions") if isinstance(contract, dict) else None
    if not isinstance(actions, list):
        return None
    return next(
        (
            item
            for item in actions
            if isinstance(item, dict) and item.get("action") == action
        ),
        None,
    )


def _available_sequences(
    calls: list[Any], completed: set[object]
) -> tuple[int, ...]:
    first = next(
        (index for index in range(1, len(calls) + 1) if index not in completed),
        None,
    )
    if first is None:
        return ()
    expected = calls[first - 1]
    group = expected.get("unordered_group") if isinstance(expected, dict) else None
    if not isinstance(group, str):
        return (first,)
    available = []
    for index in range(first, len(calls) + 1):
        call = calls[index - 1]
        if not isinstance(call, dict) or call.get("unordered_group") != group:
            break
        if index not in completed:
            available.append(index)
    return tuple(available)


def _call_matches(
    expected: object,
    action: object,
    payload: object,
    required_paths: object,
) -> bool:
    match_rule = (
        expected.get("match", expected.get("payload"))
        if isinstance(expected, dict)
        else None
    )
    shape_only = expected.get("shape_only", []) if isinstance(expected, dict) else None
    return (
        isinstance(expected, dict)
        and isinstance(payload, dict)
        and isinstance(required_paths, list)
        and isinstance(shape_only, list)
        and all(isinstance(path, str) for path in shape_only)
        and all(
            isinstance(path, str)
            and _valid_required_path(payload, expected.get("payload"), path)
            and (path in shape_only or _path_value(match_rule, path)[0])
            for path in required_paths
        )
        and action == expected.get("action")
        and _contains(payload, match_rule)
    )


class Handler(BaseHTTPRequestHandler):
    server: ScenarioServer

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, {"status": "ok"})
            return
        if self.path == "/contract":
            contract = self.server.scenario.get("contract")
            if isinstance(contract, dict):
                self._respond(200, contract)
            else:
                self._respond(500, {"error": "missing_contract"})
            return
        self._respond(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/invoke":
            self._respond(404, {"error": "not_found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(size))
        except (ValueError, json.JSONDecodeError):
            with self.server.events_lock:
                prior = self.server.events_path.read_text().splitlines()
                event = {
                    "sequence": len(prior) + 1,
                    "action": None,
                    "payload": None,
                    "matched": False,
                    "expected_sequence": None,
                }
                with self.server.events_path.open("a") as handle:
                    handle.write(
                        json.dumps(event, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    )
            self._respond(400, {"error": "invalid_json"})
            return
        action = request.get("action") if isinstance(request, dict) else None
        payload = request.get("payload") if isinstance(request, dict) else None
        public_action = _contract_action(self.server.scenario, action)
        required_paths = (
            public_action.get("required") if isinstance(public_action, dict) else None
        )
        with self.server.events_lock:
            prior = [
                json.loads(line)
                for line in self.server.events_path.read_text().splitlines()
                if line.strip()
            ]
            calls = self.server.scenario.get("calls", [])
            completed = {
                event.get("expected_sequence")
                for event in prior
                if isinstance(event, dict) and event.get("matched") is True
            }
            available = _available_sequences(calls, completed)
            expected_sequence = next(
                (
                    sequence
                    for sequence in available
                    if _call_matches(
                        calls[sequence - 1], action, payload, required_paths
                    )
                ),
                None,
            )
            expected = (
                calls[expected_sequence - 1]
                if expected_sequence is not None
                else None
            )
            event = {
                "sequence": len(prior) + 1,
                "action": action,
                "payload": payload,
                "matched": expected_sequence is not None,
                "expected_sequence": expected_sequence,
            }
            with self.server.events_path.open("a") as handle:
                handle.write(
                    json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
                )
        if expected_sequence is None:
            self._respond(
                422,
                {
                    "error": "contract_mismatch",
                    "expected_action": (
                        calls[available[0] - 1].get("action")
                        if available and isinstance(calls[available[0] - 1], dict)
                        else None
                    ),
                },
            )
            return
        self._respond(200, expected.get("response"))

    def _respond(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    arguments.events.parent.mkdir(parents=True, exist_ok=True)
    arguments.events.write_text("")
    server = ScenarioServer(("0.0.0.0", arguments.port), Handler)
    server.scenario = json.loads(arguments.scenario.read_text())
    server.events_path = arguments.events
    server.events_lock = threading.Lock()
    server.serve_forever()


if __name__ == "__main__":
    main()
