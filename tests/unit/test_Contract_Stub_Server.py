import json
import os
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from harness_testing.Contract_Stub_Server import Handler, ScenarioServer


@contextmanager
def _running_server(tmp_path: Path):
    contract = {
        "actions": [
            {
                "action": "dispatch",
                "description": "Dispatch the bounded request.",
                "required": ["route", "verification.fixed_target"],
            }
        ]
    }
    server = ScenarioServer(("127.0.0.1", 0), Handler)
    server.scenario = {
        "contract": contract,
        "calls": [
            {
                "action": "dispatch",
                "payload": {
                    "route": "bulk",
                    "verification": {"fixed_target": "fixture:v1"},
                },
                "match": {
                    "route": "bulk",
                    "verification": {"fixed_target": "fixture:v1"},
                },
                "response": {"status": "delivered"},
            }
        ],
    }
    server.events_path = tmp_path / "Events.jsonl"
    server.events_path.write_text("")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", contract, server.events_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _get_json(url: str) -> object:
    with urlopen(url) as response:
        return json.load(response)


def _post_json(url: str, value: object) -> tuple[int, object]:
    request = Request(
        url,
        data=json.dumps(value).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def test_public_contract_is_discoverable_and_invalid_calls_do_not_advance(tmp_path):
    with _running_server(tmp_path) as (base_url, contract, events_path):
        assert _get_json(f"{base_url}/contract") == contract

        invalid_status, invalid = _post_json(
            f"{base_url}/invoke",
            {
                "action": "dispatch",
                "payload": {
                    "route": "quick",
                    "verification": {"fixed_target": "fixture:v1"},
                },
            },
        )
        valid_status, valid = _post_json(
            f"{base_url}/invoke",
            {
                "action": "dispatch",
                "payload": {
                    "route": "bulk",
                    "verification": {"fixed_target": "fixture:v1"},
                    "outcome": "Equivalent caller wording is allowed.",
                },
            },
        )

    assert invalid_status == 422
    assert invalid == {"error": "contract_mismatch", "expected_action": "dispatch"}
    assert valid_status == 200
    assert valid == {"status": "delivered"}
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert [event["expected_sequence"] for event in events] == [None, 1]
    assert [event["matched"] for event in events] == [False, True]


def test_harness_stub_describe_prints_the_public_contract(tmp_path):
    script = (
        Path(__file__).parents[2]
        / "tasks/contract/missing-required-executor/environment/Harness_Stub.mjs"
    )
    with _running_server(tmp_path) as (base_url, contract, _):
        result = subprocess.run(
            ("node", str(script), "describe"),
            env={**os.environ, "HARNESS_STUB_URL": base_url},
            check=False,
            capture_output=True,
            text=True,
        )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == contract
