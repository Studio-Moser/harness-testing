import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from harness_testing.Contract_Stub_Server import Handler, ScenarioServer, _call_matches


@contextmanager
def _running_server(tmp_path: Path, scenario: dict[str, object] | None = None):
    contract: dict[str, object] = {
        "actions": [
            {
                "action": "dispatch",
                "description": "Dispatch the bounded request.",
                "required": [
                    "allowed_paths",
                    "deduplicate",
                    "outcome",
                    "route",
                    "verification.fixed_target",
                ],
            }
        ]
    }
    server = ScenarioServer(("127.0.0.1", 0), Handler)
    server.scenario = scenario or {
        "contract": contract,
        "calls": [
            {
                "action": "dispatch",
                "payload": {
                    "allowed_paths": ["Input.json", "Output.json"],
                    "deduplicate": True,
                    "outcome": "Deliver the bounded result.",
                    "route": "bulk",
                    "verification": {"fixed_target": "fixture:v1"},
                },
                "match": {
                    "allowed_paths": ["Input.json", "Output.json"],
                    "deduplicate": True,
                    "route": "bulk",
                    "verification": {"fixed_target": "fixture:v1"},
                },
                "shape_only": ["outcome"],
                "response": {"status": "delivered"},
            }
        ],
    }
    server.events_path = tmp_path / "Events.jsonl"
    server.events_path.write_text("")
    server.events_lock = threading.Lock()
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


def _valid_payload() -> dict[str, object]:
    return {
        "allowed_paths": ["Input.json", "Output.json"],
        "deduplicate": True,
        "outcome": "Equivalent caller wording is allowed.",
        "route": "bulk",
        "verification": {"fixed_target": "fixture:v1"},
    }


def test_public_contract_is_discoverable_and_invalid_calls_do_not_advance(tmp_path):
    with _running_server(tmp_path) as (base_url, contract, events_path):
        assert _get_json(f"{base_url}/contract") == contract

        invalid_status, invalid = _post_json(
            f"{base_url}/invoke",
            {
                "action": "dispatch",
                "payload": {
                    **_valid_payload(),
                    "route": "quick",
                },
            },
        )
        valid_status, valid = _post_json(
            f"{base_url}/invoke",
            {
                "action": "dispatch",
                "payload": _valid_payload(),
            },
        )

    assert invalid_status == 422
    assert invalid == {"error": "contract_mismatch", "expected_action": "dispatch"}
    assert valid_status == 200
    assert valid == {"status": "delivered"}
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert [event["expected_sequence"] for event in events] == [None, 1]
    assert [event["matched"] for event in events] == [False, True]


def test_contract_validation_rejects_null_required_values_and_json_type_aliases(
    tmp_path,
):
    invalid_payloads = [
        {**_valid_payload(), "outcome": None},
        {**_valid_payload(), "deduplicate": 1},
    ]

    for index, payload in enumerate(invalid_payloads):
        case_path = tmp_path / str(index)
        case_path.mkdir()
        with _running_server(case_path) as (base_url, _, _):
            status, _ = _post_json(
                f"{base_url}/invoke", {"action": "dispatch", "payload": payload}
            )
        assert status == 422


def test_contract_validation_accepts_reordered_set_like_lists(tmp_path):
    payload = _valid_payload()
    payload["allowed_paths"] = ["Output.json", "Input.json"]

    with _running_server(tmp_path) as (base_url, _, _):
        status, body = _post_json(
            f"{base_url}/invoke", {"action": "dispatch", "payload": payload}
        )

    assert status == 200
    assert body == {"status": "delivered"}


def test_product_pulse_rejects_a_semantically_wrong_required_operation():
    scenario_path = (
        Path(__file__).parents[2]
        / "tasks/contract/product-pulse-fanout-synthesis/environment/stub-server/Scenario.json"
    )
    scenario = json.loads(scenario_path.read_text())
    expected = scenario["calls"][0]
    payload = {**expected["payload"], "operation": "delete"}
    required = scenario["contract"]["actions"][0]["required"]

    assert not _call_matches(expected, "research", payload, required)


def test_all_protected_scenario_reference_calls_cover_the_public_contract():
    root = Path(__file__).parents[2]
    for scenario_path in sorted(
        root.glob("tasks/contract/*/environment/stub-server/Scenario.json")
    ):
        scenario = json.loads(scenario_path.read_text())
        required_by_action = {
            action["action"]: action["required"]
            for action in scenario["contract"]["actions"]
        }
        for expected in scenario["calls"]:
            assert _call_matches(
                expected,
                expected["action"],
                expected["payload"],
                required_by_action[expected["action"]],
            ), scenario_path


def test_unordered_fanout_accepts_reordered_and_concurrent_calls(tmp_path):
    count = 12
    contract = {
        "actions": [
            {
                "action": "research",
                "description": "Research one independent source.",
                "required": ["source_id"],
            }
        ]
    }
    scenario = {
        "contract": contract,
        "calls": [
            {
                "action": "research",
                "payload": {"source_id": str(index)},
                "match": {"source_id": str(index)},
                "response": {"source_id": str(index)},
                "unordered_group": "research",
            }
            for index in range(count)
        ],
    }

    with (
        _running_server(tmp_path, scenario) as (base_url, _, events_path),
        ThreadPoolExecutor(max_workers=count) as executor,
    ):
        results = list(
            executor.map(
                lambda index: _post_json(
                    f"{base_url}/invoke",
                    {
                        "action": "research",
                        "payload": {"source_id": str(index)},
                    },
                ),
                reversed(range(count)),
            )
        )

    assert [status for status, _ in results] == [200] * count
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert [event["sequence"] for event in events] == list(range(1, count + 1))
    assert {event["expected_sequence"] for event in events} == set(range(1, count + 1))


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


def test_harness_stub_records_locally_rejected_json(tmp_path):
    script = (
        Path(__file__).parents[2]
        / "tasks/contract/missing-required-executor/environment/Harness_Stub.mjs"
    )
    with _running_server(tmp_path) as (base_url, _, events_path):
        result = subprocess.run(
            ("node", str(script), "dispatch", "{"),
            env={**os.environ, "HARNESS_STUB_URL": base_url},
            check=False,
            capture_output=True,
            text=True,
        )

    assert result.returncode == 2
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert [(event["action"], event["matched"]) for event in events] == [
        ("dispatch", False)
    ]
