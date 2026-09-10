"""Versioned communication expectations for collaboration-quality evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


def _contract_validator() -> Draft202012Validator:
    schema_path = Path(__file__).parents[2] / "policy/Communication Contract.schema.json"
    return Draft202012Validator(json.loads(schema_path.read_text()))


def _validate_contract(document: object, description: str) -> dict:
    errors = sorted(_contract_validator().iter_errors(document), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'.'.join(map(str, error.path)) or '$'}: {error.message}" for error in errors
        )
        raise ValueError(f"invalid communication contract ({description}): {details}")
    assert isinstance(document, dict)
    expectations = document["expectations"]
    for name in ("progress_updates", "questions", "approval_requests", "final_answer_words"):
        if expectations[name]["minimum"] > expectations[name]["maximum"]:
            raise ValueError(
                f"invalid communication contract ({description}): {name} minimum exceeds maximum"
            )
    return document


def load_communication_contract(path: Path) -> dict:
    """Load and validate one exact contract file with its byte identity."""
    try:
        contents = path.read_bytes()
        document = json.loads(contents)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid communication contract ({path}): {error}") from error
    return {
        "digest": "sha256:" + hashlib.sha256(contents).hexdigest(),
        "contract": _validate_contract(document, str(path)),
    }


def communication_contract_for_task(root: Path, task_id: str) -> dict:
    """Resolve a workflow task's frozen collaboration contract."""
    if not task_id or Path(task_id).name != task_id:
        raise ValueError("invalid communication task ID")
    return load_communication_contract(
        root / "tasks" / "workflow" / task_id / "Communication Contract.json"
    )


def load_scenario_catalog(path: Path) -> dict:
    """Load the ten inexpensive scenarios and validate each embedded contract."""
    try:
        document = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid communication scenario catalog: {error}") from error
    if not isinstance(document, dict) or set(document) != {"schema_version", "scenarios"}:
        raise ValueError("invalid communication scenario catalog shape")
    scenarios = document.get("scenarios")
    if document.get("schema_version") != "1" or not isinstance(scenarios, list):
        raise ValueError("invalid communication scenario catalog version")
    identifiers = []
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict) or set(scenario) != {
            "id", "prompt", "follow_ups", "contract"
        }:
            raise ValueError(f"invalid communication scenario at index {index}")
        if (
            not isinstance(scenario["id"], str)
            or not isinstance(scenario["prompt"], str)
            or not scenario["prompt"].strip()
            or not isinstance(scenario["follow_ups"], list)
            or not all(isinstance(turn, str) and turn.strip() for turn in scenario["follow_ups"])
        ):
            raise ValueError(f"invalid communication scenario content at index {index}")
        contract = _validate_contract(scenario["contract"], f"scenario {scenario['id']}")
        if contract["scenario"] != scenario["id"]:
            raise ValueError("communication scenario and contract identifiers differ")
        identifiers.append(scenario["id"])
    if len(identifiers) != 10 or len(set(identifiers)) != len(identifiers):
        raise ValueError("communication scenario catalog requires ten unique scenarios")
    return document
