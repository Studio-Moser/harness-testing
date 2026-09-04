"""Validate the fixed destination for public-safe run reports."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_REPOSITORY = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"
)
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9]$")
_WORKFLOW = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.ya?ml$")
_TARGET_FIELDS = {"repository", "data_branch", "workflow", "code_ref"}


@dataclass(frozen=True)
class PublicationTarget:
    repository: str
    data_branch: str
    workflow: str
    code_ref: str


def load_publication_target(root: Path) -> PublicationTarget:
    """Load and fail closed on the repository's tracked publication policy."""

    path = root / "policy" / "Dashboard_Publication.toml"
    try:
        with path.open("rb") as policy_file:
            document = tomllib.load(policy_file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"publication policy is unreadable: {error}") from error
    if set(document) != {"public_reports"}:
        raise ValueError("publication policy must contain only [public_reports]")
    values = document.get("public_reports")
    if not isinstance(values, dict) or set(values) != _TARGET_FIELDS:
        raise ValueError("publication policy has missing or unknown target fields")
    if not all(isinstance(values[field], str) for field in _TARGET_FIELDS):
        raise ValueError("publication policy target fields must be strings")
    target = PublicationTarget(**values)
    if not _REPOSITORY.fullmatch(target.repository):
        raise ValueError("publication policy repository must be OWNER/REPO")
    if (
        not _BRANCH.fullmatch(target.data_branch)
        or ".." in target.data_branch
        or "//" in target.data_branch
        or target.data_branch.endswith(".lock")
    ):
        raise ValueError("publication policy data branch is invalid")
    if not _WORKFLOW.fullmatch(target.workflow):
        raise ValueError("publication policy workflow must be a workflow filename")
    if target.code_ref != "main":
        raise ValueError("publication policy code ref must be main")
    return target


def publication_manifest_record(target: PublicationTarget) -> dict[str, str]:
    """Return the exact destination included in content-addressed run manifests."""

    return {
        "mode": "public",
        "repository": target.repository,
        "data_branch": target.data_branch,
        "workflow": target.workflow,
        "code_ref": target.code_ref,
    }
