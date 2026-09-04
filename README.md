# Harness Testing

Harness Testing is Studio Moser’s public, deterministic benchmark for measuring how coding-agent harness changes affect correctness, workflow discipline, testing churn, elapsed time, tokens, and cost.

Every task runs against a frozen synthetic or public test project. A run never mounts a live product repository, personal project state, Shelby memory, or a developer’s normal Claude or Codex home. Model-backed runs are manual and require approval of an exact generated manifest digest.

## Safe quick start

These commands are model-free:

```bash
uv sync --frozen
uv run harness-test validate --static-only
npm ci --prefix dashboard --ignore-scripts
npm --prefix dashboard test
npm --prefix dashboard run build
```

Run one deterministic task case while authoring a task:

```bash
uv run harness-test task qa --task react-grouped-ui-updates --case oracle
uv run harness-test task qa --task react-grouped-ui-updates --case nop
```

The broader pack gates are intentionally saved for a checkpoint:

```bash
uv run harness-test task qa --pack workflow --all-cases
uv run harness-test task qa --pack contract --all-cases
```

## Experiment arms

| Arm | Layers | Purpose |
| --- | --- | --- |
| A0 | Stock provider | Provider-native baseline |
| A1 | Superpowers | Superpowers contribution in isolation |
| A2 | Studio Harness | Studio Harness contribution in isolation |
| A3 | Superpowers, then Studio Harness | Interaction and overlap calibration |

Claude receives immutable plugin directories through repeatable `--plugin-dir` flags. Those directories are checked without a model by `claude plugin validate --strict`; no plugin seed is created. Codex keeps native marketplace and plugin materialization, records its plugin inventory before dispatch, and exposes Superpowers as **skills-only**. Studio Harness uses each provider’s supported native surface.

## What is scored

- **Correctness**: the frozen task’s behavior and protected state are correct.
- **Workflow**: the agent obeys the requested implementation and verification sequence.
- **Efficiency policy**: the agent avoids premature comprehensive suites, duplicate successful commands, unnecessary plans/reviews/subagents/worktrees, and other measurable churn.

Runtime, tokens, cache usage, cost, commands, test classes, retries, and infrastructure events remain separate nullable measurements. The benchmark does not hide quality tradeoffs behind a composite rank.

The initial workflow pack covers React, TypeScript, static HTML/CSS/JavaScript, and Rust. The contract pack exercises Studio Harness behavior with local deterministic stubs. The optional DeepSWE lane is a manual capability check whose pinned source is not redistributed because the selected upstream tree has no license file.

## Runs, results, and dashboard

`harness-test run plan` writes an ignored, content-addressed manifest and starts no model session. `--invoke-skill` measures explicit capability; `--observe-skill` preserves the raw task, requires at least five attempts, and measures automatic discovery without a pass threshold. `harness-test run execute` accepts only the exact manifest digest and writes public-safe skill observations beside it. The first selected task is the delivery canary across every selected cell: a correctness zero continues, while an infrastructure or delivery failure stops the run. Subscription mode forbids API-key fallback; API mode exposes an admission estimate and explicit maximum, not a provider-side hard stop.

Raw Harbor jobs remain under ignored local paths. Every execution writes an allowlisted `Run_Report.json` beside its manifest and refreshes the ignored local dashboard once after the run, including after a handled failure. At that terminal point it also attempts one batched publication of every pending report; a failed update leaves the run evidence local and prints the exact `uv run harness-test report sync` retry command.

Public run reports form the **development-history lane**. They may be incomplete, failed, unreviewed, quarantined, or historical, so they show progress and operational failures but are not automatically release evidence. The separate **decision-grade lane** is unchanged: only reviewed, finalized files produced through `harness-test result sanitize` may enter `results/`, and publication still requires a content-valid current-series manifest with no reviewed mapping. Dashboard comparisons join observations only when their non-null series keys are equal.

Published development history lives as allowlisted JSON on the dedicated `dashboard-data` branch; dashboard code and decision-grade results remain on `main`. The Observable Framework site combines those two inputs into Latest, Trends, Comparisons, Task matrix, Run detail, and Quality versus efficiency without exposing prompts, trajectories, command output, credentials, or host paths.

See [Methodology](docs/Methodology.md), [Runbook](docs/Runbook.md), [Task Authoring](docs/Task_Authoring.md), and the [DeepSWE Capability Pack](docs/Capability_Pack.md).

## Shelby status

Shelby is future-only. This repository contains an adapter contract for eventually connecting a provider-neutral Rust runtime to Harbor; it contains no Shelby source, private memory, executable adapter, or production schema. See [Shelby Adapter Contract](docs/Shelby_Adapter_Contract.md).
