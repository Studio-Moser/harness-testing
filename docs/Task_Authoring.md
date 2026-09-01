# Task Authoring

## Authoring goal

Each task should isolate one behavior that can distinguish harness quality without depending on a live repository, mutable service, or subjective grader. Prefer the smallest frozen project that makes the desired behavior real: one React component, one static page, one Rust crate, or one local Harness contract.

Add workflow tasks under `tasks/workflow/` and Harness surface-contract tasks under `tasks/contract/`. Do not add a stack merely for breadth; add it only when it exercises a behavior the existing projects cannot.

## Required shape

Start from the nearest existing task and keep its structure:

```text
task-id/
  instruction.md
  task.toml
  environment/
  solution/solve.sh
  tests/
    Dockerfile
    Protected_Files.json
    QA.json
    QA/
    Verifier/
    criteria.py
    test.sh
    reward/
    workflow/
    efficiency/
```

Contract tasks also carry protected expected calls/results, exact evidence-prefix requirements, and a deterministic local sidecar scenario. `harness-stub describe` exposes the universal result schema and task-specific public actions, including required payload fields, but never protected answers, responses, or expected results. Every required field must be protected-matched or listed in the call's protected `shape_only` array; use `shape_only` only for caller-authored prose. Required values must match the protected JSON type and nonempty shape, and protected lists compare as unordered sets. Mark only contiguous independent calls with the same protected `unordered_group`. Invalid calls are recorded without consuming the next required workflow step. Rust tasks use the frozen crate and lockfile instead of the Node verifier subset.

The task configuration must preserve these boundaries:

- The project and separate verifier have no network.
- The agent uses an empty task-level allowlist; the run layer adds only the selected provider host.
- `/app` and `/logs/agent/trajectory.json` are explicit artifacts.
- The workspace artifact excludes `.git`, `node_modules`, and `target`.
- Toolchains, packages, base images, and upstream inputs are immutable and recorded in `Versions.toml`.
- The environment contains no symlinks, credentials, personal paths, private data, or live repository content.

Record the byte digest of the complete `environment/` tree in `metadata.fixture_digest`. Protect every source file that the instruction does not authorize changing in `tests/Protected_Files.json`; list intended mutable files separately with their baseline hashes. Static validation fails if either boundary drifts.

## Three independent criteria

Every task supplies one or more deterministic RewardKit criteria in exactly these directories:

- `reward/`: correctness of final behavior and protected state.
- `workflow/`: task-specific sequence requirements that are necessary to satisfy the instruction.
- `efficiency/`: absolute policy violations such as a premature comprehensive suite or duplicate successful command.

Do not reward plans, reviews, tool calls, or verbosity by themselves. Do not lower correctness because required workflow calls were omitted or a correct solution was inefficient; keep the dimensions separate. Correctness compares the semantic attempt multiset and requires each protected semantic evidence prefix to begin a distinct nonblank check; optional prose may follow the prefix. Missing required calls affect workflow, while invalid, duplicate, or extra calls affect efficiency. The verifier must use preinstalled dependencies and must never download packages at runtime.

## Five model-free QA cases

`tests/QA.json` defines exactly these cases:

| Case | Proof |
| --- | --- |
| `oracle` | The minimum reference implementation passes all intended dimensions. |
| `nop` | An unchanged project cannot receive correctness or workflow credit. |
| `near-miss` | A plausible incomplete implementation fails the criterion it misses. |
| `adversarial` | Fabricated evidence cannot pass the dimension it targets; a correct final artifact without required calls may pass correctness while failing workflow. |
| `source-tamper` | Editing protected source is detected even when visible behavior appears correct. |

The local `ScriptAgent` applies each frozen mutation and emits the declared command evidence; it never calls a model. Expected scores in `QA.json` are part of the task contract. A task is not eligible for a model-backed run until all five cases pass.

## Surgical authoring cadence

While changing one task, run static validation plus only its oracle and no-op:

```bash
uv run harness-test validate --static-only
uv run harness-test task qa --task TASK_ID --case oracle
uv run harness-test task qa --task TASK_ID --case nop
```

At the checkpoint, run the full deterministic gates once, including the pack’s five-case gate:

```bash
uv run harness-test task qa --pack workflow --all-cases
# or
uv run harness-test task qa --pack contract --all-cases
```

Do not run the pack between task edits. If only a criterion or classifier changes after a recorded model run, regrade the retained workspace and trajectory instead of starting another agent session.

## Review and compatibility

Before release, inspect representative passes, failures, efficient trials, and outliers in Harbor’s local viewer. Quarantine a task that is ambiguous, contaminated, nondeterministic, unfair across providers, or broken by its own fixture.

Changing the task digest, pack composition, scorer, command classifier, environment image, provider-agent major contract, or methodology schema breaks the compatibility key by default. The repaired series is schema `0.2.0`; old hidden-contract and plugin-seed cohorts remain local and quarantined, are not regraded, and receive no reviewed mapping into the repaired series.
