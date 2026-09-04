"""Load benchmark configuration through Harbor's pinned schema models."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import yaml
from harbor.models.job.config import JobConfig
from harbor.models.task.config import TaskConfig
from harbor.models.trajectories import Trajectory
from harbor.utils.trajectory_validator import TrajectoryValidator


def _contains_key(value: Any, forbidden_key: str) -> bool:
    if isinstance(value, dict):
        return forbidden_key in value or any(
            _contains_key(child, forbidden_key) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(child, forbidden_key) for child in value)
    return False


def load_versions(path: Path) -> dict[str, Any]:
    with path.open("rb") as versions_file:
        return tomllib.load(versions_file)


def load_task(path: Path, *, expected_schema: str) -> TaskConfig:
    text = path.read_text()
    raw = tomllib.loads(text)
    if _contains_key(raw, "orchestrator"):
        raise ValueError("deprecated orchestrator field is not allowed")

    task = TaskConfig.model_validate_toml(text)
    if task.schema_version != expected_schema:
        raise ValueError(
            f"{path} uses task schema {task.schema_version}; expected schema {expected_schema}"
        )
    return task


def load_job(path: Path) -> JobConfig:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Harbor job YAML must contain an object")
    if _contains_key(raw, "orchestrator"):
        raise ValueError("deprecated orchestrator field is not allowed")
    return JobConfig.model_validate(raw)


def load_trajectory(path: Path) -> Trajectory:
    raw = json.loads(path.read_text())
    validator = TrajectoryValidator()
    if not validator.validate(raw, validate_images=False):
        raise ValueError("; ".join(validator.get_errors()))
    return Trajectory.model_validate(raw)
