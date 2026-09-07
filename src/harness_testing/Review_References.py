"""Validate explicitly selected reviewed successors for comparison references."""

from __future__ import annotations

import copy
import re
from pathlib import Path

from harness_testing.Experiments import available_reference_reports
from harness_testing.Run_Reports import run_report_id

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _one(reports: list[dict], identity: str, description: str) -> dict:
    matches = [report for report in reports if report.get("report_id") == identity]
    if len(matches) != 1 or run_report_id(matches[0]) != identity:
        raise ValueError(f"{description} is unavailable, ambiguous, or has an invalid identity")
    return matches[0]


def _execution_trials(report: dict) -> list[dict]:
    trials = report.get("experiment", {}).get("trials")
    if not isinstance(trials, list):
        raise ValueError("reference has no experiment trials")
    copied = copy.deepcopy(trials)
    for trial in copied:
        if not isinstance(trial, dict):
            raise ValueError("reference has an invalid experiment trial")
        trial.pop("code_review", None)
    return copied


def validate_review_references(
    root: Path, source_report: dict, protocol_id: str, mapping: dict[str, str]
) -> dict[str, str]:
    """Return only explicit, direct, execution-identical reviewed successors."""

    if not _DIGEST.fullmatch(protocol_id):
        raise ValueError("review protocol identity is invalid")
    if not isinstance(mapping, dict) or not all(
        isinstance(old, str)
        and isinstance(new, str)
        and _DIGEST.fullmatch(old)
        and _DIGEST.fullmatch(new)
        for old, new in mapping.items()
    ):
        raise ValueError("review reference mapping must contain only digest strings")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("review reference mapping rewrites multiple sources to one revision")
    experiment = source_report.get("experiment")
    if not isinstance(experiment, dict):
        raise ValueError("source report has no experiment")
    selected = set(experiment.get("baseline_result_ids", [])) | set(
        experiment.get("predecessor_result_ids", [])
    )
    if not all(isinstance(identity, str) and _DIGEST.fullmatch(identity) for identity in selected):
        raise ValueError("source report has invalid selected reference identities")
    if not set(mapping).issubset(selected):
        raise ValueError("review reference mapping contains an unselected source report")

    reports = available_reference_reports(root)
    validated: dict[str, str] = {}
    for old_id, new_id in mapping.items():
        old = _one(reports, old_id, "selected source reference")
        new = _one(reports, new_id, "reviewed reference")
        old_experiment = old.get("experiment")
        new_experiment = new.get("experiment")
        if not isinstance(old_experiment, dict) or not isinstance(new_experiment, dict):
            raise ValueError("review reference is not a comparison report")
        review = new_experiment.get("code_review")
        if (
            not isinstance(review, dict)
            or review.get("source_report_id") != old_id
            or review.get("protocol_id") != protocol_id
        ):
            raise ValueError("reviewed reference is not a direct same-protocol successor")
        if (
            new.get("manifest_digest") != old.get("manifest_digest")
            or new_experiment.get("conditions") != old_experiment.get("conditions")
            or new_experiment.get("contenders") != old_experiment.get("contenders")
            or _execution_trials(new) != _execution_trials(old)
        ):
            raise ValueError("reviewed reference changed original execution evidence")
        trials = new_experiment.get("trials")
        if not isinstance(trials, list) or any(
            not isinstance(trial, dict)
            or not isinstance(trial.get("code_review"), dict)
            or trial["code_review"].get("protocol_id") != protocol_id
            for trial in trials
        ):
            raise ValueError("reviewed reference trial protocol does not match")
        validated[old_id] = new_id
    return validated
