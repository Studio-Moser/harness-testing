"""Public JSON Schema contract for Harness results."""

from __future__ import annotations

import json
from collections.abc import Iterable
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

_SCHEMA_RESOURCE = files("harness_testing").joinpath("Harness_Result.schema.json")


def harness_result_schema_bytes() -> bytes:
    return _SCHEMA_RESOURCE.read_bytes()


def load_harness_result_schema() -> dict[str, Any]:
    schema = json.loads(harness_result_schema_bytes())
    if not isinstance(schema, dict):
        raise ValueError("HarnessResult schema must be a JSON object")
    Draft202012Validator.check_schema(schema)
    return schema


def _json_pointer(path: Iterable[object]) -> str:
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
    return "/" + "/".join(parts) if parts else "/"


_VALIDATOR = Draft202012Validator(load_harness_result_schema())


def harness_result_schema_errors(value: object) -> tuple[tuple[str, str], ...]:
    errors = sorted(
        _VALIDATOR.iter_errors(value),
        key=lambda error: (list(error.absolute_path), str(error.validator)),
    )
    return tuple(
        (_json_pointer(error.absolute_path), str(error.validator)) for error in errors
    )
