"""Compile explicit, budget-guarded Harbor runs without starting them."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from harbor.models.job.config import JobConfig

import harness_testing.Materialize as Materialize
from harness_testing.Config import load_job, load_versions
from harness_testing.Credentials import load_claude_subscription_token
from harness_testing.Harbor_CLI import harbor_command
from harness_testing.Materialize import (
    _ARM_LAYERS,
    DEEPSWE_TASK_IDS,
    MaterializedDeepSWE,
    _find_existing_bundle,
    _resolve_source_trees,
    dockerfile_policy_errors,
    image_input_digest,
    load_deepswe_dataset,
    materialize_arm,
    require_current_image,
)
from harness_testing.Run_Reports import refresh_local_dashboard, write_run_report
from harness_testing.Skill_Evaluation import SkillEvaluation, write_skill_evaluation_report
from harness_testing.Validate import find_sensitive_keys, validate_repository

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PROVIDER_ORDER = {"claude": 0, "codex": 1}
_ROLE_ORDER = {"baseline": 0, "candidate": 1, "calibration": 2}
_BILLING_MODES = {"api", "subscription"}
_LOCAL_TASK_PACKS = ("contract", "workflow")
_API_HOSTS = {
    "claude": ("api.anthropic.com",),
    "codex": ("api.openai.com",),
}
_SUBSCRIPTION_HOSTS = {
    "claude": ("api.anthropic.com",),
    "codex": ("chatgpt.com", "auth.openai.com"),
}
_SUBSCRIPTION_SELECTORS = {
    "claude": ("CLAUDE_FORCE_OAUTH", "1"),
    "codex": ("CODEX_FORCE_AUTH_JSON", "1"),
}
_LAYER_PLUGIN_NAMES = {
    "Superpowers": "superpowers",
    "Studio Harness": "harness",
}
_CODEX_LAYER_MARKETPLACES = {
    "Superpowers": "superpowers-dev",
    "Studio Harness": "studio-moser",
}
_BENCHMARK_PLUGIN_NAMES = frozenset(_LAYER_PLUGIN_NAMES.values())
_MAX_DELIVERY_ERRORS = 12
_AGENT_ADAPTERS = {
    "claude": (
        "harness_testing.Claude_Agent:HarnessClaude",
        Path("src/harness_testing/Claude_Agent.py"),
    ),
    "codex": (
        "harness_testing.Codex_Agent:HarnessCodex",
        Path("src/harness_testing/Codex_Agent.py"),
    ),
}
_AGENT_ADAPTER_SHARED_PATHS = (Path("src/harness_testing/Skill_Evaluation.py"),)


@dataclass(frozen=True)
class RunCell:
    label: str
    provider: str
    arm: str
    role: str
    model: str
    effort: str
    harness_commit: str | None
    bundle_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "provider": self.provider,
            "arm": self.arm,
            "role": self.role,
            "model": self.model,
            "effort": self.effort,
            "harness_commit": self.harness_commit,
            "bundle_digest": self.bundle_digest,
        }


@dataclass(frozen=True)
class RunManifest:
    schema_version: str
    profile: str
    billing_mode: str
    skill_evaluation: SkillEvaluation | None
    cells: tuple[RunCell, ...]
    task_ids: tuple[str, ...]
    attempts: int
    session_count: int
    concurrency: int
    agent_timeout_seconds: int
    max_sessions: int
    max_budget_usd: Decimal
    estimated_budget_usd: Decimal
    api_equivalent_cost_usd: Decimal
    harbor_config_paths: tuple[str, ...]
    provenance: dict[str, object]
    digest: str
    path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "billing_mode": self.billing_mode,
            "skill_evaluation": (
                self.skill_evaluation.to_dict()
                if self.skill_evaluation is not None
                else None
            ),
            "cells": [cell.to_dict() for cell in self.cells],
            "task_ids": list(self.task_ids),
            "attempts": self.attempts,
            "session_count": self.session_count,
            "concurrency": self.concurrency,
            "agent_timeout_seconds": self.agent_timeout_seconds,
            "max_sessions": self.max_sessions,
            "max_budget_usd": _decimal_text(self.max_budget_usd),
            "estimated_budget_usd": _decimal_text(self.estimated_budget_usd),
            "api_equivalent_cost_usd": _decimal_text(
                self.api_equivalent_cost_usd
            ),
            "harbor_config_paths": list(self.harbor_config_paths),
            "provenance": self.provenance,
            "digest": self.digest,
        }

    @classmethod
    def from_document(cls, document: dict[str, object], path: Path) -> RunManifest:
        if "skill_evaluation" not in document:
            raise ValueError("manifest skill_evaluation is missing")
        cells = tuple(
            RunCell(
                label=str(cell["label"]),
                provider=str(cell["provider"]),
                arm=str(cell["arm"]),
                role=str(cell["role"]),
                model=str(cell["model"]),
                effort=str(cell["effort"]),
                harness_commit=(
                    str(cell["harness_commit"])
                    if cell.get("harness_commit") is not None
                    else None
                ),
                bundle_digest=str(cell["bundle_digest"]),
            )
            for cell in _object_list(document.get("cells"), "cells")
        )
        provenance = document.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError("manifest provenance must be an object")
        return cls(
            schema_version=str(document["schema_version"]),
            profile=str(document["profile"]),
            billing_mode=str(document["billing_mode"]),
            skill_evaluation=SkillEvaluation.from_document(
                document["skill_evaluation"]
            ),
            cells=cells,
            task_ids=tuple(str(task) for task in document["task_ids"]),
            attempts=int(document["attempts"]),
            session_count=int(document["session_count"]),
            concurrency=int(document["concurrency"]),
            agent_timeout_seconds=int(document["agent_timeout_seconds"]),
            max_sessions=int(document["max_sessions"]),
            max_budget_usd=Decimal(str(document["max_budget_usd"])),
            estimated_budget_usd=Decimal(str(document["estimated_budget_usd"])),
            api_equivalent_cost_usd=Decimal(
                str(document["api_equivalent_cost_usd"])
            ),
            harbor_config_paths=tuple(str(item) for item in document["harbor_config_paths"]),
            provenance=provenance,
            digest=str(document["digest"]),
            path=path,
        )


@dataclass(frozen=True)
class _Profile:
    name: str
    attempts: int
    agent_timeout_seconds: int
    concurrency: int
    packs: tuple[str, ...]
    max_sessions: int
    estimated_input_tokens_per_session: int
    estimated_output_tokens_per_session: int


def _object_list(value: object, description: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"manifest {description} must be a list of objects")
    return value


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _sha256(contents: bytes) -> str:
    return f"sha256:{hashlib.sha256(contents).hexdigest()}"


def _agent_adapter_digests(root: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for provider, (_, adapter_path) in _AGENT_ADAPTERS.items():
        paths = (adapter_path, *_AGENT_ADAPTER_SHARED_PATHS)
        inputs = {
            path.as_posix(): _sha256((root / path).read_bytes()) for path in paths
        }
        digests[provider] = _sha256(_canonical_json(inputs))
    return digests


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _tree_digest(root: Path) -> str:
    if not root.is_dir():
        raise ValueError(f"task directory is missing: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not (path.is_file() or path.is_symlink()):
            continue
        relative = path.relative_to(root).as_posix()
        payload = (
            f"symlink:{os.readlink(path)}".encode()
            if path.is_symlink()
            else path.read_bytes()
        )
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(f"{path.lstat().st_mode & 0o777:o}".encode())
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _manifest_digest(document: dict[str, object]) -> str:
    unsigned = dict(document)
    unsigned.pop("digest", None)
    return _sha256(_canonical_json(unsigned))


def verify_manifest_document(document: dict[str, object]) -> str:
    recorded = str(document.get("digest", ""))
    actual = _manifest_digest(document)
    if not _DIGEST.fullmatch(recorded) or recorded != actual:
        raise ValueError(f"manifest digest mismatch: recorded {recorded!r}, actual {actual}")
    return recorded


def _load_profile(root: Path, name: str) -> _Profile:
    path = root / "runs" / "Profiles.toml"
    with path.open("rb") as profiles_file:
        profiles = tomllib.load(profiles_file).get("profiles", {})
    raw = profiles.get(name)
    if not isinstance(raw, dict):
        raise ValueError(f"unknown run profile: {name}")
    return _Profile(
        name=name,
        attempts=int(raw["attempts"]),
        agent_timeout_seconds=int(raw["agent_timeout_seconds"]),
        concurrency=int(raw["concurrency"]),
        packs=tuple(str(pack) for pack in raw["packs"]),
        max_sessions=int(raw["max_sessions"]),
        estimated_input_tokens_per_session=int(
            raw["estimated_input_tokens_per_session"]
        ),
        estimated_output_tokens_per_session=int(
            raw["estimated_output_tokens_per_session"]
        ),
    )


def _model_entries(versions: dict[str, Any]) -> dict[str, dict[str, object]]:
    return {str(model["provider"]): model for model in versions.get("models", [])}


def _package_versions(versions: dict[str, Any]) -> dict[str, str]:
    return {
        str(package["name"]): str(package["version"])
        for package in versions.get("packages", [])
    }


def _bundle_path(root: Path, cell: RunCell) -> Path:
    return (
        root
        / "arms"
        / "materialized"
        / cell.provider
        / cell.arm
        / cell.bundle_digest.removeprefix("sha256:")
    )


def _bundle_provenance(bundle: Path) -> dict[str, Any]:
    provenance_path = bundle / "Provenance.json"
    if provenance_path.is_symlink():
        raise ValueError(f"bundle provenance must not be a symlink: {bundle}")
    if not provenance_path.is_file():
        raise ValueError(f"bundle has no materialized provenance: {bundle}")
    try:
        provenance = json.loads(provenance_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"bundle provenance is invalid: {bundle}") from error
    if not isinstance(provenance, dict):
        raise ValueError(f"bundle provenance must be an object: {bundle}")
    return provenance


def _authoritative_source_trees(
    root: Path,
    layers: tuple[str, ...],
    source_overrides: Mapping[str, tuple[str | Path, str]],
    versions: dict[str, Any],
    destination: Path,
) -> tuple[Materialize._SourceTree, ...]:
    cached_sources = _resolve_source_trees(root, layers, source_overrides)
    pins = {
        str(source["name"]): source
        for source in versions.get("sources", [])
    }
    authoritative: list[Materialize._SourceTree] = []
    for index, source in enumerate(cached_sources):
        if source.name in source_overrides:
            repository_source, commit = source_overrides[source.name]
        else:
            pin = pins.get(source.name)
            if pin is None:
                raise ValueError(f"Versions.toml has no source pin for {source.name}")
            repository_source, commit = str(pin["url"]), str(pin["commit"])
        if commit != source.commit:
            raise ValueError(f"pinned source commit changed for {source.name}")

        repository = Materialize._local_repository(repository_source)
        if repository is None:
            cache_key = hashlib.sha256(str(repository_source).encode()).hexdigest()
            repository = (
                root
                / ".cache"
                / "source-repositories"
                / f"{cache_key}.git"
            )
        try:
            resolved_commit = (
                Materialize._run_git(
                    (
                        "--no-replace-objects",
                        "rev-parse",
                        "--verify",
                        f"{commit}^{{commit}}",
                    ),
                    cwd=repository,
                )
                .stdout.decode()
                .strip()
            )
            if resolved_commit != commit:
                raise ValueError(
                    f"pinned source Git object is invalid for {source.name}"
                )
            Materialize._run_git(
                (
                    "--no-replace-objects",
                    "fsck",
                    "--strict",
                    "--no-dangling",
                    commit,
                ),
                cwd=repository,
            )
            archive = Materialize._run_git(
                (
                    "--no-replace-objects",
                    "archive",
                    "--format=tar",
                    commit,
                ),
                cwd=repository,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as error:
            raise ValueError(
                f"pinned source Git object is invalid for {source.name}"
            ) from error

        tree = destination / f"source-{index}"
        tree.mkdir()
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as archive_file:
                archive_file.extractall(tree, filter="data")
        except (OSError, tarfile.TarError) as error:
            raise ValueError(
                f"pinned source Git archive is invalid for {source.name}"
            ) from error
        authoritative.append(
            replace(
                source,
                path=tree,
                digest=Materialize._tree_digest(tree),
            )
        )
    return tuple(authoritative)


def _validate_materialized_bundle(
    root: Path,
    cell: RunCell,
    bundle: Path,
    versions: dict[str, Any],
) -> None:
    trusted_root = root.resolve(strict=True)
    arms_root = root / "arms"
    materialized_root = arms_root / "materialized"
    provider_root = materialized_root / cell.provider
    arm_root = provider_root / cell.arm
    expected = arm_root / cell.bundle_digest.removeprefix("sha256:")
    if bundle != expected:
        raise ValueError(f"cell {cell.label} materialized arm path is invalid")
    for path in (arms_root, materialized_root, provider_root, arm_root, expected):
        try:
            path_status = path.lstat()
        except OSError as error:
            raise ValueError(
                f"cell {cell.label} materialized arm path is missing"
            ) from error
        if stat.S_ISLNK(path_status.st_mode):
            raise ValueError(
                f"cell {cell.label} materialized arm path must not contain a symlink"
            )
        if not stat.S_ISDIR(path_status.st_mode):
            raise ValueError(f"cell {cell.label} materialized arm path is missing")
    expected_physical = (
        trusted_root
        / "arms"
        / "materialized"
        / cell.provider
        / cell.arm
        / cell.bundle_digest.removeprefix("sha256:")
    )
    if expected.resolve(strict=True) != expected_physical:
        raise ValueError(f"cell {cell.label} materialized arm path is invalid")
    provenance_path = bundle / "Provenance.json"
    if provenance_path.is_symlink():
        raise ValueError(f"bundle provenance must not be a symlink: {bundle}")
    provenance = _bundle_provenance(bundle)
    unsigned_provenance = dict(provenance)
    unsigned_provenance.pop("bundle_digest", None)
    canonical_digest = Materialize._sha256_bytes(
        Materialize._canonical_json(unsigned_provenance)
    )
    if (
        canonical_digest != cell.bundle_digest
        or bundle.name != canonical_digest.removeprefix("sha256:")
    ):
        raise ValueError(
            f"cell {cell.label} materialized arm provenance digest mismatch"
        )
    if (
        provenance.get("provider") != cell.provider
        or provenance.get("arm") != cell.arm
        or provenance.get("bundle_digest") != cell.bundle_digest
    ):
        raise ValueError(f"cell {cell.label} arm provenance does not match its digest")

    source_overrides: dict[str, tuple[str | Path, str]] = {}
    if cell.harness_commit is not None:
        source_overrides["Studio Harness"] = (
            _harness_source_pin(versions),
            cell.harness_commit,
        )
    layers = _ARM_LAYERS[cell.arm]
    with tempfile.TemporaryDirectory() as temporary_directory:
        sources = _authoritative_source_trees(
            root,
            layers,
            source_overrides,
            versions,
            Path(temporary_directory),
        )
        authoritative = _find_existing_bundle(
            root,
            cell.provider,
            cell.arm,
            layers,
            sources,
        )
        if (
            authoritative is None
            or authoritative.digest != cell.bundle_digest
            or authoritative.path.resolve(strict=True) != expected_physical
        ):
            raise ValueError(
                f"cell {cell.label} delivery does not match pinned source materialization"
            )

        harness_source = next(
            (source for source in sources if source.name == "Studio Harness"),
            None,
        )
        if harness_source is not None:
            source_template = (
                harness_source.path
                / "plugins"
                / "harness"
                / "templates"
                / "AGENTS_Baseline.md"
            )
            instruction = bundle / "project" / (
                "CLAUDE.md" if cell.provider == "claude" else "AGENTS.md"
            )
            try:
                expected_instruction = f"{source_template.read_text().rstrip()}\n"
                actual_instruction = instruction.read_text()
            except OSError as error:
                raise ValueError(
                    f"cell {cell.label} project instruction does not match pinned Harness source"
                ) from error
            if actual_instruction != expected_instruction:
                raise ValueError(
                    f"cell {cell.label} project instruction does not match pinned Harness source"
                )


def _reject_control_symlinks(bundle: Path, path: Path, description: str) -> None:
    try:
        relative = path.relative_to(bundle)
    except ValueError as error:
        raise ValueError(f"{description} is outside its bundle") from error
    current = bundle
    if current.is_symlink():
        raise ValueError(f"{description} must not be a symlink")
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{description} must not be a symlink")


def _delivery_surface_host_path(bundle: Path, provider: str, value: object) -> Path:
    if not isinstance(value, str):
        raise ValueError("delivery surface path must be a string")
    provider_path = Path(value)
    if not provider_path.is_absolute() or ".." in provider_path.parts:
        raise ValueError(f"unsafe delivery surface path: {value!r}")

    arm_root = Path("/harness-arm")
    codex_root = Path("/tmp/codex-home")
    try:
        arm_relative = provider_path.relative_to(arm_root)
    except ValueError:
        arm_relative = None
    if arm_relative is not None:
        if provider == "claude":
            expected_prefix = ("claude", "plugins")
        else:
            expected_prefix = ("codex", "provider-home", "plugins", "cache")
        if arm_relative.parts[: len(expected_prefix)] != expected_prefix:
            raise ValueError(f"delivery surface is outside its provider root: {value}")
        host_path = bundle.joinpath(*arm_relative.parts)
    else:
        if provider != "codex":
            raise ValueError(f"delivery surface is outside its provider root: {value}")
        try:
            relative = provider_path.relative_to(codex_root)
        except ValueError as error:
            raise ValueError(f"delivery surface is outside its provider root: {value}") from error
        if relative.parts[:2] != ("plugins", "cache"):
            raise ValueError(f"delivery surface is outside its provider root: {value}")
        host_path = bundle / "codex" / "provider-home" / relative

    _reject_control_symlinks(bundle, host_path, "delivery target")
    try:
        resolved_bundle = bundle.resolve(strict=True)
        resolved_path = host_path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"delivery surface target is missing: {value}") from error
    if not resolved_path.is_relative_to(resolved_bundle) or not resolved_path.is_dir():
        raise ValueError(f"delivery surface target is invalid: {value}")
    return resolved_path


def _actual_delivery_targets(bundle: Path, provider: str) -> set[Path]:
    if provider == "claude":
        plugin_root = bundle / "claude" / "plugins"
        if not plugin_root.exists() and not plugin_root.is_symlink():
            return set()
        if not plugin_root.is_dir():
            raise ValueError("Claude delivery root is not a directory")
        _reject_control_symlinks(bundle, plugin_root, "Claude delivery root")
        for path in plugin_root.iterdir():
            _reject_control_symlinks(bundle, path, "Claude delivery target")
        return {path.resolve(strict=True) for path in plugin_root.iterdir()}

    cache_root = bundle / "codex" / "provider-home" / "plugins" / "cache"
    if not cache_root.exists() and not cache_root.is_symlink():
        return set()
    if not cache_root.is_dir():
        raise ValueError("Codex delivery root is not a directory")
    return {
        manifest.parent.parent.resolve(strict=True)
        for manifest in cache_root.rglob(".codex-plugin/plugin.json")
    }


def _plugin_manifest(target: Path, provider: str) -> dict[str, object]:
    directory = ".claude-plugin" if provider == "claude" else ".codex-plugin"
    path = target / directory / "plugin.json"
    if (target / directory).is_symlink() or path.is_symlink():
        raise ValueError(f"delivery plugin manifest must not be a symlink: {target}")
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"delivery plugin manifest is invalid: {target}") from error
    if not isinstance(manifest, dict):
        raise ValueError(f"delivery plugin manifest is invalid: {target}")
    return manifest


def _observed_capabilities(target: Path, provider: str) -> list[str]:
    manifest = _plugin_manifest(target, provider)
    for path in (target / "skills", target / "hooks"):
        if path.is_symlink():
            raise ValueError(f"delivery capability path must not be a symlink: {target}")
    capabilities: list[str] = []
    if (target / "skills").is_dir() or manifest.get("skills"):
        capabilities.append("skills")
    hooks = manifest.get("hooks")
    if (
        provider == "claude"
        and ((target / "hooks").is_dir() or bool(hooks))
    ) or (provider == "codex" and bool(hooks)):
        capabilities.append("hooks")
    return capabilities


def _canonical_delivery_path(
    bundle: Path,
    provider: str,
    layer: str,
    target: Path,
    version: str,
) -> str:
    plugin = _LAYER_PLUGIN_NAMES[layer]
    manifest = _plugin_manifest(target, provider)
    target_plugin = target.name if provider == "claude" else target.parent.name
    if (
        target_plugin != plugin
        or manifest.get("name") != plugin
        or manifest.get("version") != version
    ):
        raise ValueError(f"delivery target is not canonical for layer {layer}")
    if provider == "claude":
        return f"/harness-arm/claude/plugins/{plugin}"

    marketplace = _CODEX_LAYER_MARKETPLACES[layer]
    cache_root = bundle / "codex" / "provider-home" / "plugins" / "cache"
    try:
        actual_marketplace, plugin_name, actual_version = target.relative_to(cache_root).parts
    except ValueError as error:
        raise ValueError(f"delivery target is not canonical for layer {layer}") from error
    if (
        actual_marketplace != marketplace
        or plugin_name != plugin
        or actual_version != version
    ):
        raise ValueError(f"delivery target is not canonical for layer {layer}")
    return (
        "/harness-arm/codex/provider-home/plugins/cache/"
        f"{marketplace}/{plugin}/{version}"
    )


def _validate_codex_provider_home(bundle: Path, targets: set[Path]) -> None:
    codex_root = bundle / "codex"
    if not targets:
        if codex_root.exists() or codex_root.is_symlink():
            raise ValueError("Codex delivery contamination in A0")
        return
    _reject_control_symlinks(bundle, codex_root, "Codex provider root")
    if not codex_root.is_dir() or {path.name for path in codex_root.iterdir()} != {
        "provider-home"
    }:
        raise ValueError("Codex delivery contamination in provider root")

    provider_home = codex_root / "provider-home"
    _reject_control_symlinks(bundle, provider_home, "Codex provider home")
    expected_home_entries = {"config.toml", "marketplaces", "plugins"}
    if not provider_home.is_dir() or {
        path.name for path in provider_home.iterdir()
    } != expected_home_entries:
        raise ValueError("Codex delivery contamination in provider home")
    cache_root = provider_home / "plugins" / "cache"
    _reject_control_symlinks(bundle, provider_home / "plugins", "Codex plugins root")
    _reject_control_symlinks(bundle, cache_root, "Codex plugin cache")
    if not cache_root.is_dir() or {
        path.name for path in (provider_home / "plugins").iterdir()
    } != {"cache"}:
        raise ValueError("Codex delivery contamination in plugin cache")

    expected_paths: dict[str, dict[str, set[str]]] = {}
    for target in targets:
        try:
            marketplace, plugin, version = target.relative_to(cache_root).parts
        except ValueError as error:
            raise ValueError("Codex delivery target is outside its cache") from error
        expected_paths.setdefault(marketplace, {}).setdefault(plugin, set()).add(version)
    if {path.name for path in cache_root.iterdir()} != set(expected_paths):
        raise ValueError("Codex delivery contamination in cache marketplaces")
    for marketplace, plugins in expected_paths.items():
        marketplace_path = cache_root / marketplace
        _reject_control_symlinks(bundle, marketplace_path, "Codex cache marketplace")
        if not marketplace_path.is_dir() or {
            path.name for path in marketplace_path.iterdir()
        } != set(plugins):
            raise ValueError("Codex delivery contamination in cache plugins")
        for plugin, versions in plugins.items():
            plugin_path = marketplace_path / plugin
            _reject_control_symlinks(bundle, plugin_path, "Codex cache plugin")
            if not plugin_path.is_dir() or {
                path.name for path in plugin_path.iterdir()
            } != versions:
                raise ValueError("Codex delivery contamination in cache versions")
            for version in versions:
                _reject_control_symlinks(
                    bundle, plugin_path / version, "Codex cache plugin version"
                )

    marketplaces = provider_home / "marketplaces"
    _reject_control_symlinks(bundle, marketplaces, "Codex marketplaces")
    for marketplace in expected_paths:
        _reject_control_symlinks(
            bundle, marketplaces / marketplace, "Codex marketplace"
        )
    if not marketplaces.is_dir() or {
        path.name for path in marketplaces.iterdir()
    } != set(expected_paths) or not all(
        (marketplaces / marketplace).is_dir() for marketplace in expected_paths
    ):
        raise ValueError("Codex delivery contamination in marketplaces")
    try:
        config_path = provider_home / "config.toml"
        _reject_control_symlinks(bundle, config_path, "Codex provider config")
        with config_path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError("Codex provider config is invalid") from error
    expected_config = {
        "marketplaces": {
            marketplace: {
                "source_type": "local",
                "source": (
                    "/harness-arm/codex/provider-home/marketplaces/"
                    f"{marketplace}"
                ),
            }
            for marketplace in expected_paths
        },
        "plugins": {
            f"{plugin}@{marketplace}": {"enabled": True}
            for marketplace, plugins in expected_paths.items()
            for plugin in plugins
        },
    }
    if config != expected_config:
        raise ValueError("Codex provider config contradicts delivery")


def _validate_project_instruction(
    bundle: Path,
    provider: str,
    layers: tuple[str, ...],
    targets: dict[str, Path],
) -> None:
    project = bundle / "project"
    if "Studio Harness" not in layers:
        if project.exists() or project.is_symlink():
            raise ValueError("project instruction is unclaimed")
        return
    filename = "CLAUDE.md" if provider == "claude" else "AGENTS.md"
    instruction = project / filename
    _reject_control_symlinks(bundle, project, "project instruction directory")
    _reject_control_symlinks(bundle, instruction, "project instruction")
    if not project.is_dir() or {path.name for path in project.iterdir()} != {filename}:
        raise ValueError("project instruction contents are invalid")
    if not instruction.is_file():
        raise ValueError("project instruction is missing")
    template = targets["Studio Harness"] / "templates" / "AGENTS_Baseline.md"
    _reject_control_symlinks(bundle, template, "Harness instruction template")
    if not template.is_file():
        raise ValueError("Harness instruction template is missing")
    if instruction.read_text() != f"{template.read_text().rstrip()}\n":
        raise ValueError("project instruction does not match the Harness template")


def _validated_delivery_surfaces(
    bundle: Path,
    provider: str,
    arm: str,
) -> tuple[dict[str, object], ...]:
    provenance = _bundle_provenance(bundle)
    expected_layers = _ARM_LAYERS.get(arm)
    if expected_layers is None:
        raise ValueError(f"unsupported arm delivery policy: {arm}")
    layers = provenance.get("layers")
    if not isinstance(layers, list) or tuple(layers) != expected_layers:
        raise ValueError(f"delivery layers do not match arm {arm}")
    sources = provenance.get("sources")
    if not isinstance(sources, list) or len(sources) != len(expected_layers):
        raise ValueError(f"delivery sources do not match arm {arm}")
    source_versions: dict[str, str] = {}
    for layer, source in zip(expected_layers, sources, strict=True):
        if (
            not isinstance(source, dict)
            or source.get("name") != layer
            or not isinstance(source.get("version"), str)
            or not source["version"]
        ):
            raise ValueError(f"delivery source does not match layer {layer}")
        source_versions[layer] = source["version"]
    surfaces = provenance.get("delivery_surfaces")
    if not isinstance(surfaces, list) or len(surfaces) != len(expected_layers):
        raise ValueError(f"delivery surfaces do not match arm {arm}")

    expected_surface = "claude-plugin-dir" if provider == "claude" else "codex-plugin"
    validated: list[dict[str, object]] = []
    expected_targets: set[Path] = set()
    targets: dict[str, Path] = {}
    for layer, surface in zip(expected_layers, surfaces, strict=True):
        if not isinstance(surface, dict):
            raise ValueError("delivery surface must be an object")
        if surface.get("layer") != layer or surface.get("surface") != expected_surface:
            raise ValueError(f"delivery surface does not match layer {layer}")
        target = _delivery_surface_host_path(bundle, provider, surface.get("path"))
        if target in expected_targets:
            raise ValueError(f"duplicate delivery target for layer {layer}")
        if provider == "claude" and target.parent != (bundle / "claude" / "plugins").resolve():
            raise ValueError("Claude plugin delivery target must be a direct child")
        canonical_path = _canonical_delivery_path(
            bundle, provider, layer, target, source_versions[layer]
        )
        if surface.get("path") != canonical_path:
            raise ValueError(f"delivery path is not canonical for layer {layer}")
        if surface.get("capabilities") != _observed_capabilities(target, provider):
            raise ValueError(f"delivery capabilities do not match layer {layer}")
        expected_targets.add(target)
        targets[layer] = target
        validated.append(surface)
    if provider == "codex":
        _validate_codex_provider_home(bundle, expected_targets)
    elif _actual_delivery_targets(bundle, provider) != expected_targets:
        raise ValueError(f"delivery contamination does not match arm {arm}")
    _validate_project_instruction(bundle, provider, expected_layers, targets)
    return tuple(validated)


def _claude_plugin_dirs(bundle: Path, arm: str) -> list[str]:
    return [
        str(surface["path"])
        for surface in _validated_delivery_surfaces(bundle, "claude", arm)
    ]


def _validate_cell(root: Path, cell: RunCell, versions: dict[str, Any]) -> None:
    if cell.provider not in _PROVIDER_ORDER:
        raise ValueError(f"unsupported provider in cell {cell.label}: {cell.provider}")
    if cell.arm not in {"A0", "A1", "A2", "A3"}:
        raise ValueError(f"unsupported arm in cell {cell.label}: {cell.arm}")
    if cell.role not in _ROLE_ORDER:
        raise ValueError(f"unsupported role in cell {cell.label}: {cell.role}")
    if cell.label != f"{cell.provider}-{cell.arm}-{cell.role}":
        raise ValueError(f"cell label is not deterministic: {cell.label}")
    if not _DIGEST.fullmatch(cell.bundle_digest):
        raise ValueError(f"cell {cell.label} has an invalid arm digest")
    if cell.arm in {"A2", "A3"}:
        if cell.harness_commit is None or not _COMMIT.fullmatch(cell.harness_commit):
            raise ValueError(f"cell {cell.label} requires an exact Harness commit")
    elif cell.harness_commit is not None:
        raise ValueError(f"cell {cell.label} must omit the Harness commit")

    model = _model_entries(versions).get(cell.provider)
    if model is None or cell.model != model.get("model") or cell.effort != model.get("effort"):
        raise ValueError(f"cell {cell.label} does not match the version ledger model pin")
    bundle_path = _bundle_path(root, cell)
    _validate_materialized_bundle(root, cell, bundle_path, versions)
    provenance = _bundle_provenance(bundle_path)
    source_commits = {
        source.get("name"): source.get("commit")
        for source in provenance.get("sources", [])
        if isinstance(source, dict)
    }
    if cell.harness_commit is not None:
        if source_commits.get("Studio Harness") != cell.harness_commit:
            raise ValueError(f"cell {cell.label} arm provenance has the wrong Harness commit")
    elif "Studio Harness" in source_commits:
        raise ValueError(f"cell {cell.label} arm provenance unexpectedly includes Harness")
    _validated_delivery_surfaces(bundle_path, cell.provider, cell.arm)


def _ordered_cells(cells: tuple[RunCell, ...]) -> tuple[RunCell, ...]:
    return tuple(
        sorted(
            cells,
            key=lambda cell: (
                _PROVIDER_ORDER[cell.provider],
                _ROLE_ORDER[cell.role],
                cell.arm,
            ),
        )
    )


def _required_images(
    profile: _Profile, task_ids: tuple[str, ...]
) -> tuple[str, ...]:
    if profile.name == "research":
        return ()
    required = {"verifier"}
    if any(task_id.startswith("rust-") for task_id in task_ids):
        required.add("rust")
    if any(not task_id.startswith("rust-") for task_id in task_ids):
        required.add("node")
    return tuple(image for image in ("node", "rust", "verifier") if image in required)


def _subscription_selectors(cells: tuple[RunCell, ...]) -> dict[str, dict[str, str]]:
    providers = {cell.provider for cell in cells}
    return {
        provider: {"name": name, "value": value}
        for provider, (name, value) in _SUBSCRIPTION_SELECTORS.items()
        if provider in providers
    }


def _is_trusted_local_task(root: Path, pack: str, task_id: str) -> bool:
    if pack not in _LOCAL_TASK_PACKS:
        return False
    tasks_root = root / "tasks"
    pack_root = tasks_root / pack
    task_root = pack_root / task_id
    task_config = task_root / "task.toml"
    if any(
        path.is_symlink()
        for path in (tasks_root, pack_root, task_root, task_config)
    ):
        return False
    if (
        not tasks_root.is_dir()
        or not pack_root.is_dir()
        or not task_root.is_dir()
        or not task_config.is_file()
    ):
        return False
    try:
        trusted_root = root.resolve(strict=True)
        resolved_tasks = tasks_root.resolve(strict=True)
        resolved_pack = pack_root.resolve(strict=True)
        resolved_task = task_root.resolve(strict=True)
        resolved_config = task_config.resolve(strict=True)
    except OSError:
        return False
    return (
        resolved_tasks == trusted_root / "tasks"
        and resolved_pack.is_relative_to(resolved_tasks)
        and resolved_task.is_relative_to(resolved_pack)
        and resolved_config.is_relative_to(resolved_task)
    )


def _task_pack(root: Path, profile: _Profile, task_id: str) -> str:
    matches = [
        pack
        for pack in profile.packs
        if _is_trusted_local_task(root, pack, task_id)
    ]
    if len(matches) == 1:
        return matches[0]
    local_matches = [
        pack
        for pack in _LOCAL_TASK_PACKS
        if _is_trusted_local_task(root, pack, task_id)
    ]
    if not matches and len(local_matches) == 1:
        return local_matches[0]
    raise ValueError(f"task {task_id} does not resolve to exactly one profile pack")


def _research_dataset(root: Path, profile: _Profile) -> MaterializedDeepSWE | None:
    if profile.name != "research":
        return None
    if profile.packs != ("research",):
        raise ValueError("research profile must contain only the DeepSWE research pack")
    return load_deepswe_dataset(root)


def _task_location(
    root: Path,
    profile: _Profile,
    task_id: str,
    research: MaterializedDeepSWE | None,
) -> tuple[str, Path, Path]:
    if research is not None:
        if task_id not in DEEPSWE_TASK_IDS:
            raise ValueError(f"task {task_id} is not in the pinned DeepSWE cohort")
        dataset = research.tasks_path
        task = dataset / task_id
        if not task.is_dir():
            raise ValueError(f"materialized DeepSWE task is missing: {task_id}")
        return "research", dataset, task
    pack = _task_pack(root, profile, task_id)
    dataset = root / "tasks" / pack
    return pack, dataset, dataset / task_id


def _provider_config(bundle: Path, provider: str) -> dict[str, object]:
    if provider == "claude":
        return {}
    path = bundle / "codex" / "provider-home" / "config.toml"
    if not path.is_file():
        return {}
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def _job_mounts(bundle: Path, provider: str) -> list[dict[str, object]]:
    mounts: list[dict[str, object]] = [
        {
            "type": "bind",
            "source": str(bundle),
            "target": "/harness-arm",
            "read_only": True,
        }
    ]
    instructions = bundle / "project" / ("CLAUDE.md" if provider == "claude" else "AGENTS.md")
    if instructions.is_file():
        mounts.append(
            {
                "type": "bind",
                "source": str(instructions),
                "target": f"/app/{instructions.name}",
                "read_only": True,
            }
        )
    codex_cache = bundle / "codex" / "provider-home" / "plugins" / "cache"
    if codex_cache.is_dir():
        mounts.append(
            {
                "type": "bind",
                "source": str(codex_cache),
                "target": "/tmp/codex-home/plugins/cache",
                "read_only": True,
            }
        )
    return mounts


def _job_document(
    root: Path,
    cell: RunCell,
    task_id: str,
    run_id: str,
    dataset_path: Path,
    attempts: int,
    concurrency: int,
    timeout: int,
    versions: dict[str, Any],
    billing_mode: str,
    skill_evaluation: SkillEvaluation | None,
) -> tuple[dict[str, object], str]:
    bundle = _bundle_path(root, cell)
    packages = _package_versions(versions)
    if cell.provider == "claude":
        agent_identity = {"import_path": _AGENT_ADAPTERS["claude"][0]}
        model_name = f"anthropic/{cell.model}"
        version = packages["@anthropic-ai/claude-code"]
        environment = {}
        skills: list[str] = []
    else:
        agent_identity = {"import_path": _AGENT_ADAPTERS["codex"][0]}
        model_name = f"openai/{cell.model}"
        version = packages["@openai/codex"]
        environment = {}
        skills = [str(bundle / "skills")] if (bundle / "skills").is_dir() else []
    hosts = (
        _SUBSCRIPTION_HOSTS[cell.provider]
        if billing_mode == "subscription"
        else _API_HOSTS[cell.provider]
    )
    kwargs: dict[str, object] = {"version": version, "reasoning_effort": cell.effort}
    if skill_evaluation is not None and skill_evaluation.mode == "capability":
        kwargs["skill_invocation"] = skill_evaluation.name
    provider_config = _provider_config(bundle, cell.provider)
    if provider_config:
        kwargs["config"] = provider_config
    if cell.provider == "claude":
        plugin_dirs = _claude_plugin_dirs(bundle, cell.arm)
        if plugin_dirs:
            kwargs["plugin_dirs"] = plugin_dirs

    raw: dict[str, object] = {
        "job_name": f"{run_id}-{cell.label}-{task_id}",
        "jobs_dir": "jobs/raw",
        "n_attempts": attempts,
        "n_concurrent_trials": concurrency,
        "quiet": False,
        "retry": {
            "max_retries": 1,
            "include_exceptions": ["NetworkConnectionError", "UnknownApiError"],
        },
        "environment": {
            "type": "docker",
            "force_build": False,
            "delete": True,
            "mounts": _job_mounts(bundle, cell.provider),
        },
        "agents": [
            {
                **agent_identity,
                "model_name": model_name,
                "override_timeout_sec": timeout,
                "max_timeout_sec": timeout,
                "extra_allowed_hosts": list(hosts),
                "skills": skills,
                "kwargs": kwargs,
                "env": environment,
            }
        ],
        "datasets": [
            {
                "path": dataset_path.resolve().relative_to(root.resolve()).as_posix(),
                "task_names": [task_id],
            }
        ],
    }
    job = JobConfig.model_validate(raw)
    document = job.model_dump(mode="json", exclude_none=True)
    retry = document.get("retry")
    if retry is not None:
        for key in ("include_exceptions", "exclude_exceptions"):
            exceptions = retry.get(key)
            if exceptions is not None:
                retry[key] = sorted(exceptions)
    sensitive_keys = find_sensitive_keys(document)
    if sensitive_keys:
        raise ValueError(f"generated Harbor job contains sensitive keys: {sensitive_keys}")
    text = yaml.safe_dump(document, sort_keys=False)
    JobConfig.model_validate(yaml.safe_load(text))
    return document, text


def _estimated_budget(
    cells: tuple[RunCell, ...],
    task_count: int,
    attempts: int,
    profile: _Profile,
    versions: dict[str, Any],
) -> Decimal:
    models = _model_entries(versions)
    total = Decimal("0")
    million = Decimal("1000000")
    for cell in cells:
        model = models[cell.provider]
        per_session = (
            Decimal(str(model["input_usd_per_million_tokens"]))
            * profile.estimated_input_tokens_per_session
            / million
            + Decimal(str(model["output_usd_per_million_tokens"]))
            * profile.estimated_output_tokens_per_session
            / million
        )
        total += per_session * task_count * attempts
    return total


def compile_run(
    root: Path,
    *,
    profile: str,
    billing_mode: str,
    cells: tuple[RunCell, ...],
    task_ids: tuple[str, ...],
    max_sessions: int,
    max_budget_usd: Decimal,
    attempts: int | None = None,
    concurrency: int | None = None,
    agent_timeout_seconds: int | None = None,
    skill_evaluation: SkillEvaluation | None = None,
) -> RunManifest:
    """Compile immutable one-cell task shards and write a dry-run manifest."""

    root = root.resolve()
    selected_profile = _load_profile(root, profile)
    attempts = selected_profile.attempts if attempts is None else attempts
    concurrency = selected_profile.concurrency if concurrency is None else concurrency
    timeout = (
        selected_profile.agent_timeout_seconds
        if agent_timeout_seconds is None
        else agent_timeout_seconds
    )
    if not cells:
        raise ValueError("at least one explicit --cell is required")
    if not task_ids:
        raise ValueError("at least one explicit --task is required")
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if not isinstance(skill_evaluation, (SkillEvaluation, type(None))):
        raise ValueError("skill_evaluation must be a SkillEvaluation or None")
    if (
        skill_evaluation is not None
        and skill_evaluation.mode == "discovery"
        and attempts < 5
    ):
        raise ValueError("skill discovery requires at least five attempts")
    if timeout < 1:
        raise ValueError("agent timeout must be positive")
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    if max_sessions < 1:
        raise ValueError("max_sessions must be positive")
    if billing_mode not in _BILLING_MODES:
        raise ValueError(f"unsupported billing mode: {billing_mode}")
    if billing_mode == "subscription" and max_budget_usd != 0:
        raise ValueError("subscription billing requires a zero max_budget_usd")
    if billing_mode == "api" and max_budget_usd <= 0:
        raise ValueError("API billing requires a positive max_budget_usd")
    if len(set(task_ids)) != len(task_ids) or any(
        not _TASK_ID.fullmatch(task_id) for task_id in task_ids
    ):
        raise ValueError("task IDs must be unique kebab-case names")
    if len({cell.label for cell in cells}) != len(cells):
        raise ValueError("cell labels must be unique")
    if {cell.role for cell in cells} >= {"baseline", "candidate"} and concurrency != 1:
        raise ValueError("paired runs require concurrency 1")
    if {cell.arm for cell in cells} == {"A0", "A1", "A2", "A3"} and profile != "calibration":
        raise ValueError("the full A0-A3 matrix is allowed only in the calibration profile")

    versions = load_versions(root / "Versions.toml")
    for cell in cells:
        _validate_cell(root, cell, versions)
    cells = _ordered_cells(cells)
    if skill_evaluation is not None:
        for cell in cells:
            _, delivered_skills = _expected_runtime_delivery(root, cell)
            if skill_evaluation.name not in delivered_skills:
                raise ValueError(
                    f"cell {cell.label} does not expose skill {skill_evaluation.name}"
                )
    session_count = len(cells) * len(task_ids) * attempts
    if session_count > max_sessions:
        raise ValueError(f"run needs {session_count} sessions but max_sessions {max_sessions}")
    if session_count > selected_profile.max_sessions:
        raise ValueError(
            f"run needs {session_count} sessions but profile limit is "
            f"{selected_profile.max_sessions}"
        )
    api_equivalent_cost = _estimated_budget(
        cells, len(task_ids), attempts, selected_profile, versions
    )
    estimated_budget = (
        Decimal("0") if billing_mode == "subscription" else api_equivalent_cost
    )
    if billing_mode == "api" and estimated_budget > max_budget_usd:
        raise ValueError(
            f"estimated budget ${_decimal_text(estimated_budget)} exceeds "
            f"max_budget_usd ${_decimal_text(max_budget_usd)}"
        )

    schema_version = str(versions["repository"]["schema_version"])
    research_dataset = _research_dataset(root, selected_profile)
    task_digests = {}
    for task_id in task_ids:
        pack, _, task_path = _task_location(
            root, selected_profile, task_id, research_dataset
        )
        task_digests[f"{pack}/{task_id}"] = _tree_digest(task_path)
    image_input_digests = {
        image: image_input_digest(root, image)
        for image in _required_images(selected_profile, task_ids)
    }
    agent_adapter_digests = _agent_adapter_digests(root)
    versions_digest = _sha256((root / "Versions.toml").read_bytes())
    profiles_digest = _sha256((root / "runs" / "Profiles.toml").read_bytes())

    def build_job_documents(run_id: str) -> dict[str, tuple[dict[str, object], str]]:
        documents = {}
        index = 0
        for task_id in task_ids:
            _, dataset_path, _ = _task_location(
                root, selected_profile, task_id, research_dataset
            )
            for cell in cells:
                index += 1
                document, text = _job_document(
                    root,
                    cell,
                    task_id,
                    run_id,
                    dataset_path,
                    attempts,
                    concurrency,
                    timeout,
                    versions,
                    billing_mode,
                    skill_evaluation,
                )
                relative_path = (
                    f"jobs/{index:03d}-{cell.provider}-{cell.role}-{cell.arm}-"
                    f"{task_id}.yaml"
                )
                documents[relative_path] = (document, text)
        return documents

    provisional_jobs = build_job_documents("run-pending")
    run_identity: dict[str, object] = {
        "schema_version": schema_version,
        "profile": profile,
        "billing_mode": billing_mode,
        "skill_evaluation": (
            skill_evaluation.to_dict() if skill_evaluation is not None else None
        ),
        "cells": [cell.to_dict() for cell in cells],
        "task_ids": list(task_ids),
        "attempts": attempts,
        "concurrency": concurrency,
        "agent_timeout_seconds": timeout,
        "max_sessions": max_sessions,
        "max_budget_usd": _decimal_text(max_budget_usd),
        "versions_digest": versions_digest,
        "profiles_digest": profiles_digest,
        "task_digests": task_digests,
        "image_input_digests": image_input_digests,
        "agent_adapter_digests": agent_adapter_digests,
        "harbor_configs": {
            path: {
                key: value
                for key, value in document.items()
                if key != "job_name"
            }
            for path, (document, _) in provisional_jobs.items()
        },
    }
    if research_dataset is not None:
        run_identity["deepswe_dataset_digest"] = research_dataset.digest
    run_id = "run-" + _sha256(_canonical_json(run_identity)).removeprefix(
        "sha256:"
    )[:20]
    job_texts = {
        path: text for path, (_, text) in build_job_documents(run_id).items()
    }

    provenance: dict[str, object] = {
        "run_id": run_id,
        "versions_digest": versions_digest,
        "profiles_digest": profiles_digest,
        "arm_digests": {cell.label: cell.bundle_digest for cell in cells},
        "harbor_config_digests": {
            path: _sha256(text.encode()) for path, text in job_texts.items()
        },
        "task_digests": task_digests,
        "image_input_digests": image_input_digests,
        "agent_adapter_digests": agent_adapter_digests,
        "budget_enforcement": (
            "subscription-only-no-api-fallback"
            if billing_mode == "subscription"
            else "admission-estimate-only"
        ),
        "subscription_selectors": (
            _subscription_selectors(cells) if billing_mode == "subscription" else {}
        ),
    }
    if research_dataset is not None:
        provenance["deepswe_dataset_digest"] = research_dataset.digest
    manifest = RunManifest(
        schema_version=schema_version,
        profile=profile,
        billing_mode=billing_mode,
        skill_evaluation=skill_evaluation,
        cells=cells,
        task_ids=task_ids,
        attempts=attempts,
        session_count=session_count,
        concurrency=concurrency,
        agent_timeout_seconds=timeout,
        max_sessions=max_sessions,
        max_budget_usd=max_budget_usd,
        estimated_budget_usd=estimated_budget,
        api_equivalent_cost_usd=api_equivalent_cost,
        harbor_config_paths=tuple(job_texts),
        provenance=provenance,
        digest="",
        path=Path(),
    )
    digest = _manifest_digest(manifest.to_dict())
    manifest_directory = root / "runs" / "generated" / digest.removeprefix("sha256:")
    manifest_path = manifest_directory / "Manifest.json"
    manifest = replace(manifest, digest=digest, path=manifest_path)

    manifest_directory.mkdir(parents=True, exist_ok=True)
    for relative_path, text in job_texts.items():
        path = manifest_directory / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_text() != text:
            path.write_text(text)
    serialized_manifest = json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n"
    if not manifest_path.is_file() or manifest_path.read_text() != serialized_manifest:
        manifest_path.write_text(serialized_manifest)
    return manifest


def _harness_source_pin(versions: dict[str, Any]) -> str:
    for source in versions.get("sources", []):
        if source.get("name") == "Studio Harness":
            return str(source["url"])
    raise ValueError("Versions.toml has no Studio Harness source")


def resolve_cell(root: Path, specification: str) -> RunCell:
    parts = specification.split(":")
    if len(parts) not in {3, 4}:
        raise ValueError("cell must be PROVIDER:ARM:ROLE[:HARNESS_COMMIT]")
    provider, arm, role = parts[:3]
    harness_commit = parts[3] if len(parts) == 4 else None
    if provider not in _PROVIDER_ORDER or arm not in {"A0", "A1", "A2", "A3"}:
        raise ValueError(f"invalid cell: {specification}")
    if role not in _ROLE_ORDER:
        raise ValueError(f"invalid cell role: {role}")
    if arm in {"A2", "A3"}:
        if harness_commit is None or not _COMMIT.fullmatch(harness_commit):
            raise ValueError(f"cell {specification} requires an exact Harness commit")
    elif harness_commit is not None:
        raise ValueError(f"cell {specification} must omit the Harness commit")

    versions = load_versions(root / "Versions.toml")
    if harness_commit is None:
        bundle = materialize_arm(root, provider, arm)
    else:
        bundle = materialize_arm(
            root,
            provider,
            arm,
            harness_source=_harness_source_pin(versions),
            harness_commit=harness_commit,
        )
    model = _model_entries(versions)[provider]
    return RunCell(
        label=f"{provider}-{arm}-{role}",
        provider=provider,
        arm=arm,
        role=role,
        model=str(model["model"]),
        effort=str(model["effort"]),
        harness_commit=harness_commit,
        bundle_digest=bundle.digest,
    )


def plan_run(
    root: Path,
    *,
    profile: str,
    billing_mode: str,
    cell_specifications: tuple[str, ...],
    task_ids: tuple[str, ...],
    max_sessions: int,
    max_budget_usd: Decimal,
    attempts: int | None = None,
    concurrency: int | None = None,
    agent_timeout_seconds: int | None = None,
    skill_evaluation: SkillEvaluation | None = None,
) -> RunManifest:
    if not cell_specifications:
        raise ValueError("at least one explicit --cell is required; no matrix is implicit")
    cells = tuple(resolve_cell(root, specification) for specification in cell_specifications)
    return compile_run(
        root,
        profile=profile,
        billing_mode=billing_mode,
        cells=cells,
        task_ids=task_ids,
        max_sessions=max_sessions,
        max_budget_usd=max_budget_usd,
        attempts=attempts,
        concurrency=concurrency,
        agent_timeout_seconds=agent_timeout_seconds,
        skill_evaluation=skill_evaluation,
    )


def format_plan(manifest: RunManifest) -> str:
    lines = [
        f"Run manifest: {manifest.digest}",
        f"Profile: {manifest.profile}",
        "Billing mode: "
        + (
            "subscription (no API-key fallback)"
            if manifest.billing_mode == "subscription"
            else "api"
        ),
        "Skill evaluation: "
        + (
            f"{manifest.skill_evaluation.mode} {manifest.skill_evaluation.name}"
            if manifest.skill_evaluation is not None
            else "none"
        ),
        f"Tasks: {', '.join(manifest.task_ids)}",
        f"Attempts: {manifest.attempts}",
        f"Sessions: {manifest.session_count} / {manifest.max_sessions}",
        f"Concurrency: {manifest.concurrency}",
        f"Agent timeout: {manifest.agent_timeout_seconds}s",
        "Expected incremental cost: "
        f"${_decimal_text(manifest.estimated_budget_usd)} / "
        f"${_decimal_text(manifest.max_budget_usd)}",
        "API-equivalent usage estimate: "
        f"${_decimal_text(manifest.api_equivalent_cost_usd)}",
        (
            "Budget enforcement: subscription credential only; subscription quota "
            "is not a dollar hard stop"
            if manifest.billing_mode == "subscription"
            else "Budget enforcement: admission estimate only; no consistent provider "
            "hard stop"
        ),
        "Cells:",
    ]
    for cell in manifest.cells:
        commit = f", Harness {cell.harness_commit}" if cell.harness_commit else ""
        lines.append(
            f"  {cell.label}: {cell.provider} {cell.model} {cell.effort}, "
            f"{cell.arm} {cell.role}{commit}, bundle {cell.bundle_digest}"
        )
    lines.append("Harbor order:")
    lines.extend(f"  {path}" for path in manifest.harbor_config_paths)
    lines.append("Task inputs:")
    task_digests = manifest.provenance.get("task_digests", {})
    if isinstance(task_digests, dict):
        lines.extend(f"  {name}: {digest}" for name, digest in sorted(task_digests.items()))
    lines.append("Image inputs:")
    image_digests = manifest.provenance.get("image_input_digests", {})
    if isinstance(image_digests, dict):
        lines.extend(f"  {name}: {digest}" for name, digest in sorted(image_digests.items()))
    lines.append(f"Manifest path: {manifest.path}")
    lines.append("No model session started.")
    return "\n".join(lines)


def load_manifest(path: Path) -> RunManifest:
    document = json.loads(path.read_text())
    if not isinstance(document, dict):
        raise ValueError("run manifest must contain an object")
    verify_manifest_document(document)
    return RunManifest.from_document(document, path.resolve())


def _verify_generated_inputs(root: Path, manifest: RunManifest) -> None:
    if manifest.session_count > manifest.max_sessions:
        raise ValueError("manifest session count exceeds its approval cap")
    if manifest.billing_mode not in _BILLING_MODES:
        raise ValueError("manifest billing mode is unsupported")
    if manifest.billing_mode == "subscription" and (
        manifest.max_budget_usd != 0 or manifest.estimated_budget_usd != 0
    ):
        raise ValueError("subscription manifest must authorize zero incremental spend")
    if manifest.billing_mode == "api" and manifest.max_budget_usd <= 0:
        raise ValueError("API manifest must have a positive approval cap")
    if manifest.billing_mode == "api" and (
        manifest.estimated_budget_usd > manifest.max_budget_usd
    ):
        raise ValueError("manifest estimated budget exceeds its approval cap")
    if manifest.billing_mode == "api" and (
        manifest.estimated_budget_usd != manifest.api_equivalent_cost_usd
    ):
        raise ValueError("API manifest cost estimate is inconsistent")
    expected_selectors = (
        _subscription_selectors(manifest.cells)
        if manifest.billing_mode == "subscription"
        else {}
    )
    if manifest.provenance.get("subscription_selectors") != expected_selectors:
        raise ValueError("manifest subscription selectors do not match its billing route")
    versions = load_versions(root / "Versions.toml")
    for cell in manifest.cells:
        _validate_cell(root, cell, versions)
    expected_task_digests = manifest.provenance.get("task_digests")
    if not isinstance(expected_task_digests, dict):
        raise ValueError("manifest has no task digests")
    profile = _load_profile(root, manifest.profile)
    research_dataset = _research_dataset(root, profile)
    actual_task_digests = {}
    for task_id in manifest.task_ids:
        pack, _, task_path = _task_location(
            root, profile, task_id, research_dataset
        )
        actual_task_digests[f"{pack}/{task_id}"] = _tree_digest(task_path)
    if expected_task_digests != actual_task_digests:
        raise ValueError("task digest mismatch after manifest approval")
    expected_deepswe_digest = manifest.provenance.get("deepswe_dataset_digest")
    actual_deepswe_digest = (
        research_dataset.digest if research_dataset is not None else None
    )
    if expected_deepswe_digest != actual_deepswe_digest:
        raise ValueError("DeepSWE dataset digest mismatch after manifest approval")
    expected_image_digests = manifest.provenance.get("image_input_digests")
    if not isinstance(expected_image_digests, dict):
        raise ValueError("manifest has no image input digests")
    actual_image_digests = {
        image: image_input_digest(root, image)
        for image in _required_images(profile, manifest.task_ids)
    }
    if expected_image_digests != actual_image_digests:
        raise ValueError("image input digest mismatch after manifest approval")
    expected_adapter_digests = manifest.provenance.get("agent_adapter_digests")
    actual_adapter_digests = _agent_adapter_digests(root)
    if expected_adapter_digests != actual_adapter_digests:
        raise ValueError("agent adapter digest mismatch after manifest approval")
    expected_digests = manifest.provenance.get("harbor_config_digests")
    if not isinstance(expected_digests, dict):
        raise ValueError("manifest has no Harbor config digests")
    if not manifest.cells:
        raise ValueError("manifest has no cells")
    for index, relative_path in enumerate(manifest.harbor_config_paths):
        if relative_path.startswith("/") or ".." in Path(relative_path).parts:
            raise ValueError(f"unsafe Harbor config path: {relative_path}")
        path = manifest.path.parent / relative_path
        expected = expected_digests.get(relative_path)
        if expected != _sha256(path.read_bytes()):
            raise ValueError(f"Harbor config digest mismatch: {relative_path}")
        job = load_job(path)
        cell = manifest.cells[index % len(manifest.cells)]
        if f"-{cell.label}-" not in job.job_name:
            raise ValueError(f"Harbor config order mismatch: {relative_path}")
        agent = job.agents[0]
        expected_import_path = _AGENT_ADAPTERS[cell.provider][0]
        if agent.import_path != expected_import_path:
            raise ValueError(f"Harbor agent adapter mismatch: {relative_path}")
        expected_skill_invocation = (
            manifest.skill_evaluation.name
            if manifest.skill_evaluation is not None
            and manifest.skill_evaluation.mode == "capability"
            else None
        )
        actual_skill_invocation = agent.kwargs.get("skill_invocation")
        if actual_skill_invocation != expected_skill_invocation or (
            expected_skill_invocation is None
            and "skill_invocation" in agent.kwargs
        ):
            raise ValueError(
                f"Harbor skill invocation does not match evaluation: {relative_path}"
            )
        if cell.provider != "claude":
            continue
        if "CLAUDE_CODE_PLUGIN_SEED_DIR" in agent.env:
            raise ValueError(f"Claude plugin seed is forbidden: {relative_path}")
        if agent.env != {} or agent.skills != []:
            raise ValueError(f"Claude delivery has unsupported surfaces: {relative_path}")
        expected_plugin_dirs = _claude_plugin_dirs(_bundle_path(root, cell), cell.arm)
        actual_plugin_dirs = agent.kwargs.get("plugin_dirs")
        if actual_plugin_dirs is not None and not isinstance(actual_plugin_dirs, list):
            raise ValueError(f"Claude plugin directories are invalid: {relative_path}")
        if (actual_plugin_dirs or []) != expected_plugin_dirs:
            raise ValueError(f"Claude plugin directories do not match delivery: {relative_path}")
        if "config" in agent.kwargs:
            raise ValueError(f"Claude settings config is forbidden: {relative_path}")


def _verify_subscription_auth(
    cells: tuple[RunCell, ...],
    environment: Mapping[str, str],
    home: Path,
) -> None:
    providers = {cell.provider for cell in cells}
    if "codex" in providers:
        for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE"):
            if environment.get(name, "").strip():
                raise ValueError(
                    f"{name} must be unset for Codex subscription billing"
                )
        configured_path = environment.get("CODEX_AUTH_JSON_PATH", "").strip()
        auth_path = Path(configured_path) if configured_path else home / ".codex" / "auth.json"
        if not auth_path.is_file():
            raise ValueError("Codex subscription credential is missing")
        try:
            auth = json.loads(auth_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Codex subscription credential is invalid") from error
        tokens = auth.get("tokens") if isinstance(auth, dict) else None
        if (
            not isinstance(auth, dict)
            or auth.get("auth_mode") != "chatgpt"
            or not isinstance(tokens, dict)
            or not isinstance(tokens.get("access_token"), str)
            or not tokens["access_token"].strip()
            or not isinstance(tokens.get("refresh_token"), str)
            or not tokens["refresh_token"].strip()
        ):
            raise ValueError(
                "Codex credential does not contain ChatGPT subscription auth"
            )

    if "claude" in providers:
        for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
            if environment.get(name, "").strip():
                raise ValueError(
                    f"{name} must be unset for Claude subscription billing"
                )
        if not environment.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
            raise ValueError("Claude subscription credential is missing")


def _expected_runtime_delivery(
    root: Path,
    cell: RunCell,
) -> tuple[dict[str, dict[str, object]], frozenset[str]]:
    bundle = _bundle_path(root, cell)
    surfaces = _validated_delivery_surfaces(bundle, cell.provider, cell.arm)
    plugins: dict[str, dict[str, object]] = {}
    skills: set[str] = set()
    for surface in surfaces:
        layer = str(surface["layer"])
        plugin = _LAYER_PLUGIN_NAMES[layer]
        target = _delivery_surface_host_path(bundle, cell.provider, surface["path"])
        skill_root = target / "skills"
        if skill_root.is_dir():
            skills.update(
                f"{plugin}:{path.name}"
                for path in sorted(skill_root.iterdir())
                if path.is_dir()
            )
        if cell.provider == "codex":
            marketplace = _CODEX_LAYER_MARKETPLACES[layer]
            version = target.name
            plugins[plugin] = {
                "name": plugin,
                "pluginId": f"{plugin}@{marketplace}",
                "marketplaceName": marketplace,
                "version": version,
                "enabled": True,
                "installed": True,
            }
        else:
            plugins[plugin] = {"name": plugin}
    return plugins, frozenset(skills)


def _benchmark_skill_names(root: Path, cells: tuple[RunCell, ...]) -> frozenset[str]:
    names: set[str] = set()
    for cell in cells:
        if cell.arm == "A0":
            continue
        _, skills = _expected_runtime_delivery(root, cell)
        names.update(skills)
    return frozenset(names)


def _benchmark_looking(value: object) -> bool:
    try:
        text = json.dumps(value, sort_keys=True).lower()
    except (TypeError, ValueError):
        text = repr(value).lower()
    return bool(
        re.search(
            r"(?<![a-z0-9_-])(?:superpowers|harness)(?:@|:|[^a-z0-9_-]|$)",
            text,
        )
        or "superpowers-dev" in text
        or "studio-moser" in text
    )


def _claude_delivery_errors(
    evidence_path: Path,
    expected_plugins: frozenset[str],
    expected_skills: frozenset[str],
    benchmark_skill_names: frozenset[str],
) -> list[str]:
    errors: list[str] = []
    try:
        lines = evidence_path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return ["Claude startup evidence is unreadable"]
    init_events: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if _benchmark_looking(line):
                errors.append(
                    f"Claude line {line_number} has malformed benchmark startup evidence"
                )
                if len(errors) == _MAX_DELIVERY_ERRORS:
                    break
            continue
        if (
            isinstance(event, dict)
            and event.get("type") == "system"
            and event.get("subtype") == "init"
        ):
            init_events.append(event)
    if not init_events:
        errors.append("Claude startup evidence has 0 primary init events")
        return errors

    event = init_events[0]
    if len(init_events) > 1:
        session_id = event.get("session_id")
        if not isinstance(session_id, str) or not session_id or any(
            repeated.get("session_id") != session_id for repeated in init_events[1:]
        ):
            errors.append("Claude startup evidence has multiple primary sessions")
            return errors
        if any(
            repeated.get("plugins") != event.get("plugins")
            or repeated.get("skills") != event.get("skills")
            for repeated in init_events[1:]
        ):
            errors.append("Claude startup evidence has conflicting repeated startup evidence")
            return errors

    raw_plugins = event.get("plugins")
    observed_plugins: set[str] = set()
    seen_plugins: set[str] = set()
    if not isinstance(raw_plugins, list):
        errors.append("Claude startup benchmark plugins are malformed")
    else:
        for index, entry in enumerate(raw_plugins):
            name = entry.get("name") if isinstance(entry, dict) else entry
            normalized: str | None = None
            if isinstance(name, str):
                parts = name.split("@")
                if (len(parts) == 1 and parts[0]) or (
                    len(parts) == 2 and all(part.strip() for part in parts)
                ):
                    normalized = parts[0]
            if normalized not in _BENCHMARK_PLUGIN_NAMES:
                candidate = name if isinstance(name, str) else entry
                if _benchmark_looking(candidate):
                    errors.append(
                        f"Claude plugin entry {index} has malformed benchmark plugin evidence"
                    )
                    if len(errors) == _MAX_DELIVERY_ERRORS:
                        break
                continue
            if normalized in seen_plugins:
                errors.append(
                    f"Claude plugin entry {index} has ambiguous benchmark plugin {normalized}"
                )
                if len(errors) == _MAX_DELIVERY_ERRORS:
                    break
                continue
            seen_plugins.add(normalized)
            observed_plugins.add(normalized)

    raw_skills = event.get("skills")
    observed_skills: set[str] = set()
    seen_skills: set[str] = set()
    if not isinstance(raw_skills, list):
        errors.append("Claude startup benchmark skills are malformed")
    else:
        for index, entry in enumerate(raw_skills):
            if isinstance(entry, str):
                if entry in benchmark_skill_names:
                    if entry in seen_skills:
                        errors.append(
                            f"Claude skill entry {index} has ambiguous benchmark skill {entry}"
                        )
                        if len(errors) == _MAX_DELIVERY_ERRORS:
                            break
                        continue
                    seen_skills.add(entry)
                    observed_skills.add(entry)
                elif _benchmark_looking(entry):
                    errors.append(
                        f"Claude skill entry {index} has unexpected benchmark skill {entry}"
                    )
                    if len(errors) == _MAX_DELIVERY_ERRORS:
                        break
            elif _benchmark_looking(entry):
                errors.append(
                    f"Claude skill entry {index} has malformed benchmark skill evidence"
                )
                if len(errors) == _MAX_DELIVERY_ERRORS:
                    break
    if observed_plugins != expected_plugins:
        errors.append(
            "Claude benchmark plugins mismatch: "
            f"expected {sorted(expected_plugins)}, observed {sorted(observed_plugins)}"
        )
    if observed_skills != expected_skills:
        errors.append(
            "Claude benchmark skills mismatch: "
            f"expected {sorted(expected_skills)}, observed {sorted(observed_skills)}"
        )
    return errors


def _codex_delivery_errors(
    evidence_path: Path,
    expected_plugins: dict[str, dict[str, object]],
) -> list[str]:
    try:
        document = json.loads(evidence_path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ["Codex plugin inventory is unreadable"]
    if not isinstance(document, dict) or not isinstance(document.get("installed"), list):
        return ["Codex plugin inventory installed entries are malformed"]

    errors: list[str] = []
    observed: dict[str, dict[str, object]] = {}
    for index, entry in enumerate(document["installed"]):
        if not isinstance(entry, dict):
            if _benchmark_looking(entry):
                errors.append(
                    f"Codex installed entry {index} has malformed benchmark plugin evidence"
                )
                if len(errors) == _MAX_DELIVERY_ERRORS:
                    break
            continue
        name = entry.get("name")
        plugin_id = entry.get("pluginId")
        benchmark_name = (
            name
            if isinstance(name, str) and name in _BENCHMARK_PLUGIN_NAMES
            else plugin_id.split("@", 1)[0]
            if isinstance(plugin_id, str)
            and plugin_id.split("@", 1)[0] in _BENCHMARK_PLUGIN_NAMES
            else None
        )
        if benchmark_name is None:
            identity = (name, plugin_id, entry.get("marketplaceName"))
            candidate = entry if all(value is None for value in identity) else identity
            if _benchmark_looking(candidate):
                errors.append(
                    f"Codex installed entry {index} has malformed benchmark plugin evidence"
                )
                if len(errors) == _MAX_DELIVERY_ERRORS:
                    break
            continue
        normalized = {
            field: entry.get(field)
            for field in (
                "name",
                "pluginId",
                "marketplaceName",
                "version",
                "enabled",
                "installed",
            )
        }
        expected_marketplace = (
            "superpowers-dev" if benchmark_name == "superpowers" else "studio-moser"
        )
        if (
            normalized["name"] != benchmark_name
            or normalized["pluginId"]
            != f"{benchmark_name}@{expected_marketplace}"
            or normalized["marketplaceName"] != expected_marketplace
            or not isinstance(normalized["version"], str)
            or normalized["enabled"] is not True
            or normalized["installed"] is not True
        ):
            errors.append(
                f"Codex installed entry {index} has malformed benchmark plugin evidence"
            )
            if len(errors) == _MAX_DELIVERY_ERRORS:
                break
            continue
        if benchmark_name in observed:
            errors.append(
                f"Codex installed entry {index} has ambiguous benchmark plugin {benchmark_name}"
            )
            if len(errors) == _MAX_DELIVERY_ERRORS:
                break
            continue
        observed[benchmark_name] = normalized
    if observed != expected_plugins:
        errors.append(
            "Codex benchmark plugins mismatch: "
            f"expected {sorted(expected_plugins)}, observed {sorted(observed)}"
        )
    return errors


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _completed_job_errors(
    root: Path,
    cell: RunCell,
    job_name: str,
    benchmark_skill_names: frozenset[str],
    *,
    expected_attempts: int,
) -> tuple[str, ...]:
    errors: list[str] = []
    job_dir = root / "jobs" / "raw" / job_name
    job_result = _read_json_object(job_dir / "result.json")
    if job_result is None:
        return (f"{job_name}: Harbor job result is unreadable",)
    stats = job_result.get("stats")
    n_total_trials = job_result.get("n_total_trials")
    if type(n_total_trials) is not int or n_total_trials != expected_attempts:
        errors.append(
            f"{job_name}: Harbor job trial count is invalid: "
            f"expected {expected_attempts}, observed {n_total_trials!r}"
        )
    expected_counts = {
        "n_completed_trials": expected_attempts,
        "n_errored_trials": 0,
        "n_running_trials": 0,
        "n_pending_trials": 0,
        "n_cancelled_trials": 0,
    }
    if not isinstance(stats, dict) or any(
        type(stats.get(name)) is not int or stats.get(name) != expected
        for name, expected in expected_counts.items()
    ):
        errors.append(
            f"{job_name}: Harbor job did not complete one clean trial per attempt"
        )

    trial_dirs = (
        sorted(
            path
            for path in job_dir.iterdir()
            if path.is_dir() and (path / "result.json").is_file()
        )
        if job_dir.is_dir()
        else []
    )
    if len(trial_dirs) != expected_attempts:
        errors.append(f"{job_name}: Harbor job has {len(trial_dirs)} trial results")
        return tuple(errors[:_MAX_DELIVERY_ERRORS])

    try:
        expected_plugin_records, expected_skills = _expected_runtime_delivery(root, cell)
    except (OSError, ValueError) as error:
        errors.append(f"{job_name}: arm delivery provenance is invalid: {error}")
        return tuple(errors[:_MAX_DELIVERY_ERRORS])
    expected_plugins = frozenset(expected_plugin_records)
    for trial_dir in trial_dirs:
        label = job_name if expected_attempts == 1 else f"{job_name}/{trial_dir.name}"
        trial_result = _read_json_object(trial_dir / "result.json")
        if trial_result is None:
            errors.append(f"{label}: Harbor trial result is unreadable")
        else:
            if "exception_info" not in trial_result:
                errors.append(f"{label}: Harbor trial exception evidence is missing")
            elif trial_result["exception_info"] is not None:
                errors.append(f"{label}: Harbor trial exception is present")
            verifier_result = trial_result.get("verifier_result")
            rewards = (
                verifier_result.get("rewards")
                if isinstance(verifier_result, dict)
                else None
            )
            if not isinstance(rewards, dict):
                errors.append(f"{label}: Harbor verifier rewards are missing")
        if _read_json_object(trial_dir / "verifier" / "reward.json") is None:
            errors.append(f"{label}: Harbor verifier reward artifact is unreadable")

        if cell.provider == "claude":
            delivery_errors = _claude_delivery_errors(
                trial_dir / "agent" / "claude-code.txt",
                expected_plugins,
                expected_skills,
                benchmark_skill_names,
            )
        else:
            delivery_errors = _codex_delivery_errors(
                trial_dir / "agent" / "plugin-inventory.json",
                expected_plugin_records,
            )
        errors.extend(f"{label}: {error}" for error in delivery_errors)
        if len(errors) >= _MAX_DELIVERY_ERRORS:
            break
    return tuple(errors[:_MAX_DELIVERY_ERRORS])


def _skill_evaluation_trials(
    root: Path, manifest: RunManifest
) -> tuple[dict[str, object], ...]:
    trials: list[dict[str, object]] = []
    cell_count = len(manifest.cells)
    for index, relative_path in enumerate(manifest.harbor_config_paths):
        cell = manifest.cells[index % cell_count]
        task_id = manifest.task_ids[index // cell_count]
        job_name = load_job(manifest.path.parent / relative_path).job_name
        job_dir = root / "jobs" / "raw" / job_name
        trial_dirs = sorted(
            path
            for path in job_dir.iterdir()
            if path.is_dir() and (path / "result.json").is_file()
        )
        trials.extend(
            {
                "provider": cell.provider,
                "cell": cell.label,
                "task": task_id,
                "attempt": attempt,
                "trajectory": trial_dir / "agent" / "trajectory.json",
            }
            for attempt, trial_dir in enumerate(trial_dirs, start=1)
        )
    if len(trials) != manifest.session_count:
        raise ValueError(
            "skill evaluation trial count does not match the approved manifest"
        )
    return tuple(trials)


def execute_run(root: Path, manifest_path: Path, approval: str) -> None:
    """Execute only a previously compiled manifest with an exact digest approval."""

    root = root.resolve()
    manifest = load_manifest(manifest_path)
    if approval != manifest.digest:
        raise ValueError(
            f"approval digest mismatch: expected {manifest.digest}, received {approval}"
        )
    failures = validate_repository(root)
    if failures:
        raise ValueError("repository validation failed: " + "; ".join(map(str, failures)))
    image_errors = dockerfile_policy_errors(root)
    if image_errors:
        raise ValueError("image policy validation failed: " + "; ".join(image_errors))
    _verify_generated_inputs(root, manifest)
    execution_environment = os.environ.copy()
    for name, _ in _SUBSCRIPTION_SELECTORS.values():
        execution_environment.pop(name, None)
    if manifest.billing_mode == "subscription":
        if any(cell.provider == "claude" for cell in manifest.cells):
            token = load_claude_subscription_token(os.environ)
            if token:
                execution_environment["CLAUDE_CODE_OAUTH_TOKEN"] = token
        _verify_subscription_auth(manifest.cells, execution_environment, Path.home())
        for selector in _subscription_selectors(manifest.cells).values():
            execution_environment[selector["name"]] = selector["value"]
    profile = _load_profile(root, manifest.profile)
    for image in _required_images(profile, manifest.task_ids):
        require_current_image(root, image)
    write_run_report(root, manifest, "running")
    try:
        benchmark_skill_names = _benchmark_skill_names(root, manifest.cells)
        canary_jobs: list[tuple[RunCell, str]] = []
        for index, relative_path in enumerate(manifest.harbor_config_paths):
            config_path = manifest.path.parent / relative_path
            cell = manifest.cells[index % len(manifest.cells)]
            job_name = load_job(config_path).job_name
            job_dir = root / "jobs" / "raw" / job_name
            if job_dir.exists():
                existing_errors = _completed_job_errors(
                    root,
                    cell,
                    job_name,
                    benchmark_skill_names,
                    expected_attempts=manifest.attempts,
                )
                if existing_errors:
                    raise ValueError(
                        "existing job is not resumable: " + "; ".join(existing_errors)
                    )
                print(f"Reusing completed job: {job_name}")
            else:
                subprocess.run(
                    harbor_command("run", "-c", str(config_path)),
                    cwd=root,
                    check=True,
                    env=execution_environment,
                )
            write_run_report(root, manifest, "running")
            if index < len(manifest.cells):
                canary_jobs.append((cell, job_name))
                if index + 1 == len(manifest.cells):
                    errors = [
                        error
                        for canary_cell, canary_job_name in canary_jobs
                        for error in _completed_job_errors(
                            root,
                            canary_cell,
                            canary_job_name,
                            benchmark_skill_names,
                            expected_attempts=manifest.attempts,
                        )
                    ][:_MAX_DELIVERY_ERRORS]
                    if errors:
                        raise ValueError("delivery canary failed: " + "; ".join(errors))
                continue
            errors = _completed_job_errors(
                root,
                cell,
                job_name,
                benchmark_skill_names,
                expected_attempts=manifest.attempts,
            )
            if errors:
                raise ValueError("job delivery failed: " + "; ".join(errors))
        if manifest.skill_evaluation is not None:
            report = write_skill_evaluation_report(
                manifest.path.parent / "Skill_Evaluation.json",
                manifest_digest=manifest.digest,
                evaluation=manifest.skill_evaluation,
                trials=_skill_evaluation_trials(root, manifest),
            )
            aggregate = report["aggregate"]
            if isinstance(aggregate, dict):
                print(
                    "Skill invocation: "
                    f"{aggregate['numerator']}/{aggregate['denominator']} "
                    f"({aggregate['rate']:.0%})"
                )
    except BaseException as error:
        try:
            write_run_report(root, manifest, "failed")
            refresh_local_dashboard(root)
        except Exception as report_error:
            error.add_note(f"Local dashboard refresh also failed: {report_error}")
        raise
    report_path = write_run_report(root, manifest, "completed")
    dashboard_path = refresh_local_dashboard(root)
    print(f"Local run report: {report_path}")
    if dashboard_path is not None:
        print(f"Local dashboard: {dashboard_path}")
