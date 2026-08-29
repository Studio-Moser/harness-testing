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


class Handler(BaseHTTPRequestHandler):
    server: ScenarioServer

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, {"status": "ok"})
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
        prior = self.server.events_path.read_text().splitlines()
        sequence = len(prior) + 1
        calls = self.server.scenario.get("calls", [])
        expected = calls[sequence - 1] if sequence <= len(calls) else None
        action = request.get("action") if isinstance(request, dict) else None
        payload = request.get("payload") if isinstance(request, dict) else None
        matched = (
            isinstance(expected, dict)
            and action == expected.get("action")
            and payload == expected.get("payload")
        )
        event = {
            "sequence": sequence,
            "action": action,
            "payload": payload,
            "matched": matched,
        }
        with self.server.events_path.open("a") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        if not matched:
            self._respond(409, {"error": "unexpected_call", "sequence": sequence})
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
