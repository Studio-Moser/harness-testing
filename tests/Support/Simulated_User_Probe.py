"""Model-free native probe. Run inside the pinned image with --network none.

Uses fake credentials and a loopback fake provider. No outbound model request.
"""

import base64
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from harness_testing import Simulated_User as user  # noqa: E402


def main():
    captured = []
    output = {"decision": "approve", "fact_ids": []}

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            import gzip

            body = self.rfile.read(int(self.headers["Content-Length"]))
            if self.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            captured.append(json.loads(body))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            item = {
                "type": "message",
                "id": "message-1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(output)}],
            }
            events = [
                {"type": "response.created", "response": {"id": "fake-response"}},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "fake-response",
                        "status": "completed",
                        "output": [item],
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 20,
                            "total_tokens": 120,
                            "input_tokens_details": {"cached_tokens": 0},
                            "output_tokens_details": {"reasoning_tokens": 0},
                        },
                    },
                },
            ]
            for event in events:
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
            self.wfile.flush()

    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        auth_dir = work / "auth"
        auth_dir.mkdir()
        claims = (
            base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "https://api.openai.com/auth": {
                            "chatgpt_account_id": "fake-account",
                            "chatgpt_plan_type": "pro",
                        }
                    }
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        (auth_dir / "auth.json").write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": "fake-access",
                        "refresh_token": "fake-refresh",
                        "id_token": "e30." + claims + ".fake",
                        "account_id": "fake-account",
                    },
                }
            )
        )
        os.environ["CODEX_HOME"] = str(auth_dir)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        original_popen = user.subprocess.Popen

        def local_only(command, **kwargs):
            if "app-server" in command:
                command = [
                    *command,
                    "-c",
                    f'chatgpt_base_url="http://127.0.0.1:{server.server_port}"',
                    "-c",
                    'model_provider="fake"',
                    "-c",
                    f'model_providers.fake.base_url="http://127.0.0.1:{server.server_port}"',
                    "-c",
                    'model_providers.fake.name="Fake local provider"',
                    "-c",
                    "model_providers.fake.supports_websockets=false",
                    "-c",
                    "model_providers.fake.requires_openai_auth=true",
                ]
            return original_popen(command, **kwargs)

        user.subprocess.Popen = local_only
        try:
            result = user._native_decision(
                {
                    "task": "Change local copy",
                    "facts": {},
                    "conversation": [],
                    "current_request": "Approve this direction?",
                },
                user.default_config(),
                30,
            )
        finally:
            user.subprocess.Popen = original_popen
            server.shutdown()
        print(
            json.dumps(
                {
                    "reason": result["reason"],
                    "decision": result["decision"],
                    "usage_complete": result["evidence"]["usage_complete"],
                    "model_usage": result["evidence"]["model_usage"],
                    "requests": len(captured),
                    "tools": [row.get("tools", []) for row in captured],
                },
                indent=2,
            )
        )
        assert captured, "Native runtime did not reach the loopback fake provider"
        assert all(row["model"] == "gpt-5.6-sol" for row in captured)
        assert all(not row.get("tools") for row in captured), "Responder exposed tools"
        assert all(row.get("reasoning", {}).get("effort") == "medium" for row in captured)
        assert result["reason"] is None
        assert result["decision"] == output
        assert result["evidence"]["usage_complete"]


if __name__ == "__main__":
    main()
