# Code Review Evaluation Plan

Approved intent: add the identical final-patch review layer discussed in chat. Implementation is authorized; this does not schedule additional benchmark model calls.

Outcome: agents can prepare blinded reviews of existing final submissions, record independently confirmed remaining defects and internal repair evidence, and inspect quality beside execution cost in the read-only dashboard.
Blockers: none for the agent-mediated workflow. Model execution is a separately authorized operation.
Testing seam: model-free CLI prepare/record against fixture final patches, strict rejection of altered targets or incomplete evidence, immutable report revision and dashboard rendering tests.
Proof: final full Python suite 550 passed; Ruff and static validation passed; dashboard 31 tests passed, eight pages built and one link validated. Live Chrome inspection verified the retained pilot shows test success separately from unknown final-review and internal-repair evidence. Model-free preparation succeeded for retained DeepSWE and local comparison trials. Independent review passed frozen tree `3e746c920bb1e9ba48e6e4c810ccc3b262b2fdab` after seven reported integrity/accounting/display/reference issues were corrected.

## Design

Use a separate, content-addressed evaluation plan. It binds the exact source report, task requirements, final patch bytes, pinned base/environment, common reviewer model/effort/runtime, review instructions and per-submission time budget. The plan also freezes pricing and explicit reviewed successors for any selected baseline or predecessor references. Random opaque packet IDs hide the mapping. Each packet carries only requirements, target, protocol and patch; the coordinator alone receives the mapping. Source code can reveal its author, so blinding is a delivery control, not a guarantee against inference.

The pipeline dispatches each packet in a fresh session with identical conditions and no tested harness installation. It records the actual conditions and completed/blocked/incomplete state. It does not fix submissions. Findings remain claims until a separate confirming session supplies a reproduction procedure, expected/observed result and a retained evidence file with verified digest. Import validates evidence integrity and attestation; it never executes submitted commands or equates an attestation with an automatically proven reproduction.

Execution and evaluation usage remain separate. Missing usage is unknown, including partial/failed evaluations. Internal review findings and fixes are optional evidence with explicit unknown state, never keyword-inferred or substituted for remaining defects. Import uses a retained local timestamp for stable revision identity and requires separate confirmation usage ledgers; missing accounting stays unknown. Imported summaries create a new immutable source report revision; they do not change original test scores, costs, publication authority or original evidence.

## Implementation

- [x] Add `Code_Reviews.py`, CLI `review prepare --report --protocol [--references]` and `review record --plan --results`. Use existing hash, schema/public-safety, job resolution and retained-report helpers. Prepare is model-free; record executes no supplied code.
- [x] Add strict protocol/results contracts and a versioned common review instruction; reject target, protocol, evidence, coverage, duplicate-ID and path-boundary mismatches. Tests cover blank/missing evidence, unconfirmed claims, altered packets and zero versus missing costs.
- [x] Add optional per-trial `code_review` summaries and experiment `code_review` metadata to the report schema. Preserve old reports. Keep missing review and incompatible protocol explicit; never let test-only evidence assert overall reviewed-code superiority.
- [x] Show remaining confirmed defects by severity, unconfirmed findings, internal repair evidence, review status and separate evaluation cost on comparison/task/history views. Existing diagnostic results remain explicitly selectable; no statistical winner from a pilot.
- [x] Document packet dispatch, independent confirmation, evidence recording and repeated version comparison in the agent guide. Verify a model-free end-to-end example, Python suite, dashboard tests/build and a live page.
- [x] Review a frozen implementation diff through the normal review route; reproduce findings, fix within scope and commit after verification. No push or publication.

## Shared public interface

Each trial may contain `code_review` with `protocol_id`, `status` (`completed`, `blocked`, `incomplete`), `target_digest`, `findings` (safe objects with `id`, `severity` P0–P3, `category`, `title`, relative `file`, positive `line`, `status` confirmed/unconfirmed/dismissed, `evidence_digest` nullable), `cost_usd` nullable, `duration_seconds` nullable, `usage_complete` boolean, `model_usage` in existing report format, and `internal_review` (`status` unknown/recorded, `found`, `fixed`, `unresolved` nullable integers, `evidence_digest` nullable). Completed with unconfirmed findings remains unresolved quality evidence.

Experiment `code_review`: `plan_id`, `protocol_id`, `source_report_id`, `results_digest`, `evaluation_cost_usd` nullable. No private mappings, reproduction commands, raw logs or session IDs cross this public boundary. Backend importer returns a new report path; report and dashboard integration consume these fixed fields.
