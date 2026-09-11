# Collaboration Quality Evaluations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reproducible collaboration-quality evaluation, blinded grading, human calibration, conversational scenarios, and direct dashboard answers without changing engineering correctness verdicts.

**Architecture:** Capture a safe root-session transcript at the native conversation boundary, score it with a deterministic policy, and attach optional collaboration evidence to immutable version-3 reports. Use prepare/record workflows for identity-blinded model grading and human A/B labels, then aggregate those independent results in the read-only dashboard.

**Tech Stack:** Python 3.12, JSON Schema 2020-12, pytest, Observable Framework, browser-native JavaScript, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-10-collaboration-quality-evals-design.md`

## Global Constraints

- Collaboration quality remains separate from code correctness and efficiency.
- Only user-visible root-session text is graded; hidden reasoning, tools, outputs, and child transcripts are excluded.
- Historical reports remain schema-valid, and missing evidence remains unknown.
- Model-backed runs and graders require their existing explicit approval paths.
- Public reports fail closed on unsafe transcript content.

---

### Task 1: Communication contracts and transcript capture

**Files:**
- Create: `policy/Communication Contract.schema.json`
- Create: `policy/Communication Scenarios.json`
- Create: `src/harness_testing/Communication_Contracts.py`
- Modify: `src/harness_testing/Native_Conversation.py`
- Modify: `src/harness_testing/Trial_Evidence.py`
- Modify: `src/harness_testing/Comparison_Tasks.py`
- Create: `tests/unit/test_Communication_Contracts.py`
- Modify: `tests/unit/test_Native_Conversation.py`
- Modify: `tests/unit/test_Trial_Evidence.py`

**Interfaces:**
- Produces: `load_communication_contract(path) -> dict`, `communication_contract_for_task(root, task_id) -> dict`, and trial evidence field `transcript`.

- [ ] Write failing tests for strict contract validation, all ten scenario definitions, Codex/Claude visible-message capture, message kinds, ordinals, and elapsed timestamps.
- [ ] Run the focused tests and confirm the new assertions fail.
- [ ] Implement the schema, catalog, contract loader, and root-session transcript capture.
- [ ] Add contracts to the nine existing comparison tasks and copy them during comparison materialization.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Deterministic metrics and report schema

**Files:**
- Create: `src/harness_testing/Collaboration_Quality.py`
- Modify: `src/harness_testing/Experiment_Reports.py`
- Modify: `policy/Run_Report.schema.json`
- Create: `tests/Fixtures/Collaboration/Transcript.json`
- Create: `tests/unit/test_Collaboration_Quality.py`
- Modify: `tests/unit/test_Experiment_Reports.py`

**Interfaces:**
- Consumes: normalized `transcript`, task prompt, contract, and recorded model usage.
- Produces: `calculate_communication_metrics(...) -> dict`, per-trial `collaboration.contract`, `collaboration.transcript`, and `collaboration.metrics`.

- [ ] Write failing fixture tests for every metric, violation turn reference, missing timing, missing usage, and prompt repetition.
- [ ] Run the focused tests and confirm failure.
- [ ] Implement the deterministic tokenizer/detector policy and report attachment.
- [ ] Extend the optional version-3 trial schema without invalidating historical reports.
- [ ] Run focused report, schema, identity, and public-safety tests.

### Task 3: Blinded rubric grading and report import

**Files:**
- Create: `policy/Collaboration Grading Protocol.json`
- Create: `policy/Collaboration Grading Protocol.schema.json`
- Create: `policy/Collaboration Grading Results.schema.json`
- Create: `src/harness_testing/Collaboration_Grading.py`
- Modify: `src/harness_testing/CLI.py`
- Modify: `policy/Run_Report.schema.json`
- Create: `tests/unit/test_Collaboration_Grading.py`
- Modify: `tests/unit/test_CLI.py`

**Interfaces:**
- Produces: `prepare_grading(root, report_path, protocol_path) -> HarnessResult` and `record_grading(root, plan_path, results_path) -> HarnessResult`.

- [ ] Write failing tests proving packets omit contender/model identity and contain only task, contract, transcript, and final outcome.
- [ ] Add result-schema tests for eight scored dimensions, rationales, independent preference, grader identity, usage, cost, and rubric version.
- [ ] Implement randomized content-addressed plans and strict result import into a superseding immutable report.
- [ ] Add `harness-test collaboration prepare|record` CLI commands.
- [ ] Run focused grading, CLI, schema, tamper, safety, and report-identity tests.

### Task 4: Human calibration and personality-only support

**Files:**
- Create: `policy/Collaboration Calibration Labels.schema.json`
- Modify: `src/harness_testing/Collaboration_Grading.py`
- Modify: `src/harness_testing/CLI.py`
- Modify: `src/harness_testing/Experiments.py`
- Modify: `src/harness_testing/Contenders.py`
- Create: `runs/examples/Opus Personality Comparison.json`
- Modify: `tests/unit/test_Collaboration_Grading.py`
- Modify: `tests/unit/test_Experiments.py`
- Modify: `tests/unit/test_Contenders.py`

**Interfaces:**
- Produces: `prepare_calibration(...)`, `record_calibration(...)`, aggregate calibration count/agreement, and source-free `studio-personality` contender materialization from frozen startup files.

- [ ] Write failing tests for same-scenario A/B pairing, randomized side identity, label import, optional annoyance reason, agreement math, and the 15-label calibration threshold.
- [ ] Write failing tests for Nothing, personality-only, and complete Studio contender isolation.
- [ ] Implement calibration prepare/record commands and attach versioned labels to a superseding report.
- [ ] Permit a non-Nothing instruction-only contender while retaining the no-input rule for Nothing and content-derived identity.
- [ ] Add and validate an Opus 5 example request with identical conditions across the three variants.
- [ ] Run focused calibration, experiment, contender, and materialization tests.

### Task 5: Dashboard answers and evidence drill-down

**Files:**
- Create: `dashboard/src/components/Collaboration.js`
- Modify: `dashboard/src/components/Comparisons.js`
- Modify: `dashboard/src/Comparison.css`
- Modify: `dashboard/src/Comparisons.md`
- Modify: `dashboard/src/Run_Detail.md`
- Create: `dashboard/test/Collaboration.test.js`
- Modify: `dashboard/test/Comparisons.test.js`

**Interfaces:**
- Consumes: optional per-trial collaboration evidence and calibration labels.
- Produces: `summarizeCollaboration`, `renderCollaborationSummary`, and `renderCollaborationEvidence`.

- [ ] Write failing dashboard tests for preferred collaborator, talkativeness, interruptions, useful updates, personality effect, overhead, limitations, per-scenario rows, and exact-turn links.
- [ ] Implement answer-first collaboration summary and task-evidence transcript drill-down.
- [ ] Add responsive, accessible styling while preserving the existing dashboard visual language.
- [ ] Run dashboard tests and production build.

### Task 6: Documentation, validation, and review

**Files:**
- Modify: `README.md`
- Modify: `docs/Agent Experiment Guide.md`
- Modify: `docs/Runbook.md`
- Modify: `src/harness_testing/Validate.py`
- Modify: `tests/unit/test_Validate.py`

**Interfaces:**
- Consumes: the completed collaboration workflow.
- Produces: agent-facing preparation, approval, grading, calibration, publication, and interpretation instructions.

- [ ] Document how to add a contract, prepare blinded grades, record labels, run the Opus comparison, and interpret dashboard limitations.
- [ ] Add static validation for schemas, scenario catalog, task contracts, and example request.
- [ ] Run `uv run pytest -q`, `uv run ruff check .`, `uv run harness-test validate --static-only`, `npm test`, and `npm run build`.
- [ ] Run the Impeccable detector and inspect desktop/mobile dashboard renders once, fix the resulting batch, then confirm once.
- [ ] Request independent code review against the frozen branch diff and address confirmed findings.
