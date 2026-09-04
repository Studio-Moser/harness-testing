# Capability Pack

The optional capability pack measures longer-horizon work on six frozen DeepSWE v1.1
tasks. It is a manual `research` lane, not part of validation, checkpoints, releases, or
continuous integration.

## Frozen Source

- Repository: [datacurve-ai/deep-swe](https://github.com/datacurve-ai/deep-swe)
- Commit: `8cae5984d5dd0ee37445beff0e928dc10c331116`
- Upstream format: Harbor task schema 1.1 with separate verifier environments
- Local policy: fetched task content and generated wrappers are never redistributed

The pinned tree has no license file. GitHub's current repository metadata and a license
added after this commit do not grant this project permission to republish the pinned
files. Materialization therefore fails unless `.cache/deepswe` is ignored and untracked.

| Language | Band | Task |
| --- | --- | --- |
| TypeScript | Easier | `happy-dom-abort-pending-body-reads` |
| TypeScript | Harder | `quill-shared-toolbar-focus` |
| JavaScript | Easier | `yjs-map-conflict-detection` |
| JavaScript | Harder | `katex-multicolumn-array-spans` |
| Rust | Easier | `wasmi-trap-coredumps` |
| Rust | Harder | `pest-character-class-coalescing` |

## Materialize Manually

Preview the exact network, image, task, and cache scope:

```bash
uv run harness-test deepswe materialize
```

The preview writes nothing. Execute it only with explicit confirmation:

```bash
uv run harness-test deepswe materialize --confirm-download
```

Materialization does not start Claude, Codex, Harbor, or a benchmark trial. It:

1. fetches the exact Git commit with blob filtering and archives only the six allowlisted
   task directories;
2. records sorted SHA-256 manifests for each instruction, solution, verifier, metadata
   set, and starting repository;
3. pulls each task's upstream `linux/amd64` image by its pinned manifest digest and
   records both that manifest digest and the local image ID;
4. builds or reuses a separately tagged `linux/amd64` agent-tools image from the pinned
   Harness Testing Node Dockerfile, then copies its Claude Code and Codex CLI payloads
   into each derived image outside `/app`;
5. builds a separate hidden-test image from the unchanged upstream verifier files while
   pinning its generated `FROM` line to the same immutable manifest;
6. confirms the original and agent images have the same clean `/app` commit and byte
   manifest; and
7. changes only the agent and verifier `docker_image` pointers in a cached task wrapper,
   recording original-task, wrapper, original-image, agent-image, and verifier-image
   digests separately.

DeepSWE documents its task Dockerfiles as fallbacks for unavailable prebuilt images. The
pinned Dockerfiles begin from mutable `mars-base:latest`, so this materializer uses the
published v1.1 task images rather than rebuilding a less reproducible starting state.
The separate agent-tools tag prevents an Apple Silicon host's normal `linux/arm64` image
from being copied into these x86 task images.

Generated content stays under:

```text
.cache/deepswe/
  source-repository.git/
  source-trees/<commit>/
  source-manifests/<commit>.json
  datasets/<dataset-digest>/
  Current.json
```

Reusing a cache validates every recorded byte, wrapper digest, current CLI pin, and local
derived-image ID. Drift is an error; the materializer never silently repairs or publishes
a changed cache.

## Plan a Research Run

After materialization, only `--profile research` resolves these cached tasks. A run still
uses the normal explicit cell, session, budget, manifest-digest, and approval gates:

```bash
uv run harness-test run plan \
  --profile research \
  --billing-mode subscription \
  --cell codex:A2:candidate:<HARNESS_COMMIT> \
  --task happy-dom-abort-pending-body-reads \
  --max-sessions 1 \
  --max-budget-usd 0
```

Ordinary profiles cannot resolve the cached dataset. The `run plan` command still starts
no model session; `run execute` requires the exact newly approved manifest digest.
