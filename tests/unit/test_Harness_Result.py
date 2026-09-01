import copy
import json
from pathlib import Path

from harness_testing.Harness_Result import (
    harness_result_schema_bytes,
    harness_result_schema_errors,
    load_harness_result_schema,
)

REPOSITORY_ROOT = Path(__file__).parents[2]


def _expected_results() -> list[dict[str, object]]:
    return [
        json.loads(path.read_text())["result"]
        for path in sorted(
            REPOSITORY_ROOT.glob("tasks/contract/*/tests/Expected.json")
        )
    ]


def test_every_protected_expected_result_matches_the_public_schema():
    assert harness_result_schema_bytes() == (
        REPOSITORY_ROOT / "src/harness_testing/Harness_Result.schema.json"
    ).read_bytes()
    assert load_harness_result_schema()["$schema"] == (
        "https://json-schema.org/draft/2020-12/schema"
    )
    assert all(
        harness_result_schema_errors(result) == () for result in _expected_results()
    )


def test_schema_rejects_empty_unavailable_values_and_unknown_fields():
    result = copy.deepcopy(_expected_results()[0])
    result["route"]["actual_model"] = ""
    result["unexpected"] = True

    errors = harness_result_schema_errors(result)

    assert ("/route/actual_model", "anyOf") in errors
    assert ("/", "additionalProperties") in errors


def test_schema_enforces_terminal_status_evidence_invariants():
    accepted = copy.deepcopy(
        next(
            result
            for result in _expected_results()
            if result["status"] == "accepted"
        )
    )
    accepted["evidence"]["outcome"] = "unproven"
    blocked = copy.deepcopy(
        next(
            result for result in _expected_results() if result["status"] == "blocked"
        )
    )
    blocked["blockers"] = []

    assert ("/evidence/outcome", "const") in harness_result_schema_errors(accepted)
    assert ("/blockers", "minItems") in harness_result_schema_errors(blocked)
