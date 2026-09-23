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

