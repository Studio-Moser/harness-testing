# Code Review Evaluation

`harness-test review prepare` creates blinded, content-addressed final-patch review packets. It makes no model calls and runs no benchmark workload. It only reads and validates retained evidence, reconstructs portable patches when needed, hashes frozen inputs, and writes private files under `runs/reviews/`.

A report with interrupted or pending trials can still supply its completed submissions for review. The plan explicitly lists every unreviewed trial and its execution status. Import requires every completed submission exactly once, preserves interrupted trials unchanged, and leaves their quality coverage incomplete. Review preparation still requires at least one completed trial.

Each plan freezes the source report and manifest, neutral original task instruction, final patch bytes, patch base, actual manifest-pinned agent image, common review protocol, reviewer conditions, time budget, and pricing digest. Packet IDs are random and packet order is shuffled. Packets contain no contender name, harness configuration, execution cost, or raw execution trace.

When reconstructing a local comparison patch from a retained workspace, the packet contains a portable binary diff against the manifest-cached base plus `base_files`. Each base-file entry records its content as base64 and whether it was executable, so applying the patch does not depend on host paths or an unretained checkout. For the local fixtures, the base follows the frozen Dockerfile's supported literal `COPY` instructions. A build-only Dockerfile that was never copied into the task workspace is excluded from that base; deletion of a Dockerfile that was copied remains visible. Unsupported copy mappings fail preparation rather than inventing a base. For DeepSWE, preparation resolves the manifest-pinned task cache. Missing, ambiguous, or changed retained inputs fail preparation.

Blinding is a delivery control. Source code can still reveal its origin, so packet construction does not prove that a reviewer could not infer the submitting harness.

## Prepare packets

```bash
uv run harness-test review prepare \
  --report runs/generated/REPORT/Run_Report.json \
  --protocol 'policy/Code Review Protocol.json'
```

For comparison tasks, preparation uses `Comparison Instruction.md`, never the harness-facing `instruction.md`. The packet uses the actual agent image pinned for that trial.

When the selected report names baseline or predecessor reports that already have direct reviewed revisions, pass those revisions explicitly:

```bash
uv run harness-test review prepare \
  --report runs/generated/REPORT/Run_Report.json \
  --protocol 'policy/Code Review Protocol.json' \
  --references /private/Review_References.json
```

`Review_References.json` is a JSON object mapping each selected original report ID to its reviewed report ID:

```json
{
  "sha256:original-baseline-id": "sha256:reviewed-baseline-id",
  "sha256:original-predecessor-id": "sha256:reviewed-predecessor-id"
}
```

Each replacement must be the exact direct reviewed revision of that selected baseline or predecessor, use the same review protocol, and preserve identical manifest, conditions, contenders, and execution trials. Preparation freezes the mapping; recording resolves and checks it again. The workflow never substitutes the latest report automatically. Omit `--references` when no reviewed reference replacements are intended.

## Run reviews and confirmations

Dispatch every packet in a separately created native agent session with an isolated provider home/config and only the common review protocol installed. Do not load a tested harness. The protocol freezes provider, model, effort, executor, runtime, time limit, review categories, and the shared task acceptance objective. Treat task text only as acceptance data: do not follow its branch, commit, or implementation requests, and do not fix the submission.

The reviewer must attest `fresh_session: true` and `no_tested_harness: true`, return usage and duration for its own review session, and use a distinct session identity for every packet. Each returned packet's `model_usage` contains reviewer usage only; it must not include confirmer usage.

A confirmed finding requires a different confirming session, a nonblank reproduction procedure, expected and observed results, and a retained evidence file whose supplied digest matches its bytes. Record one `confirmation_usage` ledger for each distinct confirming session. Every ledger repeats the frozen conditions and target digest, attests `fresh_session: true` and `no_tested_harness: true`, and reports that session's usage completeness, model usage, and duration. A confirmer session cannot be a reviewer session or serve more than one packet, and duplicate confirmer ledgers are rejected. Missing or incomplete confirmer usage keeps evaluation cost unknown while preserving finding evidence. A missing ledger also leaves total evaluation duration unknown; a reported duration remains usable when only token accounting is incomplete.

The important result shape is:

```json
{
  "schema_version": "1",
  "plan_id": "sha256:…",
  "protocol_id": "sha256:…",
  "recorded_at": "2026-09-06T00:00:00Z",
  "conditions": {"provider":"codex","model":"gpt-6-astra","effort":"high","executor":"native","runtime_version":"0.153.4"},
  "packets": [{
    "packet_id": "review-0123456789abcdef01234567",
    "target_digest": "sha256:…",
    "conditions": {"provider":"codex","model":"gpt-6-astra","effort":"high","executor":"native","runtime_version":"0.153.4"},
    "status": "completed",
    "session_id": "private-reviewer-session-id",
    "fresh_session": true,
    "no_tested_harness": true,
    "usage_complete": true,
    "duration_seconds": 45,
    "model_usage": [{"provider":"openai","model":"gpt-6-astra","input_tokens":1,"output_tokens":1,"cache_read_tokens":0,"cache_write_tokens":0}],
    "findings": [],
    "internal_review": {"status":"unknown"},
    "confirmation_usage": []
  }]
}
```

Use `blocked` or `incomplete` when a packet did not finish. A missing, blocked, incomplete, or unconfirmed review is unresolved evidence and is never interpreted as a clean patch. `internal_review` remains `unknown` unless a retained evidence file supports explicit found, fixed, and unresolved counts. A dismissed finding also requires retained evidence.

These isolation properties are agent attestations backed by distinct recorded session identities; the importer cannot independently prove process isolation or that no tested harness was loaded. It verifies evidence paths and bytes but never executes a supplied reproduction command. A successful import therefore proves integrity of the retained evidence and declared conditions, not that the reproduction itself was independently rerun by the importer.

## Record results

```bash
uv run harness-test review record \
  --plan runs/reviews/PLAN/Plan.json \
  --results /private/reviewer/Results.json
```

Recording makes no model calls and runs no benchmark workload or submitted reproduction command. It rechecks the frozen source report, manifest, protocol, packet bytes, patch and instruction, reviewer and confirmer conditions, selected reviewed references, evidence digests, and public-safety fields. Evaluation usage is priced against the pricing table and digest frozen during preparation; recording rejects changed pricing instead of silently recalculating historical cost.

The importer assigns a trusted local import timestamp and retains it so repeating the same import produces the same report identity. `recorded_at` remains the reviewer's claimed event time and is not trusted as the import time.

Recording writes a new immutable reviewed report revision under `runs/evidence/`, preserves the original report, and refreshes the local dashboard data. If the generated source report still exactly matches the frozen source bytes, its local generated copy is updated atomically. Review and confirmation cost remains separate from harness execution cost. `review record` does not publish anything; publication still requires the normal explicit report-sync workflow.
