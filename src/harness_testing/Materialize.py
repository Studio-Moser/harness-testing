"""Materialize immutable benchmark inputs and pinned container images."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from harness_testing.Config import load_versions

_IMAGE_DOCKERFILES = {
    "node": "Node_Agent.Dockerfile",
    "rust": "Rust_Agent.Dockerfile",
    "verifier": "Verifier.Dockerfile",
}
_IMAGE_INPUTS = {
    "node": ("images/Node_Agent.Dockerfile",),
    "rust": ("images/Rust_Agent.Dockerfile",),
    "verifier": (
        "images/Verifier.Dockerfile",
        "src/harness_testing/__init__.py",
        "src/harness_testing/Contract_Criteria.py",
        "src/harness_testing/Contract_Stub_Server.py",
        "src/harness_testing/Trajectory_Events.py",
        "src/harness_testing/Workflow_Criteria.py",
    ),
}
_IMAGE_INPUT_LABEL = "studio.moser.harness-testing.input-digest"

_ARM_LAYERS = {
    "A0": (),
    "A1": ("Superpowers",),
    "A2": ("Studio Harness",),
    "A3": ("Superpowers", "Studio Harness"),
}
_EXACT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_PLUGIN_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class ImageBuildCommand:
    image: str
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class MaterializedArm:
    provider: str
    arm: str
    path: Path
    digest: str


@dataclass(frozen=True)
class _SourceTree:
    name: str
    url: str
    version: str
    commit: str
    path: Path
    digest: str


@dataclass(frozen=True)
class _PluginInput:
    layer: str
    marketplace: str
    plugin: str
    version: str
    path: Path
    plugin_path: Path


def _container_reference(container: dict[str, object]) -> str:
    return f"{container['image']}:{container['tag']}@{container['digest']}"


def _package_versions(versions: dict[str, object]) -> dict[str, str]:
    return {
        str(package["name"]): str(package["version"])
        for package in versions.get("packages", [])
    }


def dockerfile_policy_errors(root: Path) -> tuple[str, ...]:
    versions = load_versions(root / "Versions.toml")
    containers = {
        str(container["name"]): _container_reference(container)
        for container in versions.get("containers", [])
    }
    packages = _package_versions(versions)
    expected_from = {
        "Node_Agent.Dockerfile": (containers["node"],),
        "Rust_Agent.Dockerfile": (containers["node"], containers["rust"]),
        "Verifier.Dockerfile": (containers["python"],),
    }
    required_fragments = {
        "Node_Agent.Dockerfile": (
            f"@anthropic-ai/claude-code@{packages['@anthropic-ai/claude-code']}",
            f"@openai/codex@{packages['@openai/codex']}",
            "claude --version",
            "codex --version",
        ),
        "Rust_Agent.Dockerfile": (
            f"@anthropic-ai/claude-code@{packages['@anthropic-ai/claude-code']}",
            f"@openai/codex@{packages['@openai/codex']}",
            "node --version",
            "claude --version",
            "codex --version",
            "rustc --version",
            "cargo --version",
        ),
        "Verifier.Dockerfile": (
            f"harbor-rewardkit=={packages['harbor-rewardkit']}",
            "rewardkit --help",
        ),
    }

    errors: list[str] = []
    for filename, expected_references in expected_from.items():
        path = root / "images" / filename
        if not path.is_file():
            errors.append(f"{filename}: missing")
            continue
        text = path.read_text()
        actual_references = tuple(
            line.split()[1]
            for line in text.splitlines()
            if line.lstrip().upper().startswith("FROM ")
        )
        if actual_references != expected_references:
            errors.append(
                f"{filename}: FROM references {actual_references!r}; "
                f"expected {expected_references!r}"
            )
        for fragment in required_fragments[filename]:
            if fragment not in text:
                errors.append(f"{filename}: required pinned command is missing: {fragment}")
        for line in text.splitlines():
            directive = line.lstrip().upper()
            if directive.startswith(("CMD ", "ENTRYPOINT ")) and re.search(
                r"\b(?:curl|npm|pip|uvx)\b", line, re.IGNORECASE
            ):
                errors.append(f"{filename}: runtime entrypoint downloads packages")
    return tuple(errors)


def image_input_digest(root: Path, image: str) -> str:
    inputs = _IMAGE_INPUTS.get(image)
    if inputs is None:
        raise ValueError(f"unknown image: {image}")
    digest = hashlib.sha256()
    for relative in inputs:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"image input is missing: {path}")
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def image_reference(root: Path, image: str) -> str:
    if image not in _IMAGE_DOCKERFILES:
        raise ValueError(f"unknown image: {image}")
    return f"studio-moser/harness-testing-{image}:{_schema_version(root)}"


def image_is_current(root: Path, image: str) -> bool:
    result = subprocess.run(
        (
            "docker",
            "image",
            "inspect",
            "--format",
            f'{{{{ index .Config.Labels "{_IMAGE_INPUT_LABEL}" }}}}',
            image_reference(root, image),
        ),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == image_input_digest(root, image)


def require_current_image(root: Path, image: str) -> None:
    if not image_is_current(root, image):
        raise ValueError(
            f"local {image} image is missing or stale; run "
            f"harness-test images build --{image}"
        )


def image_build_commands(
    root: Path, selected_images: Iterable[str]
) -> tuple[ImageBuildCommand, ...]:
    versions = load_versions(root / "Versions.toml")
    schema_version = str(versions["repository"]["schema_version"])
    commands: list[ImageBuildCommand] = []
    for image in selected_images:
        if image not in _IMAGE_DOCKERFILES:
            raise ValueError(f"unknown image: {image}")
        dockerfile = root / "images" / _IMAGE_DOCKERFILES[image]
        input_digest = image_input_digest(root, image)
        commands.append(
            ImageBuildCommand(
                image=image,
                arguments=(
                    "docker",
                    "buildx",
                    "build",
                    "--load",
                    "--label",
                    f"{_IMAGE_INPUT_LABEL}={input_digest}",
                    "--file",
                    str(dockerfile),
                    "--tag",
                    f"studio-moser/harness-testing-{image}:{schema_version}",
                    str(root),
                ),
            )
        )
    return tuple(commands)


def build_images(root: Path, selected_images: Iterable[str]) -> None:
    errors = dockerfile_policy_errors(root)
    if errors:
        raise ValueError("; ".join(errors))
    for command in image_build_commands(root, selected_images):
        subprocess.run(command.arguments, cwd=root, check=True)
        require_current_image(root, command.image)


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _run_git(arguments: tuple[str, ...], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ("git", *arguments),
        cwd=cwd,
        env=_git_environment(),
        check=True,
        capture_output=True,
    )


def _sha256_bytes(contents: bytes) -> str:
    return f"sha256:{hashlib.sha256(contents).hexdigest()}"


def _path_payload(path: Path) -> bytes:
    if path.is_symlink():
        return f"symlink:{os.readlink(path)}".encode()
    return path.read_bytes()


def _file_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256_bytes(_path_payload(path))
        for path in sorted(root.rglob("*"))
        if (path.is_file() or path.is_symlink()) and path != root / "Provenance.json"
    }


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not (path.is_file() or path.is_symlink()):
            continue
        relative_path = path.relative_to(root).as_posix().encode()
        mode = stat.S_IMODE(path.lstat().st_mode)
        payload = _path_payload(path)
        digest.update(relative_path)
        digest.update(b"\0")
        digest.update(f"{mode:o}".encode())
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _schema_version(root: Path) -> str:
    versions_path = root / "Versions.toml"
    if not versions_path.is_file():
        return "0.1.0"
    return str(load_versions(versions_path)["repository"]["schema_version"])


def _source_pins(root: Path) -> dict[str, dict[str, object]]:
    versions = load_versions(root / "Versions.toml")
    return {str(source["name"]): source for source in versions.get("sources", [])}


def _require_exact_commit(commit: str) -> None:
    if not _EXACT_COMMIT.fullmatch(commit):
        raise ValueError("source pin must be a 40-character lowercase commit")


def _safe_source_url(source: str | Path, repository: Path | None) -> str:
    if repository is not None:
        try:
            remote = (
                _run_git(("remote", "get-url", "origin"), cwd=repository)
                .stdout.decode()
                .strip()
            )
        except subprocess.CalledProcessError:
            return "local-git"
        source = remote
    text = str(source)
    if text.startswith("git@github.com:"):
        return f"https://github.com/{text.removeprefix('git@github.com:')}"
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https", "ssh", "git"}:
        return "local-git"
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path, parsed.query, ""))


def _local_repository(source: str | Path) -> Path | None:
    candidate = Path(source).expanduser()
    return candidate.resolve() if candidate.exists() else None


def _validate_local_repository(repository: Path, commit: str) -> None:
    try:
        status = _run_git(("status", "--porcelain", "--untracked-files=all"), cwd=repository)
        _run_git(("cat-file", "-e", f"{commit}^{{commit}}"), cwd=repository)
    except subprocess.CalledProcessError as error:
        raise ValueError(f"source is not a Git repository containing {commit}") from error
    if status.stdout.strip():
        raise ValueError(f"candidate source is dirty: {repository}")


def _archive_repository(root: Path, source: str | Path, commit: str) -> tuple[Path, str]:
    _require_exact_commit(commit)
    repository = _local_repository(source)
    source_url = _safe_source_url(source, repository)
    if repository is not None:
        _validate_local_repository(repository, commit)
        git_directory = repository
    else:
        cache_key = hashlib.sha256(str(source).encode()).hexdigest()
        git_directory = root / ".cache" / "source-repositories" / f"{cache_key}.git"
        if not git_directory.is_dir():
            git_directory.parent.mkdir(parents=True, exist_ok=True)
            _run_git(("init", "--bare", str(git_directory)))
            _run_git(("remote", "add", "origin", str(source)), cwd=git_directory)
        try:
            _run_git(("cat-file", "-e", f"{commit}^{{commit}}"), cwd=git_directory)
        except subprocess.CalledProcessError:
            try:
                _run_git(("fetch", "--depth", "1", "origin", commit), cwd=git_directory)
            except subprocess.CalledProcessError as error:
                raise ValueError(f"source does not contain pinned commit {commit}") from error

    archive_key = hashlib.sha256(f"{source_url}\0{commit}".encode()).hexdigest()
    destination = root / ".cache" / "source-trees" / archive_key
    if destination.is_dir():
        return destination, source_url

    try:
        archive = _run_git(("archive", "--format=tar", commit), cwd=git_directory).stdout
    except subprocess.CalledProcessError as error:
        raise ValueError(f"could not archive pinned commit {commit}") from error
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary_directory:
        extracted = Path(temporary_directory) / "tree"
        extracted.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as archive_file:
            archive_file.extractall(extracted, filter="data")
        with suppress(FileExistsError):
            extracted.rename(destination)
    return destination, source_url


def _resolve_source_trees(
    root: Path,
    layers: tuple[str, ...],
    source_overrides: Mapping[str, tuple[str | Path, str]],
) -> tuple[_SourceTree, ...]:
    pins = _source_pins(root) if (root / "Versions.toml").is_file() else {}
    resolved: list[_SourceTree] = []
    for layer in layers:
        pin = pins.get(layer, {})
        if layer in source_overrides:
            source, commit = source_overrides[layer]
        else:
            if not pin:
                raise ValueError(f"Versions.toml has no source pin for {layer}")
            source, commit = str(pin["url"]), str(pin["commit"])
        _require_exact_commit(commit)
        path, source_url = _archive_repository(root, source, commit)
        resolved.append(
            _SourceTree(
                name=layer,
                url=source_url if layer in source_overrides else str(pin["url"]),
                version=str(pin.get("version", "fixture")),
                commit=commit,
                path=path,
                digest=_tree_digest(path),
            )
        )
    return tuple(resolved)


def _read_json(path: Path, description: str) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"missing expected {description}: {path}")
    try:
        value = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid {description}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid {description}: {path}")
    return value


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, symlinks=True)


def _plugin_entry(marketplace: dict[str, object], plugin_name: str) -> dict[str, object]:
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        raise ValueError("plugin marketplace has no plugins list")
    for plugin in plugins:
        if isinstance(plugin, dict) and plugin.get("name") == plugin_name:
            return plugin
    raise ValueError(f"plugin marketplace has no {plugin_name} entry")


def _prepare_plugin_inputs(
    work: Path, provider: str, sources: tuple[_SourceTree, ...]
) -> tuple[_PluginInput, ...]:
    inputs: list[_PluginInput] = []
    for source in sources:
        if source.name == "Superpowers":
            claude_manifest = _read_json(
                source.path / ".claude-plugin" / "plugin.json", "Claude plugin manifest"
            )
            codex_manifest = _read_json(
                source.path / ".codex-plugin" / "plugin.json", "Codex plugin manifest"
            )
            if claude_manifest.get("name") != "superpowers" or codex_manifest.get(
                "name"
            ) != "superpowers":
                raise ValueError("Superpowers plugin manifests do not match the source pin")
            marketplace_path = (
                source.path / ".claude-plugin" / "marketplace.json"
                if provider == "claude"
                else source.path / ".agents" / "plugins" / "marketplace.json"
            )
            marketplace = _read_json(marketplace_path, f"{provider} marketplace")
            marketplace_name = str(marketplace.get("name", ""))
            plugin_path = source.path
            version = str(claude_manifest.get("version", codex_manifest.get("version", "")))
            marketplace_root = source.path
        elif source.name == "Studio Harness":
            plugin_path = source.path / "plugins" / "harness"
            manifest = _read_json(
                plugin_path / ".claude-plugin" / "plugin.json", "Harness Claude plugin manifest"
            )
            for required_path in (
                plugin_path / "skills",
                plugin_path / "templates" / "AGENTS_Baseline.md",
                plugin_path / "references" / "house-rules.md",
            ):
                if not required_path.exists():
                    raise ValueError(f"missing expected Harness input: {required_path}")
            if provider == "codex":
                continue
            original = _read_json(
                source.path / ".claude-plugin" / "marketplace.json",
                "Harness Claude marketplace",
            )
            harness_entry = dict(_plugin_entry(original, "harness"))
            harness_entry["source"] = "./plugins/harness"
            marketplace_name = str(original.get("name", "studio-moser"))
            marketplace_root = work / "marketplaces" / marketplace_name
            (marketplace_root / ".claude-plugin").mkdir(parents=True)
            (marketplace_root / ".claude-plugin" / "marketplace.json").write_text(
                json.dumps(
                    {
                        "name": marketplace_name,
                        "owner": original.get("owner", {"name": "Studio Moser"}),
                        "plugins": [harness_entry],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            (marketplace_root / "plugins").mkdir()
            _copy_tree(plugin_path, marketplace_root / "plugins" / "harness")
            plugin_path = marketplace_root / "plugins" / "harness"
            version = str(manifest.get("version", ""))
        else:
            raise ValueError(f"unsupported arm layer: {source.name}")

        if not _SAFE_PLUGIN_NAME.fullmatch(marketplace_name):
            raise ValueError(f"invalid marketplace name: {marketplace_name}")
        if not version:
            raise ValueError(f"plugin version is missing for {source.name}")
        plugin_name = "superpowers" if source.name == "Superpowers" else "harness"
        inputs.append(
            _PluginInput(
                layer=source.name,
                marketplace=marketplace_name,
                plugin=plugin_name,
                version=version,
                path=marketplace_root,
                plugin_path=plugin_path,
            )
        )
    return tuple(inputs)


def _node_image(root: Path) -> str:
    return f"studio-moser/harness-testing-node:{_schema_version(root)}"


def _run_native_plugin_install(
    root: Path, provider: str, inputs: tuple[_PluginInput, ...], output: Path
) -> None:
    if not inputs:
        return
    output.mkdir(parents=True)
    docker_arguments = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-e",
        "HOME=/output/home",
    ]
    commands = ["mkdir -p /output/home"]
    if provider == "claude":
        docker_arguments.extend(
            (
                "-e",
                "CLAUDE_CONFIG_DIR=/output/config",
                "-e",
                "CLAUDE_CODE_PLUGIN_CACHE_DIR=/output/plugin-seed",
            )
        )
    else:
        docker_arguments.extend(("-e", "CODEX_HOME=/output/provider-home"))
    for plugin_input in inputs:
        container_source = f"/sources/{plugin_input.marketplace}"
        docker_arguments.extend(("-v", f"{plugin_input.path}:{container_source}:ro"))
        if provider == "claude":
            commands.extend(
                (
                    f"claude plugin marketplace add {shlex.quote(container_source)} --scope user",
                    "claude plugin install "
                    f"{shlex.quote(f'{plugin_input.plugin}@{plugin_input.marketplace}')} "
                    "--scope user",
                )
            )
        else:
            commands.extend(
                (
                    f"codex plugin marketplace add {shlex.quote(container_source)} --json",
                    "codex plugin add "
                    f"{shlex.quote(f'{plugin_input.plugin}@{plugin_input.marketplace}')} --json",
                )
            )
    docker_arguments.extend(
        (
            "-v",
            f"{output}:/output",
            _node_image(root),
            "sh",
            "-lc",
            " && ".join(commands),
        )
    )
    completed = subprocess.run(docker_arguments, text=True, capture_output=True)
    if completed.returncode:
        details = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"{provider} native plugin installation failed: {details}")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _installed_plugin_source(
    provider: str,
    native_output: Path,
    plugin_input: _PluginInput,
    native_cli: bool,
) -> Path:
    if not native_cli:
        return plugin_input.plugin_path
    if provider == "claude":
        path = (
            native_output
            / "plugin-seed"
            / "cache"
            / plugin_input.marketplace
            / plugin_input.plugin
            / plugin_input.version
        )
    else:
        path = (
            native_output
            / "provider-home"
            / "plugins"
            / "cache"
            / plugin_input.marketplace
            / plugin_input.plugin
            / plugin_input.version
        )
    if not path.is_dir():
        raise ValueError(f"native plugin installer did not create {path}")
    return path


def _copy_harness_project_inputs(bundle: Path, provider: str, source: _SourceTree) -> None:
    harness = source.path / "plugins" / "harness"
    baseline = (harness / "templates" / "AGENTS_Baseline.md").read_text().rstrip()
    house_rules = (harness / "references" / "house-rules.md").read_text().rstrip()
    filename = "CLAUDE.md" if provider == "claude" else "AGENTS.md"
    project_file = bundle / "project" / filename
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text(f"{baseline}\n\n{house_rules}\n")
    if provider == "codex":
        _copy_tree(harness / "skills", bundle / "skills")


def _assemble_claude_bundle(
    bundle: Path,
    inputs: tuple[_PluginInput, ...],
    native_output: Path,
    native_cli: bool,
) -> None:
    if not inputs:
        return
    seed = bundle / "claude" / "plugin-seed"
    enabled_plugins: dict[str, bool] = {}
    known_marketplaces: dict[str, object] = {}
    for plugin_input in inputs:
        source = _installed_plugin_source("claude", native_output, plugin_input, native_cli)
        cache_path = (
            seed
            / "cache"
            / plugin_input.marketplace
            / plugin_input.plugin
            / plugin_input.version
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree(source, cache_path)
        marketplace_path = seed / "marketplaces" / plugin_input.marketplace
        marketplace_path.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree(plugin_input.path, marketplace_path)
        mounted_path = f"/harness-arm/claude/plugin-seed/marketplaces/{plugin_input.marketplace}"
        known_marketplaces[plugin_input.marketplace] = {
            "installLocation": mounted_path,
            "source": {"path": mounted_path, "source": "directory"},
        }
        enabled_plugins[f"{plugin_input.plugin}@{plugin_input.marketplace}"] = True
    _write_json(seed / "known_marketplaces.json", known_marketplaces)
    _write_json(bundle / "claude" / "settings.json", {"enabledPlugins": enabled_plugins})


def _codex_config(inputs: tuple[_PluginInput, ...]) -> str:
    sections: list[str] = []
    for plugin_input in inputs:
        mounted_source = (
            f'/harness-arm/codex/provider-home/marketplaces/{plugin_input.marketplace}'
        )
        sections.extend(
            (
                f"[marketplaces.{plugin_input.marketplace}]",
                'source_type = "local"',
                f'source = "{mounted_source}"',
                "",
                f'[plugins."{plugin_input.plugin}@{plugin_input.marketplace}"]',
                "enabled = true",
                "",
            )
        )
    return "\n".join(sections)


def _assemble_codex_bundle(
    bundle: Path,
    inputs: tuple[_PluginInput, ...],
    native_output: Path,
    native_cli: bool,
) -> None:
    if not inputs:
        return
    provider_home = bundle / "codex" / "provider-home"
    for plugin_input in inputs:
        source = _installed_plugin_source("codex", native_output, plugin_input, native_cli)
        cache_path = (
            provider_home
            / "plugins"
            / "cache"
            / plugin_input.marketplace
            / plugin_input.plugin
            / plugin_input.version
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree(source, cache_path)
        marketplace_path = provider_home / "marketplaces" / plugin_input.marketplace
        marketplace_path.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree(plugin_input.path, marketplace_path)
    (provider_home / "config.toml").write_text(_codex_config(inputs))


def _delivery_surfaces(
    provider: str,
    sources: tuple[_SourceTree, ...],
    inputs: tuple[_PluginInput, ...],
) -> list[dict[str, object]]:
    plugin_inputs = {plugin_input.layer: plugin_input for plugin_input in inputs}
    surfaces: list[dict[str, object]] = []
    for source in sources:
        if provider == "claude":
            plugin = plugin_inputs[source.name]
            capabilities = ["skills"]
            if (plugin.plugin_path / "hooks").is_dir():
                capabilities.append("hooks")
            surface = "claude-plugin-seed"
        elif source.name == "Superpowers":
            manifest = _read_json(
                source.path / ".codex-plugin" / "plugin.json", "Codex plugin manifest"
            )
            capabilities = ["skills"]
            hooks = manifest.get("hooks")
            if isinstance(hooks, dict) and hooks:
                capabilities.append("hooks")
            surface = "codex-plugin"
        else:
            capabilities = ["skills"]
            surface = "harbor-skills"
        surfaces.append(
            {"layer": source.name, "surface": surface, "capabilities": capabilities}
        )
    return surfaces


def _make_read_only(root: Path) -> None:
    directories: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_dir():
            directories.append(path)
            continue
        executable = bool(path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        path.chmod(0o555 if executable else 0o444)
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        directory.chmod(0o555)
    root.chmod(0o555)


def _validate_existing_bundle(path: Path, digest: str) -> None:
    provenance_path = path / "Provenance.json"
    provenance = _read_json(provenance_path, "arm provenance")
    if provenance.get("bundle_digest") != digest:
        raise ValueError(f"existing materialized arm has invalid provenance: {path}")
    if provenance.get("generated_file_digests") != _file_digests(path):
        raise ValueError(f"existing materialized arm contents do not match provenance: {path}")


def _find_existing_bundle(
    root: Path,
    provider: str,
    arm: str,
    layers: tuple[str, ...],
    sources: tuple[_SourceTree, ...],
) -> MaterializedArm | None:
    arm_root = root / "arms" / "materialized" / provider / arm
    if not arm_root.is_dir():
        return None
    expected_sources = [
        {
            "name": source.name,
            "url": source.url,
            "version": source.version,
            "commit": source.commit,
            "source_tree_digest": source.digest,
        }
        for source in sources
    ]
    for path in sorted(arm_root.iterdir()):
        provenance_path = path / "Provenance.json"
        if not provenance_path.is_file():
            continue
        provenance = _read_json(provenance_path, "arm provenance")
        if (
            provenance.get("provider") != provider
            or provenance.get("arm") != arm
            or provenance.get("layers") != list(layers)
            or provenance.get("sources") != expected_sources
            or provenance.get("materializer_schema") != _schema_version(root)
        ):
            continue
        digest = str(provenance.get("bundle_digest", ""))
        if path.name != digest.removeprefix("sha256:"):
            raise ValueError(f"materialized arm path does not match provenance: {path}")
        _validate_existing_bundle(path, digest)
        return MaterializedArm(provider=provider, arm=arm, path=path, digest=digest)
    return None


def materialize_arm(
    root: Path,
    provider: str,
    arm: str,
    *,
    harness_source: str | Path | None = None,
    harness_commit: str | None = None,
    source_overrides: Mapping[str, tuple[str | Path, str]] | None = None,
    native_cli: bool = True,
) -> MaterializedArm:
    """Create one immutable provider arm without starting a model session."""

    root = root.resolve()
    if provider not in {"claude", "codex"}:
        raise ValueError(f"unsupported provider: {provider}")
    if arm not in _ARM_LAYERS:
        raise ValueError(f"unsupported arm: {arm}")
    if (harness_source is None) != (harness_commit is None):
        raise ValueError("--harness-source and --harness-commit must be provided together")
    overrides = dict(source_overrides or {})
    if harness_source is not None and harness_commit is not None:
        overrides["Studio Harness"] = (harness_source, harness_commit)

    layers = _ARM_LAYERS[arm]
    sources = _resolve_source_trees(root, layers, overrides)
    if existing := _find_existing_bundle(root, provider, arm, layers, sources):
        return existing
    cache_root = root / ".cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache_root) as temporary_directory:
        temporary = Path(temporary_directory)
        work = temporary / "work"
        bundle = temporary / "bundle"
        work.mkdir()
        bundle.mkdir()
        plugin_inputs = _prepare_plugin_inputs(work, provider, sources)
        native_output = temporary / "native-output"
        if native_cli:
            _run_native_plugin_install(root, provider, plugin_inputs, native_output)
        if provider == "claude":
            _assemble_claude_bundle(bundle, plugin_inputs, native_output, native_cli)
        else:
            _assemble_codex_bundle(bundle, plugin_inputs, native_output, native_cli)

        harness = next((source for source in sources if source.name == "Studio Harness"), None)
        if harness is not None:
            _copy_harness_project_inputs(bundle, provider, harness)

        generated_file_digests = _file_digests(bundle)
        provenance: dict[str, object] = {
            "provider": provider,
            "arm": arm,
            "layers": list(layers),
            "sources": [
                {
                    "name": source.name,
                    "url": source.url,
                    "version": source.version,
                    "commit": source.commit,
                    "source_tree_digest": source.digest,
                }
                for source in sources
            ],
            "delivery_surfaces": _delivery_surfaces(provider, sources, plugin_inputs),
            "generated_file_digests": generated_file_digests,
            "materializer_schema": _schema_version(root),
        }
        digest = _sha256_bytes(_canonical_json(provenance))
        provenance["bundle_digest"] = digest
        _write_json(bundle / "Provenance.json", provenance)

        destination = (
            root
            / "arms"
            / "materialized"
            / provider
            / arm
            / digest.removeprefix("sha256:")
        )
        if destination.exists():
            _validate_existing_bundle(destination, digest)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_tree(bundle, destination)
            _make_read_only(destination)
    return MaterializedArm(provider=provider, arm=arm, path=destination, digest=digest)
