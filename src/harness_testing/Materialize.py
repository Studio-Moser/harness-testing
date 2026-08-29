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
import tomllib
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
_SAFE_IMAGE_USER = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SAFE_PLATFORM = re.compile(r"^[a-z0-9]+/[a-z0-9_]+$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_DEEPSWE_IMAGE_LABEL = "studio.moser.harness-testing.deepswe-input-digest"

DEEPSWE_TASK_IDS = (
    "happy-dom-abort-pending-body-reads",
    "quill-shared-toolbar-focus",
    "yjs-map-conflict-detection",
    "katex-multicolumn-array-spans",
    "wasmi-trap-coredumps",
    "pest-character-class-coalescing",
)


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
class DeepSWEMaterializationPlan:
    source_url: str
    commit: str
    task_ids: tuple[str, ...]
    original_images: tuple[str, ...]
    original_image_digests: tuple[str, ...]
    platform: str
    cache_path: Path


@dataclass(frozen=True)
class DeepSWEImageProvenance:
    original_image: str
    original_image_reference: str
    original_manifest_digest: str
    original_image_digest: str
    derived_image: str
    derived_image_digest: str
    verifier_image: str
    verifier_image_digest: str
    platform: str
    starting_repository_commit: str
    starting_repository_digest: str
    starting_repository_files: dict[str, str]
    agent_tools_image_digest: str | None = None


@dataclass(frozen=True)
class MaterializedDeepSWE:
    path: Path
    digest: str

    @property
    def tasks_path(self) -> Path:
        return self.path / "tasks"

    @property
    def provenance_path(self) -> Path:
        return self.path / "Provenance.json"


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


def _platform_image_reference(root: Path, image: str, platform: str) -> str:
    if image not in _IMAGE_DOCKERFILES:
        raise ValueError(f"unknown image: {image}")
    if not _SAFE_PLATFORM.fullmatch(platform):
        raise ValueError(f"unsafe container platform: {platform}")
    platform_tag = platform.replace("/", "-").replace("_", "-")
    return (
        f"studio-moser/harness-testing-{image}:"
        f"{_schema_version(root)}-{platform_tag}"
    )


def _platform_agent_tools_build_arguments(
    root: Path, platform: str
) -> tuple[str, ...]:
    return (
        "docker",
        "buildx",
        "build",
        "--load",
        "--platform",
        platform,
        "--label",
        f"{_IMAGE_INPUT_LABEL}={image_input_digest(root, 'node')}",
        "--file",
        str(root / "images" / _IMAGE_DOCKERFILES["node"]),
        "--tag",
        _platform_image_reference(root, "node", platform),
        str(root),
    )


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


def _byte_tree_digest(root: Path) -> str:
    return _sha256_bytes(_canonical_json(_file_digests(root)))


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


def _deepswe_configuration(
    root: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    tuple[dict[str, str], ...],
    str,
]:
    versions = load_versions(root / "Versions.toml")
    sources = [
        source
        for source in versions.get("sources", [])
        if source.get("name") == "DeepSWE"
    ]
    configuration = versions.get("deepswe")
    if len(sources) != 1 or not isinstance(configuration, dict):
        raise ValueError("Versions.toml requires one DeepSWE source and configuration")
    source = sources[0]
    tasks = configuration.get("tasks")
    if not isinstance(tasks, list) or not all(isinstance(task, dict) for task in tasks):
        raise ValueError("Versions.toml requires the pinned DeepSWE task cohort")
    normalized = tuple(
        {
            "id": str(task.get("id", "")),
            "image": str(task.get("image", "")),
            "digest": str(task.get("digest", "")),
        }
        for task in tasks
    )
    if tuple(task["id"] for task in normalized) != DEEPSWE_TASK_IDS or any(
        not task["image"] or not _SHA256_DIGEST.fullmatch(task["digest"])
        for task in normalized
    ):
        raise ValueError("Versions.toml DeepSWE cohort does not match the six-task pin")
    if source.get("redistribute") is not False:
        raise ValueError("DeepSWE redistribution must remain disabled")
    if configuration.get("license_at_pin") != "absent":
        raise ValueError("DeepSWE license-at-pin boundary is unresolved")
    if configuration.get("cache_path") != ".cache/deepswe":
        raise ValueError("DeepSWE cache must remain under .cache/deepswe")
    if configuration.get("schema_version") != "1.1":
        raise ValueError("DeepSWE task schema pin must remain 1.1")
    platform = str(configuration.get("platform", ""))
    if platform != "linux/amd64":
        raise ValueError("DeepSWE task platform pin must remain linux/amd64")
    _require_exact_commit(str(source.get("commit", "")))
    return versions, source, normalized, platform


def deepswe_materialization_plan(root: Path) -> DeepSWEMaterializationPlan:
    """Return the exact manual DeepSWE network/build scope without writing files."""

    root = root.resolve()
    _, source, tasks, platform = _deepswe_configuration(root)
    return DeepSWEMaterializationPlan(
        source_url=str(source["url"]),
        commit=str(source["commit"]),
        task_ids=tuple(task["id"] for task in tasks),
        original_images=tuple(task["image"] for task in tasks),
        original_image_digests=tuple(task["digest"] for task in tasks),
        platform=platform,
        cache_path=root / ".cache" / "deepswe",
    )


def format_deepswe_plan(plan: DeepSWEMaterializationPlan) -> str:
    lines = [
        "DeepSWE manual capability materialization",
        f"Source: {plan.source_url}",
        f"Commit: {plan.commit}",
        f"Platform: {plan.platform}",
        "Network: fetch only the six pinned task directories, then pull their six "
        "published v1.1 images by manifest digest.",
        "Build: build or reuse one platform-matched agent-tools image, then extend "
        "each original image with the pinned Claude and Codex CLI payloads.",
        f"Ignored cache only: {plan.cache_path}",
        "Tasks:",
    ]
    lines.extend(
        f"  {task_id}: {image}@{digest}"
        for task_id, image, digest in zip(
            plan.task_ids,
            plan.original_images,
            plan.original_image_digests,
            strict=True,
        )
    )
    lines.extend(
        (
            "Fetched tasks and generated wrappers remain local and are not publishable.",
            "No model session or benchmark trial will start.",
        )
    )
    return "\n".join(lines)


def _require_ignored_deepswe_cache(root: Path, cache: Path) -> None:
    try:
        relative = cache.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("DeepSWE cache must stay inside the repository .cache") from error
    if relative.as_posix() != ".cache/deepswe":
        raise ValueError("DeepSWE cache must stay at .cache/deepswe")
    try:
        _run_git(
            ("check-ignore", "--quiet", "--no-index", "--", relative.as_posix()),
            cwd=root,
        )
    except subprocess.CalledProcessError as error:
        raise ValueError("DeepSWE cache must be ignored before materialization") from error
    tracked = _run_git(("ls-files", "--", relative.as_posix()), cwd=root)
    if tracked.stdout.strip():
        raise ValueError("DeepSWE cache contains tracked, publishable content")


def _git_object_exists(repository: Path, object_name: str) -> bool:
    result = subprocess.run(
        ("git", "cat-file", "-e", object_name),
        cwd=repository,
        env=_git_environment(),
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _deepswe_manifest_digest(document: dict[str, object], field: str) -> str:
    unsigned = dict(document)
    unsigned.pop(field, None)
    return _sha256_bytes(_canonical_json(unsigned))


def _validate_deepswe_source_cache(
    tree: Path,
    manifest_path: Path,
    commit: str,
    task_ids: tuple[str, ...],
) -> dict[str, object]:
    manifest = _read_json(manifest_path, "DeepSWE source manifest")
    recorded_digest = str(manifest.get("manifest_digest", ""))
    if (
        manifest.get("commit") != commit
        or manifest.get("task_ids") != list(task_ids)
        or recorded_digest != _deepswe_manifest_digest(manifest, "manifest_digest")
        or manifest.get("file_digests") != _file_digests(tree)
        or manifest.get("byte_tree_digest") != _byte_tree_digest(tree)
        or manifest.get("tree_digest") != _tree_digest(tree)
    ):
        raise ValueError("DeepSWE source cache does not match its byte manifest")
    return manifest


def _archive_deepswe_tasks(
    root: Path,
    source: str | Path,
    commit: str,
    task_ids: tuple[str, ...],
) -> tuple[Path, dict[str, object]]:
    repository = _local_repository(source)
    if repository is not None:
        _validate_local_repository(repository, commit)
        git_directory = repository
    else:
        git_directory = root / ".cache" / "deepswe" / "source-repository.git"
        if not git_directory.is_dir():
            git_directory.parent.mkdir(parents=True, exist_ok=True)
            _run_git(("init", "--bare", str(git_directory)))
            _run_git(("remote", "add", "origin", str(source)), cwd=git_directory)
        else:
            remote = (
                _run_git(("remote", "get-url", "origin"), cwd=git_directory)
                .stdout.decode()
                .strip()
            )
            if remote != str(source):
                raise ValueError("DeepSWE source cache remote does not match the pin")
        if not _git_object_exists(git_directory, f"{commit}^{{commit}}"):
            try:
                _run_git(
                    (
                        "-c",
                        "protocol.version=2",
                        "fetch",
                        "--depth",
                        "1",
                        "--filter=blob:none",
                        "origin",
                        commit,
                    ),
                    cwd=git_directory,
                )
            except subprocess.CalledProcessError as error:
                raise ValueError(
                    f"DeepSWE source does not contain pinned commit {commit}"
                ) from error

    if not _git_object_exists(git_directory, f"{commit}^{{commit}}"):
        raise ValueError(f"DeepSWE source does not contain pinned commit {commit}")
    if _git_object_exists(git_directory, f"{commit}:LICENSE"):
        raise ValueError("DeepSWE pinned license boundary changed; review before fetching")
    for task_id in task_ids:
        if not _git_object_exists(
            git_directory, f"{commit}:tasks/{task_id}/task.toml"
        ):
            raise ValueError(f"DeepSWE pinned task is missing: {task_id}")

    cache = root / ".cache" / "deepswe"
    destination = cache / "source-trees" / commit
    manifest_path = cache / "source-manifests" / f"{commit}.json"
    if destination.is_dir():
        return destination, _validate_deepswe_source_cache(
            destination, manifest_path, commit, task_ids
        )
    if destination.exists() or manifest_path.exists():
        raise ValueError("DeepSWE source cache is incomplete")

    paths = tuple(f"tasks/{task_id}" for task_id in task_ids)
    try:
        archive = _run_git(
            ("archive", "--format=tar", commit, "--", *paths), cwd=git_directory
        ).stdout
    except subprocess.CalledProcessError as error:
        raise ValueError("could not archive the pinned DeepSWE cohort") from error
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary_directory:
        extracted = Path(temporary_directory) / "tree"
        extracted.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as archive_file:
            archive_file.extractall(extracted, filter="data")
        actual_tasks = {
            path.name for path in (extracted / "tasks").iterdir() if path.is_dir()
        }
        if actual_tasks != set(task_ids):
            raise ValueError("DeepSWE archive escaped the six-task allowlist")
        extracted.rename(destination)
    _make_read_only(destination)
    manifest: dict[str, object] = {
        "schema_version": "1",
        "commit": commit,
        "task_ids": list(task_ids),
        "file_digests": _file_digests(destination),
        "byte_tree_digest": _byte_tree_digest(destination),
        "tree_digest": _tree_digest(destination),
    }
    manifest["manifest_digest"] = _deepswe_manifest_digest(
        manifest, "manifest_digest"
    )
    _write_json(manifest_path, manifest)
    manifest_path.chmod(0o444)
    return destination, manifest


def _inspect_image_document(image: str) -> dict[str, object]:
    completed = subprocess.run(
        ("docker", "image", "inspect", image),
        check=True,
        capture_output=True,
        text=True,
    )
    document = json.loads(completed.stdout)
    if not isinstance(document, list) or len(document) != 1 or not isinstance(
        document[0], dict
    ):
        raise ValueError(f"Docker returned invalid image metadata for {image}")
    return document[0]


def _inspect_image_id(image: str) -> str | None:
    completed = subprocess.run(
        ("docker", "image", "inspect", "--format", "{{.Id}}", image),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        return None
    value = completed.stdout.strip()
    return value if re.fullmatch(r"sha256:[0-9a-f]{64}", value) else None


def _image_platform(document: dict[str, object], image: str) -> str:
    operating_system = document.get("Os")
    architecture = document.get("Architecture")
    platform = f"{operating_system}/{architecture}"
    if not _SAFE_PLATFORM.fullmatch(platform):
        raise ValueError(f"Docker returned an invalid platform for {image}")
    return platform


def _platform_agent_tools_image(root: Path, platform: str) -> str:
    reference = _platform_image_reference(root, "node", platform)
    expected_input = image_input_digest(root, "node")
    image_id = _inspect_image_id(reference)
    if image_id is not None:
        document = _inspect_image_document(reference)
        configuration = document.get("Config")
        labels = configuration.get("Labels") if isinstance(configuration, dict) else None
        if (
            isinstance(labels, dict)
            and labels.get(_IMAGE_INPUT_LABEL) == expected_input
            and _image_platform(document, reference) == platform
        ):
            return reference

    subprocess.run(
        _platform_agent_tools_build_arguments(root, platform),
        cwd=root,
        check=True,
    )
    document = _inspect_image_document(reference)
    configuration = document.get("Config")
    labels = configuration.get("Labels") if isinstance(configuration, dict) else None
    if (
        not isinstance(labels, dict)
        or labels.get(_IMAGE_INPUT_LABEL) != expected_input
        or _image_platform(document, reference) != platform
    ):
        raise ValueError("platform-matched node agent-tools image is stale or invalid")
    return reference


def _tar_byte_manifest(archive: bytes) -> tuple[dict[str, str], str]:
    files: dict[str, str] = {}
    records: list[dict[str, object]] = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as archive_file:
        for member in sorted(archive_file.getmembers(), key=lambda item: item.name):
            if member.isfile():
                extracted = archive_file.extractfile(member)
                if extracted is None:
                    raise ValueError(f"could not read archived file {member.name}")
                payload = extracted.read()
            elif member.issym():
                payload = f"symlink:{member.linkname}".encode()
            else:
                continue
            digest = _sha256_bytes(payload)
            files[member.name] = digest
            records.append({"path": member.name, "mode": member.mode, "sha256": digest})
    return files, _sha256_bytes(_canonical_json(records))


def _image_repository_snapshot(
    image: str, expected_commit: str, platform: str
) -> tuple[dict[str, str], str]:
    script = (
        'set -euo pipefail; test -z "$(git -C /app status --porcelain)"; '
        'printf "commit=%s\\n" "$(git -C /app rev-parse HEAD)"; '
        "git -C /app archive --format=tar HEAD"
    )
    completed = subprocess.run(
        (
            "docker",
            "run",
            "--rm",
            "--platform",
            platform,
            "--network",
            "none",
            "--entrypoint",
            "/bin/bash",
            image,
            "-lc",
            script,
        ),
        check=True,
        capture_output=True,
    )
    header, separator, archive = completed.stdout.partition(b"\n")
    if separator != b"\n" or header != f"commit={expected_commit}".encode():
        raise ValueError(f"image {image} does not contain the expected starting commit")
    return _tar_byte_manifest(archive)


def deepswe_derived_dockerfile(
    root: Path,
    original_image: str,
    agent_tools_image: str,
    *,
    original_user: str = "",
) -> str:
    """Render the minimal image layer that adds pinned CLIs outside /app."""

    packages = _package_versions(load_versions(root / "Versions.toml"))
    for name in ("@anthropic-ai/claude-code", "@openai/codex"):
        if name not in packages:
            raise ValueError(f"Versions.toml has no package pin for {name}")
    if original_user and not _SAFE_IMAGE_USER.fullmatch(original_user):
        raise ValueError(f"unsafe original DeepSWE image user: {original_user}")
    for reference in (original_image, agent_tools_image):
        if any(character in reference for character in "\r\n"):
            raise ValueError("unsafe DeepSWE image reference")
    lines = [
        f"FROM {agent_tools_image} AS agent-tools",
        f"FROM {original_image}",
        "USER 0",
        "COPY --from=agent-tools "
        "/usr/local/lib/node_modules/@anthropic-ai/claude-code "
        "/usr/local/lib/node_modules/@anthropic-ai/claude-code",
        "COPY --from=agent-tools /usr/local/lib/node_modules/@openai/codex "
        "/usr/local/lib/node_modules/@openai/codex",
        "RUN ln -sf ../lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe "
        "/usr/local/bin/claude \\",
        "    && ln -sf ../lib/node_modules/@openai/codex/bin/codex.js "
        "/usr/local/bin/codex \\",
        "    && claude --version \\",
        "    && codex --version \\",
        '    && test -z "$(git -C /app status --porcelain)"',
    ]
    if original_user:
        lines.append(f"USER {original_user}")
    return "\n".join(lines) + "\n"


def deepswe_pinned_verifier_dockerfile(
    original: str, original_image_reference: str
) -> str:
    """Pin the generated verifier build while leaving upstream test bytes untouched."""

    if any(character in original_image_reference for character in "\r\n"):
        raise ValueError("unsafe DeepSWE verifier image reference")
    pattern = r"^FROM[ \t]+\S+[ \t]*$"
    if len(re.findall(pattern, original, flags=re.MULTILINE)) != 1:
        raise ValueError("DeepSWE verifier Dockerfile requires one base image")
    pinned = re.sub(
        pattern,
        f"FROM {original_image_reference}",
        original,
        count=1,
        flags=re.MULTILINE,
    )
    return pinned


def _materialize_deepswe_image(
    root: Path,
    task_id: str,
    original_image: str,
    original_manifest_digest: str,
    platform: str,
    base_commit: str,
    dockerfile_path: Path,
    verifier_context: Path,
    verifier_dockerfile_path: Path,
) -> DeepSWEImageProvenance:
    image_errors = dockerfile_policy_errors(root)
    if image_errors:
        raise ValueError("image policy validation failed: " + "; ".join(image_errors))
    original_reference = f"{original_image}@{original_manifest_digest}"
    subprocess.run(
        ("docker", "pull", "--platform", platform, original_reference),
        check=True,
    )
    original_document = _inspect_image_document(original_reference)
    original_digest = str(original_document.get("Id", ""))
    repo_digests = original_document.get("RepoDigests")
    immutable_references = (
        [str(reference) for reference in repo_digests]
        if isinstance(repo_digests, list)
        else []
    )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", original_digest):
        raise ValueError(f"original DeepSWE image has no content digest: {original_image}")
    if (
        _image_platform(original_document, original_reference) != platform
        or not any(
            reference.endswith(f"@{original_manifest_digest}")
            for reference in immutable_references
        )
    ):
        raise ValueError(
            f"original DeepSWE image does not match its platform pin: {original_image}"
        )
    configuration = original_document.get("Config")
    configured_user = configuration.get("User") if isinstance(configuration, dict) else ""
    original_user = configured_user if isinstance(configured_user, str) else ""
    starting_files, starting_digest = _image_repository_snapshot(
        original_reference, base_commit, platform
    )

    agent_tools_image = _platform_agent_tools_image(root, platform)
    agent_tools_digest = _inspect_image_id(agent_tools_image)
    if agent_tools_digest is None:
        raise ValueError("pinned node agent-tools image is missing")
    dockerfile = deepswe_derived_dockerfile(
        root,
        original_reference,
        agent_tools_image,
        original_user=original_user,
    )
    dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    dockerfile_path.write_text(dockerfile)
    input_digest = _sha256_bytes(
        _canonical_json(
            {
                "task_id": task_id,
                "platform": platform,
                "original_manifest_digest": original_manifest_digest,
                "original_image_digest": original_digest,
                "agent_tools_image_digest": agent_tools_digest,
                "dockerfile_digest": _sha256_bytes(dockerfile.encode()),
            }
        )
    )
    derived_image = (
        f"studio-moser/harness-testing-deepswe-{task_id}:"
        f"{input_digest.removeprefix('sha256:')[:16]}"
    )
    subprocess.run(
        (
            "docker",
            "buildx",
            "build",
            "--load",
            "--platform",
            platform,
            "--label",
            f"{_DEEPSWE_IMAGE_LABEL}={input_digest}",
            "--file",
            str(dockerfile_path),
            "--tag",
            derived_image,
            str(dockerfile_path.parent),
        ),
        cwd=root,
        check=True,
    )
    derived_document = _inspect_image_document(derived_image)
    derived_digest = str(derived_document.get("Id", ""))
    if (
        not _SHA256_DIGEST.fullmatch(derived_digest)
        or _image_platform(derived_document, derived_image) != platform
    ):
        raise ValueError(f"derived DeepSWE image was not created: {task_id}")
    derived_files, derived_repository_digest = _image_repository_snapshot(
        derived_image, base_commit, platform
    )
    if (
        derived_files != starting_files
        or derived_repository_digest != starting_digest
    ):
        raise ValueError(f"derived DeepSWE image changed /app: {task_id}")

    verifier_dockerfile = deepswe_pinned_verifier_dockerfile(
        (verifier_context / "Dockerfile").read_text(),
        original_reference,
    )
    verifier_dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    verifier_dockerfile_path.write_text(verifier_dockerfile)
    verifier_input_digest = _sha256_bytes(
        _canonical_json(
            {
                "task_id": task_id,
                "platform": platform,
                "original_manifest_digest": original_manifest_digest,
                "verifier_tree_digest": _tree_digest(verifier_context),
                "dockerfile_digest": _sha256_bytes(verifier_dockerfile.encode()),
            }
        )
    )
    verifier_image = (
        f"studio-moser/harness-testing-deepswe-{task_id}-verifier:"
        f"{verifier_input_digest.removeprefix('sha256:')[:16]}"
    )
    subprocess.run(
        (
            "docker",
            "buildx",
            "build",
            "--load",
            "--platform",
            platform,
            "--label",
            f"{_DEEPSWE_IMAGE_LABEL}={verifier_input_digest}",
            "--file",
            str(verifier_dockerfile_path),
            "--tag",
            verifier_image,
            str(verifier_context),
        ),
        cwd=root,
        check=True,
    )
    verifier_document = _inspect_image_document(verifier_image)
    verifier_digest = str(verifier_document.get("Id", ""))
    if (
        not _SHA256_DIGEST.fullmatch(verifier_digest)
        or _image_platform(verifier_document, verifier_image) != platform
    ):
        raise ValueError(f"derived DeepSWE verifier image was not created: {task_id}")
    return DeepSWEImageProvenance(
        original_image=original_image,
        original_image_reference=original_reference,
        original_manifest_digest=original_manifest_digest,
        original_image_digest=original_digest,
        derived_image=derived_image,
        derived_image_digest=derived_digest,
        verifier_image=verifier_image,
        verifier_image_digest=verifier_digest,
        platform=platform,
        starting_repository_commit=base_commit,
        starting_repository_digest=starting_digest,
        starting_repository_files=starting_files,
        agent_tools_image_digest=agent_tools_digest,
    )


def _task_manifest(task_root: Path, paths: Iterable[Path]) -> dict[str, str]:
    return {
        path.relative_to(task_root).as_posix(): _sha256_bytes(_path_payload(path))
        for path in sorted(paths)
        if path.is_file() or path.is_symlink()
    }


def _deepswe_byte_manifests(
    task_root: Path, image: DeepSWEImageProvenance
) -> dict[str, object]:
    metadata_paths = [task_root / "task.toml", task_root / "pre_artifacts.sh"]
    metadata_paths.extend((task_root / "environment").rglob("*"))
    return {
        "instruction": _task_manifest(task_root, (task_root / "instruction.md",)),
        "metadata": _task_manifest(task_root, metadata_paths),
        "solution": _task_manifest(task_root, (task_root / "solution").rglob("*")),
        "starting_repository": {
            "commit": image.starting_repository_commit,
            "digest": image.starting_repository_digest,
            "files": image.starting_repository_files,
        },
        "verifier": _task_manifest(task_root, (task_root / "tests").rglob("*")),
    }


def _task_configuration(task_root: Path) -> dict[str, object]:
    try:
        with (task_root / "task.toml").open("rb") as task_file:
            document = tomllib.load(task_file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"invalid pinned DeepSWE task metadata: {task_root.name}") from error
    return document


def _replace_task_images(
    task_path: Path, derived_image: str, verifier_image: str
) -> None:
    text = task_path.read_text()
    replacement = f'docker_image = "{derived_image}"'
    updated, count = re.subn(
        r'^docker_image\s*=\s*"[^"]+"\s*$',
        replacement,
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError(f"DeepSWE task has no single docker_image field: {task_path}")
    updated, verifier_count = re.subn(
        r"^(\[verifier\.environment\][ \t]*\r?\n)",
        rf'\1docker_image = "{verifier_image}"\n',
        updated,
        count=1,
        flags=re.MULTILINE,
    )
    if verifier_count != 1:
        raise ValueError(
            f"DeepSWE task has no separate verifier environment: {task_path}"
        )
    configuration = tomllib.loads(updated)
    if (
        configuration.get("environment", {}).get("docker_image") != derived_image
        or configuration.get("verifier", {})
        .get("environment", {})
        .get("docker_image")
        != verifier_image
    ):
        raise ValueError(f"DeepSWE task image wrapper is invalid: {task_path}")
    task_path.chmod(stat.S_IMODE(task_path.stat().st_mode) | stat.S_IWUSR)
    task_path.write_text(updated)


def _validate_materialized_deepswe(
    root: Path,
    path: Path,
    digest: str,
    source_manifest: dict[str, object],
) -> MaterializedDeepSWE:
    provenance = _read_json(path / "Provenance.json", "DeepSWE provenance")
    versions, source, tasks, platform = _deepswe_configuration(root)
    packages = _package_versions(versions)
    expected_packages = {
        name: packages[name]
        for name in ("@anthropic-ai/claude-code", "@openai/codex")
    }
    expected_source_digest = str(source_manifest["manifest_digest"])
    expected_source = {
        "name": "DeepSWE",
        "url": str(source["url"]),
        "version": str(source["version"]),
        "commit": str(source["commit"]),
    }
    if (
        path.name != digest.removeprefix("sha256:")
        or provenance.get("dataset_digest") != digest
        or digest != _deepswe_manifest_digest(provenance, "dataset_digest")
        or provenance.get("schema_version") != "1"
        or provenance.get("materializer_schema") != _schema_version(root)
        or provenance.get("source") != expected_source
        or provenance.get("source_manifest_digest") != expected_source_digest
        or provenance.get("task_ids") != [task["id"] for task in tasks]
        or provenance.get("platform") != platform
        or provenance.get("redistribution") != "forbidden"
        or provenance.get("license_at_pin") != "absent"
        or provenance.get("cli_packages") != expected_packages
        or provenance.get("generated_file_digests") != _file_digests(path)
    ):
        raise ValueError("materialized DeepSWE dataset does not match current provenance")
    task_records = provenance.get("tasks")
    if not isinstance(task_records, list) or len(task_records) != len(tasks):
        raise ValueError("materialized DeepSWE task provenance is incomplete")
    if [record.get("task_id") for record in task_records if isinstance(record, dict)] != [
        task["id"] for task in tasks
    ]:
        raise ValueError("materialized DeepSWE task provenance is invalid")
    source_tree = (
        root
        / ".cache"
        / "deepswe"
        / "source-trees"
        / str(source["commit"])
        / "tasks"
    )
    for record, task_pin in zip(task_records, tasks, strict=True):
        if not isinstance(record, dict):
            raise ValueError("materialized DeepSWE task provenance is invalid")
        task_id = str(record.get("task_id", ""))
        wrapper = path / "tasks" / task_id
        original_task = source_tree / task_id
        original_reference = f"{task_pin['image']}@{task_pin['digest']}"
        derived_directory = path / "Derived" / task_id
        if (
            task_id not in DEEPSWE_TASK_IDS
            or record.get("original_task_digest")
            != _byte_tree_digest(original_task)
            or record.get("wrapper_digest") != _tree_digest(wrapper)
            or record.get("original_image") != task_pin["image"]
            or record.get("original_manifest_digest") != task_pin["digest"]
            or record.get("original_image_reference") != original_reference
            or record.get("platform") != platform
            or record.get("derived_dockerfile_digest")
            != _sha256_bytes((derived_directory / "Dockerfile").read_bytes())
            or record.get("verifier_dockerfile_digest")
            != _sha256_bytes(
                (derived_directory / "Verifier.Dockerfile").read_bytes()
            )
            or _inspect_image_id(original_reference)
            != record.get("original_image_digest")
            or _inspect_image_id(str(record.get("derived_image", "")))
            != record.get("derived_image_digest")
            or _inspect_image_id(str(record.get("verifier_image", "")))
            != record.get("verifier_image_digest")
        ):
            raise ValueError(f"materialized DeepSWE task is stale or invalid: {task_id}")
    return MaterializedDeepSWE(path=path, digest=digest)


def load_deepswe_dataset(root: Path) -> MaterializedDeepSWE:
    """Load the current ignored DeepSWE dataset and fail closed on drift."""

    root = root.resolve()
    plan = deepswe_materialization_plan(root)
    _require_ignored_deepswe_cache(root, plan.cache_path)
    current = _read_json(plan.cache_path / "Current.json", "DeepSWE current pointer")
    digest = str(current.get("dataset_digest", ""))
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("DeepSWE dataset is not materialized")
    source_manifest_path = (
        plan.cache_path / "source-manifests" / f"{plan.commit}.json"
    )
    source_tree = plan.cache_path / "source-trees" / plan.commit
    source_manifest = _validate_deepswe_source_cache(
        source_tree, source_manifest_path, plan.commit, plan.task_ids
    )
    path = plan.cache_path / "datasets" / digest.removeprefix("sha256:")
    if not path.is_dir():
        raise ValueError("DeepSWE current dataset cache is missing")
    return _validate_materialized_deepswe(
        root, path, digest, source_manifest
    )


def _current_deepswe_is_compatible(
    root: Path,
    plan: DeepSWEMaterializationPlan,
    source_manifest: dict[str, object],
) -> bool:
    current_path = plan.cache_path / "Current.json"
    if not current_path.is_file():
        return False
    current = _read_json(current_path, "DeepSWE current pointer")
    digest = str(current.get("dataset_digest", ""))
    path = plan.cache_path / "datasets" / digest.removeprefix("sha256:")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or not path.is_dir():
        return False
    provenance = _read_json(path / "Provenance.json", "DeepSWE provenance")
    versions = load_versions(root / "Versions.toml")
    packages = _package_versions(versions)
    return (
        provenance.get("materializer_schema") == _schema_version(root)
        and provenance.get("source_manifest_digest")
        == source_manifest.get("manifest_digest")
        and provenance.get("task_ids") == list(plan.task_ids)
        and provenance.get("platform") == plan.platform
        and provenance.get("cli_packages")
        == {
            name: packages[name]
            for name in ("@anthropic-ai/claude-code", "@openai/codex")
        }
    )


def materialize_deepswe(
    root: Path,
    *,
    confirm_download: bool,
    source_override: tuple[str | Path, str] | None = None,
) -> MaterializedDeepSWE:
    """Fetch and derive the manual six-task capability lane without a model run."""

    root = root.resolve()
    plan = deepswe_materialization_plan(root)
    if not confirm_download:
        raise ValueError("DeepSWE materialization requires explicit --confirm-download")
    _require_ignored_deepswe_cache(root, plan.cache_path)
    if source_override is None:
        source: str | Path = plan.source_url
        commit = plan.commit
    else:
        source, commit = source_override
        if commit != plan.commit:
            raise ValueError("source override commit does not match the DeepSWE pin")
    plan.cache_path.mkdir(parents=True, exist_ok=True)
    source_tree, source_manifest = _archive_deepswe_tasks(
        root, source, commit, plan.task_ids
    )
    if _current_deepswe_is_compatible(root, plan, source_manifest):
        return load_deepswe_dataset(root)

    versions, source_pin, task_pins, platform = _deepswe_configuration(root)
    packages = _package_versions(versions)
    with tempfile.TemporaryDirectory(dir=plan.cache_path) as temporary_directory:
        dataset = Path(temporary_directory) / "dataset"
        tasks_directory = dataset / "tasks"
        derived_directory = dataset / "Derived"
        tasks_directory.mkdir(parents=True)
        records: list[dict[str, object]] = []
        for task_pin in task_pins:
            task_id = task_pin["id"]
            original_task = source_tree / "tasks" / task_id
            wrapper = tasks_directory / task_id
            _copy_tree(original_task, wrapper)
            configuration = _task_configuration(original_task)
            task = configuration.get("task")
            metadata = configuration.get("metadata")
            environment = configuration.get("environment")
            if (
                configuration.get("schema_version") != "1.1"
                or not isinstance(task, dict)
                or task.get("name") != f"datacurve/{task_id}"
                or not isinstance(metadata, dict)
                or metadata.get("task_id") != task_id
                or not isinstance(environment, dict)
                or environment.get("docker_image") != task_pin["image"]
            ):
                raise ValueError(f"DeepSWE task metadata changed upstream: {task_id}")
            base_commit = str(metadata.get("base_commit_hash", ""))
            _require_exact_commit(base_commit)
            dockerfile_path = derived_directory / task_id / "Dockerfile"
            verifier_dockerfile_path = (
                derived_directory / task_id / "Verifier.Dockerfile"
            )
            image = _materialize_deepswe_image(
                root,
                task_id,
                task_pin["image"],
                task_pin["digest"],
                platform,
                base_commit,
                dockerfile_path,
                original_task / "tests",
                verifier_dockerfile_path,
            )
            _replace_task_images(
                wrapper / "task.toml",
                image.derived_image,
                image.verifier_image,
            )
            _make_read_only(wrapper)
            record: dict[str, object] = {
                "task_id": task_id,
                "original_task_digest": _byte_tree_digest(original_task),
                "wrapper_digest": _tree_digest(wrapper),
                "original_image": image.original_image,
                "original_image_reference": image.original_image_reference,
                "original_manifest_digest": image.original_manifest_digest,
                "original_image_digest": image.original_image_digest,
                "derived_image": image.derived_image,
                "derived_image_digest": image.derived_image_digest,
                "verifier_image": image.verifier_image,
                "verifier_image_digest": image.verifier_image_digest,
                "platform": image.platform,
                "derived_dockerfile_digest": _sha256_bytes(
                    dockerfile_path.read_bytes()
                ),
                "verifier_dockerfile_digest": _sha256_bytes(
                    verifier_dockerfile_path.read_bytes()
                ),
                "agent_tools_image_digest": image.agent_tools_image_digest,
                "byte_manifests": _deepswe_byte_manifests(original_task, image),
            }
            records.append(record)
        provenance: dict[str, object] = {
            "schema_version": "1",
            "materializer_schema": _schema_version(root),
            "source": {
                "name": "DeepSWE",
                "url": str(source_pin["url"]),
                "version": str(source_pin["version"]),
                "commit": commit,
            },
            "source_manifest_digest": source_manifest["manifest_digest"],
            "task_ids": list(plan.task_ids),
            "platform": platform,
            "redistribution": "forbidden",
            "license_at_pin": "absent",
            "cli_packages": {
                name: packages[name]
                for name in ("@anthropic-ai/claude-code", "@openai/codex")
            },
            "tasks": records,
            "generated_file_digests": _file_digests(dataset),
        }
        digest = _deepswe_manifest_digest(provenance, "dataset_digest")
        provenance["dataset_digest"] = digest
        _write_json(dataset / "Provenance.json", provenance)
        destination = plan.cache_path / "datasets" / digest.removeprefix("sha256:")
        if destination.exists():
            _validate_materialized_deepswe(
                root, destination, digest, source_manifest
            )
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_tree(dataset, destination)
            _make_read_only(destination)
    _write_json(plan.cache_path / "Current.json", {"dataset_digest": digest})
    return _validate_materialized_deepswe(
        root, destination, digest, source_manifest
    )
