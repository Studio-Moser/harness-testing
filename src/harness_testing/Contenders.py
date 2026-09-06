"""Content-addressed complete collections, alongside legacy single-plugin arms."""

from __future__ import annotations

import io
import shutil
import tarfile
import tempfile
from pathlib import Path

import yaml

from harness_testing import Materialize as M
from harness_testing.Experiments import contender_identity


def _source_tree(root: Path, source: dict, target: Path) -> None:
    """Archive the actual pinned Git object, never trust a mutable extracted cache."""
    M._archive_repository(root, source["source"], source["commit"])
    repository = M._local_repository(source["source"])
    if repository is None:
        import hashlib

        key = hashlib.sha256(source["source"].encode()).hexdigest()
        repository = root / ".cache/source-repositories" / f"{key}.git"
    archive = M._run_git(
        ("--no-replace-objects", "archive", "--format=tar", source["commit"]), cwd=repository
    ).stdout
    target.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        stream.extractall(target, filter="data")


def _rubric_bytes(definition: dict) -> bytes | None:
    if definition["rubric"]["mode"] == "disabled":
        return None
    data = Path(definition["rubric"]["path"]).read_bytes()
    rubric = yaml.safe_load(data)
    if (
        not isinstance(rubric, dict)
        or rubric.get("seed")
        or not rubric.get("reviewed")
        or not rubric.get("routing")
        or not rubric.get("capabilities")
    ):
        raise ValueError(
            "rubric must be personalized, reviewed and contain capabilities and routes"
        )
    models = rubric.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("rubric must contain actual model/effort rows")
    names = {f"{row.get('name')}@{row.get('effort')}" for row in models if isinstance(row, dict)}
    if any(
        not isinstance(value, str) or value not in names
        for key, value in rubric["routing"].items()
        if key != "taste_min"
    ):
        raise ValueError("rubric routes must reference declared model/effort rows")
    if any(
        not isinstance(row, dict) or row.get("trust") is None or row.get("efficiency") is None
        for row in models
    ):
        raise ValueError("rubric model rows require personalized trust and efficiency")
    return data


def materialize_contender(
    root: Path, provider: str, definition: dict, *, native_cli: bool = True
) -> tuple[M.MaterializedArm, dict]:
    """Deliver every declared plugin/skill using the existing native installers."""
    if provider not in {"claude", "codex"}:
        raise ValueError("unsupported contender provider")
    rubric = _rubric_bytes(definition)
    cache = root / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as scratch:
        work = Path(scratch)
        bundle = work / "bundle"
        bundle.mkdir()
        inputs, sources, inventory, instructions = [], [], [], []
        names = set()
        for index, source in enumerate(definition["sources"]):
            tree = work / f"source-{index}"
            _source_tree(root, source, tree)
            sources.append(
                {
                    "name": source["name"],
                    "commit": source["commit"],
                    "tree_digest": M._tree_digest(tree),
                }
            )
            if source["kind"] == "collection":
                marketplace = M._read_json(
                    tree / ".claude-plugin/marketplace.json", "collection marketplace"
                )
                entries = marketplace.get("plugins", [])
                declared = []
                for entry in entries:
                    relative = entry.get("source")
                    if not isinstance(relative, str):
                        raise ValueError(
                            "collection dependencies must have pinned local plugin sources"
                        )
                    path = (tree / relative).resolve()
                    if not path.is_relative_to(tree.resolve()):
                        raise ValueError("plugin source escapes pinned collection")
                    declared.append(path)
                accounted = {
                    skill.resolve() for path in declared for skill in path.rglob("SKILL.md")
                }
                all_skills = {skill.resolve() for skill in tree.rglob("SKILL.md")}
                if all_skills != accounted:
                    raise ValueError("collection has skills outside its declared plugin inventory")
                baseline = tree / "plugins/harness/templates/AGENTS_Baseline.md"
                if baseline.is_file():
                    instructions.append(baseline.read_text())
            else:
                declared = [tree]
            for source_plugin in declared:
                manifest = M._read_json(
                    source_plugin / ".claude-plugin/plugin.json", "plugin manifest"
                )
                name, version = manifest.get("name"), manifest.get("version")
                if (
                    not isinstance(name, str)
                    or not M._SAFE_PLUGIN_NAME.fullmatch(name)
                    or name in names
                ):
                    raise ValueError(
                        "plugin names must be unique safe names across all dependencies"
                    )
                if not isinstance(version, str) or not M._SAFE_PLUGIN_VERSION.fullmatch(version):
                    raise ValueError(f"plugin version missing or invalid: {name}")
                names.add(name)
                # One native marketplace per plugin avoids changing shared marketplace paths.
                marketplace_name = f"experiment-{name}"
                marketplace_root = work / "marketplaces" / marketplace_name
                plugin = marketplace_root / "plugins" / name
                plugin.parent.mkdir(parents=True)
                shutil.copytree(source_plugin, plugin, symlinks=True)
                for skill in sorted(plugin.glob("skills/*/SKILL.md")):
                    inventory.append(f"{name}:{skill.parent.name}")
                if provider == "codex":
                    codex_manifest = plugin / ".codex-plugin/plugin.json"
                    if not codex_manifest.is_file():
                        converted = {
                            "name": name,
                            "version": version,
                            "description": manifest.get("description", name),
                            "skills": "./skills/",
                        }
                        if manifest.get("hooks"):
                            M._write_json(plugin / "hooks/hooks.json", {"hooks": manifest["hooks"]})
                        M._write_json(codex_manifest, converted)
                    M._write_json(
                        marketplace_root / ".agents/plugins/marketplace.json",
                        {
                            "name": marketplace_name,
                            "interface": {"displayName": name},
                            "plugins": [
                                {
                                    "name": name,
                                    "source": {"source": "local", "path": f"./plugins/{name}"},
                                    "policy": {
                                        "installation": "AVAILABLE",
                                        "authentication": "ON_INSTALL",
                                    },
                                    "category": "Developer Tools",
                                }
                            ],
                        },
                    )
                inputs.append(
                    M._PluginInput(
                        layer=name,
                        marketplace=marketplace_name,
                        plugin=name,
                        version=version,
                        path=marketplace_root,
                        plugin_path=plugin,
                    )
                )
        inputs = tuple(inputs)
        if provider == "claude":
            M._assemble_claude_bundle(bundle, inputs)
            if native_cli:
                M._run_claude_plugin_validation(root, bundle, inputs)
        else:
            native = work / "native"
            if native_cli:
                M._run_codex_plugin_install(root, inputs, native)
            M._assemble_codex_bundle(bundle, inputs, native, native_cli)
        instructions.extend(Path(path).read_text() for path in definition["startup_paths"])
        if definition["family"] != "nothing":
            if rubric is not None:
                rubric_path = bundle / "config/studio-moser/model-rubric.yml"
                rubric_path.parent.mkdir(parents=True)
                rubric_path.write_bytes(rubric)
                instructions.append(
                    "The frozen model rubric for this experiment is at "
                    "/harness-arm/config/studio-moser/model-rubric.yml. Use it for normal routing."
                )
            elif "harness" in names:
                instructions.append(
                    "The model-routing rubric is disabled for this harness version. "
                    "Use the native runtime's normal model selection "
                    "without requiring a rubric file."
                )
        if instructions:
            target = bundle / "project" / ("CLAUDE.md" if provider == "claude" else "AGENTS.md")
            target.parent.mkdir(parents=True)
            target.write_text("\n\n".join(instructions) + "\n")
        effective = {
            "provider": provider,
            "sources": sources,
            "inventory": sorted(inventory),
            "rubric_digest": M._sha256_bytes(rubric) if rubric else None,
            "delivery_config": definition["delivery_config"],
            "files": M._file_digests(bundle),
        }
        identity = contender_identity(effective)
        if definition.get("id") is not None and definition["id"] != identity:
            raise ValueError("contender content identity does not match requested identity")
        public = {
            "id": identity,
            "family": definition["family"],
            "label": definition["label"],
            "source_commits": [source["commit"] for source in sources],
            "inventory_digest": contender_identity({"skills": sorted(inventory)}),
            "rubric_digest": effective["rubric_digest"],
        }
        arm = "V" + identity.removeprefix("sha256:")[:16]
        surfaces = []
        for item in inputs:
            path = (
                f"/harness-arm/claude/plugins/{item.plugin}"
                if provider == "claude"
                else f"/harness-arm/codex/provider-home/plugins/cache/"
                f"{item.marketplace}/{item.plugin}/{item.version}"
            )
            surfaces.append(
                {
                    "layer": item.plugin,
                    "surface": "claude-plugin-dir" if provider == "claude" else "codex-plugin",
                    "path": path,
                    "capabilities": ["skills"],
                }
            )
        provenance = {
            "provider": provider,
            "arm": arm,
            "contender": public,
            "effective_inputs": effective,
            "delivery_surfaces": surfaces,
            "inventory": sorted(inventory),
            "generated_file_digests": M._file_digests(bundle),
        }
        digest = contender_identity(provenance)
        provenance["bundle_digest"] = digest
        M._write_json(bundle / "Provenance.json", provenance)
        destination = root / "arms/materialized" / provider / arm / digest.removeprefix("sha256:")
        if destination.exists():
            validate_contender_bundle(destination, identity, digest)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bundle, destination, symlinks=True)
            M._make_read_only(destination)
    return M.MaterializedArm(provider, arm, destination, digest), public


def validate_contender_bundle(path: Path, identity: str, digest: str) -> dict:
    provenance = M._read_json(path / "Provenance.json", "contender provenance")
    unsigned = {key: value for key, value in provenance.items() if key != "bundle_digest"}
    if contender_identity(unsigned) != digest or provenance.get("bundle_digest") != digest:
        raise ValueError("contender bundle provenance identity mismatch")
    if (
        contender_identity(provenance["effective_inputs"]) != identity
        or provenance["contender"]["id"] != identity
    ):
        raise ValueError("contender version identity mismatch")
    if M._file_digests(path) != provenance["generated_file_digests"]:
        raise ValueError("contender bundle contents changed")
    return provenance
