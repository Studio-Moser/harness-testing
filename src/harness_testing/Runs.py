"""Compile explicit, budget-guarded Harbor runs without starting them."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from harbor.models.job.config import JobConfig

from harness_testing.Config import load_job, load_versions
from harness_testing.Materialize import (
    _ARM_LAYERS,
    DEEPSWE_TASK_IDS,
    MaterializedDeepSWE,
    dockerfile_policy_errors,
    image_input_digest,
    load_deepswe_dataset,
    materialize_arm,
    require_current_image,
)
from harness_testing.Validate import find_sensitive_keys, validate_repository

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PROVIDER_ORDER = {"claude": 0, "codex": 1}
_ROLE_ORDER = {"baseline": 0, "candidate": 1, "calibration": 2}
_BILLING_MODES = {"api", "subscription"}
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
    if not provenance_path.is_file():
        raise ValueError(f"bundle has no materialized provenance: {bundle}")
    try:
        provenance = json.loads(provenance_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"bundle provenance is invalid: {bundle}") from error
    if not isinstance(provenance, dict):
        raise ValueError(f"bundle provenance must be an object: {bundle}")
    return provenance


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
) -> str:
    plugin = _LAYER_PLUGIN_NAMES[layer]
    manifest = _plugin_manifest(target, provider)
    target_plugin = target.name if provider == "claude" else target.parent.name
    if target_plugin != plugin or manifest.get("name") != plugin:
        raise ValueError(f"delivery target is not canonical for layer {layer}")
    if provider == "claude":
        return f"/harness-arm/claude/plugins/{plugin}"

    root = bundle.parents[4]
    source_versions = {
        str(source["name"]): str(source["version"])
        for source in load_versions(root / "Versions.toml").get("sources", [])
        if isinstance(source, dict)
        and isinstance(source.get("name"), str)
        and isinstance(source.get("version"), str)
    }
    marketplace = _CODEX_LAYER_MARKETPLACES[layer]
    version = source_versions.get(layer)
    if version is None:
        raise ValueError(f"canonical source version is missing for layer {layer}")
    cache_root = bundle / "codex" / "provider-home" / "plugins" / "cache"
    try:
        actual_marketplace, plugin_name, actual_version = target.relative_to(cache_root).parts
    except ValueError as error:
        raise ValueError(f"delivery target is not canonical for layer {layer}") from error
    if (
        actual_marketplace != marketplace
        or plugin_name != plugin
        or actual_version != version
        or not isinstance(manifest.get("version"), str)
        or manifest["version"] != version
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
        canonical_path = _canonical_delivery_path(bundle, provider, layer, target)
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
    provenance = _bundle_provenance(bundle_path)
    if (
        provenance.get("provider") != cell.provider
        or provenance.get("arm") != cell.arm
        or provenance.get("bundle_digest") != cell.bundle_digest
    ):
        raise ValueError(f"cell {cell.label} arm provenance does not match its digest")
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


def _task_pack(root: Path, profile: _Profile, task_id: str) -> str:
    matches = [
        pack for pack in profile.packs if (root / "tasks" / pack / task_id).is_dir()
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches and len(profile.packs) == 1:
        return profile.packs[0]
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
    agent_adapter_digests = {
        provider: _sha256((root / path).read_bytes())
        for provider, (_, path) in _AGENT_ADAPTERS.items()
    }
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
    actual_adapter_digests = {
        provider: _sha256((root / path).read_bytes())
        for provider, (_, path) in _AGENT_ADAPTERS.items()
    }
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
        _verify_subscription_auth(manifest.cells, os.environ, Path.home())
        for selector in _subscription_selectors(manifest.cells).values():
            execution_environment[selector["name"]] = selector["value"]
    profile = _load_profile(root, manifest.profile)
    for image in _required_images(profile, manifest.task_ids):
        require_current_image(root, image)
    for relative_path in manifest.harbor_config_paths:
        subprocess.run(
            ("harbor", "run", "-c", str(manifest.path.parent / relative_path)),
            cwd=root,
            check=True,
            env=execution_environment,
        )
