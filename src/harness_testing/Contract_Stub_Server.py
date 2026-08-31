"""Protected deterministic HTTP stub used by Harness contract tasks."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class ScenarioServer(ThreadingHTTPServer):
    scenario: dict[str, Any]
    events_path: Path


def _contains(value: object, required: object) -> bool:
    if isinstance(required, dict):
        return isinstance(value, dict) and all(
            key in value and _contains(value[key], child)
            for key, child in required.items()
        )
    return value == required


def _has_path(value: object, dotted_path: str) -> bool:
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


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
            self._respond(400, {"error": "invalid_json"})
            return
        prior = [
            json.loads(line)
            for line in self.server.events_path.read_text().splitlines()
            if line.strip()
        ]
        sequence = len(prior) + 1
        calls = self.server.scenario.get("calls", [])
        completed = {
            event.get("expected_sequence")
            for event in prior
            if isinstance(event, dict) and event.get("matched") is True
        }
        expected_sequence = next(
            (index for index in range(1, len(calls) + 1) if index not in completed),
            None,
        )
        expected = (
            calls[expected_sequence - 1]
            if expected_sequence is not None
            else None
        )
        action = request.get("action") if isinstance(request, dict) else None
        payload = request.get("payload") if isinstance(request, dict) else None
        public_action = _contract_action(self.server.scenario, action)
        required_paths = (
            public_action.get("required") if isinstance(public_action, dict) else None
        )
        matched = (
            isinstance(expected, dict)
            and isinstance(payload, dict)
            and isinstance(required_paths, list)
            and all(isinstance(path, str) and _has_path(payload, path) for path in required_paths)
            and action == expected.get("action")
            and _contains(payload, expected.get("match", expected.get("payload")))
        )
        event = {
            "sequence": sequence,
            "action": action,
            "payload": payload,
            "matched": matched,
            "expected_sequence": expected_sequence if matched else None,
        }
        with self.server.events_path.open("a") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        if not matched:
            self._respond(
                422,
                {
                    "error": "contract_mismatch",
                    "expected_action": (
                        expected.get("action") if isinstance(expected, dict) else None
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
    server.serve_forever()


if __name__ == "__main__":
    main()
