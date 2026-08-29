# Future Shelby Adapter Contract

## Status and boundary

This document defines an integration seam; it does not implement Shelby support. A future adapter would connect Shelby’s provider-neutral Rust headless runtime to Harbor 0.22.0 so Shelby harness changes can be measured by the same frozen tasks.

This repository must not contain Shelby source, production memory, private schemas, credentials, personal paths, an executable adapter, or macOS-native application code. The native app may use the same runtime, but it is not the Harbor execution boundary.

## Harbor agent boundary

The future Python bridge subclasses Harbor’s `BaseInstalledAgent` and provides:

- stable `name()` identity and `version()` reporting;
- `SUPPORTS_ATIF = True`;
- `install(environment)` for the pinned headless runtime and its required files;
- `run(instruction, environment, context)` to start one isolated run and wait for its terminal event; and
- `populate_context_post_run(context)` to parse durable output after Harbor synchronizes logs.

Do not override `setup()`. `BaseInstalledAgent.setup()` owns `/installed-agent`, error wrapping, the call to `install()`, and best-effort version detection. Installation uses the inherited root/agent execution helpers and an immutable runtime artifact.

`run()` must accept only the supplied instruction, environment, and task-scoped configuration. It must not load a normal Shelby profile or memory. Cancellation is cooperative first and forceful after a bounded grace period; either path writes one terminal event before returning whenever the process can still do so.

## Runtime event contract

The Rust runtime emits typed, append-only JSON Lines to a run-scoped file. Each event has a schema version, durable run ID, monotonic sequence number, timestamp, type, and typed payload. Once written, an event is never edited or reordered.

Minimum event families are:

| Runtime event | Required meaning | ATIF v1.7 mapping |
| --- | --- | --- |
| `run_started` | Runtime/agent/model identity and durable run ID | Root `session_id`, `trajectory_id`, and `agent` |
| `turn_started` / `assistant_message` | Ordered model turn and assistant content | Sequential `steps` with message source |
| `tool_call` | Unique call ID, tool name, and structured arguments | Step `tool_calls` |
| `tool_result` | Matching call ID, result status, and bounded content | Observation referencing the call ID |
| `usage` | Provider-reported input, cache, output, and cost fields | `final_metrics` and `AgentContext` when available |
| `run_cancelled` | Cancellation request and terminal outcome | Final step plus adapter metadata |
| `run_completed` / `run_failed` | Exactly one terminal state | Final step and terminal adapter metadata |

ATIF step IDs are sequential from one. The root `session_id` represents the logical run. Every trajectory document receives a distinct `trajectory_id`; any embedded subagent trajectory has its own unique ID even if it shares the run-scoped session ID.

Tool arguments and results must retain enough structure for deterministic command classification, but publication remains governed by the public-result allowlist. Raw events and trajectories stay local.

## Nullable telemetry

`populate_context_post_run()` may set Harbor `AgentContext.n_input_tokens`, `n_cache_tokens`, `n_output_tokens`, `cost_usd`, `rollout_details`, and adapter `metadata`. It sets a value only when the runtime or provider reported it with known semantics. Unsupported or missing values remain `None`; the adapter never substitutes zero or estimates provider billing.

The adapter records runtime version, event-schema version, durable run ID, terminal state, and cancellation outcome in namespaced metadata. Secrets, prompts, reasoning, raw tool output, and private memory do not belong in context metadata.

## Conceptual manifest

The eventual implementation should bind an immutable contract equivalent to this non-executable example:

```yaml
schema_version: "1"
adapter:
  harbor: "0.22.0"
  base_class: "BaseInstalledAgent"
  identity: "shelby-headless"
  supports_atif: true
runtime:
  implementation: "provider-neutral-rust-headless"
  artifact_digest: "sha256:<immutable-runtime-digest>"
events:
  format: "append-only-jsonl"
  schema_version: "<pinned-event-schema>"
  sequence: "strictly-monotonic"
identity:
  run_id: "durable-runtime-run-id"
  session_id: "same-logical-run"
  trajectory_id: "unique-document-id"
cancellation:
  terminal_event_required: true
  bounded_grace_period: true
outputs:
  trajectory: "ATIF-v1.7"
  telemetry: "nullable-agent-context"
```

## Acceptance gate

Implementation can begin only after the Rust headless runtime exists and its event schema is frozen. The adapter then needs model-free contract tests for installation, identity, ordered event conversion, tool-call references, nullable telemetry, completion, failure, cancellation, malformed/truncated logs, and timeout recovery before any approved model-backed comparison.
