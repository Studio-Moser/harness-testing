# Collaboration Quality Evaluations Design

## Goal

Measure whether a harness makes an agent better to work with, especially Claude Opus 5, while keeping collaboration quality separate from engineering correctness and execution efficiency.

## Evidence model

Every applicable task carries a versioned `Communication Contract.json`. The contract identifies the scenario, sets scenario-specific limits for questions, approval requests, progress updates, and final-answer length, and names the rubric dimensions to grade. Its content digest is frozen with the task and copied into the report.

The native conversation controller records only user-visible root-session messages. Each message has a stable ordinal, role, kind (`user`, `progress`, or `final`), text, and elapsed seconds from the first task turn. Hidden reasoning, tool calls, tool output, and child-session conversation do not enter collaboration scoring. Report construction fails closed when a transcript is incomplete or unsafe to publish.

## Deterministic metrics

`Collaboration_Quality.py` calculates reproducible metrics from the frozen contract and transcript:

- assistant and total visible words and tokens;
- assistant, progress, and final-message counts and lengths;
- question and approval-request counts, including excess counts against the contract;
- heading, bullet, and formatting density;
- prompt-restatement and repeated-sentence evidence;
- configured slop-phrase matches;
- average and maximum time between assistant updates;
- communication-token share of recorded model output;
- progress updates containing a finding, decision, blocker, or changed direction.

Each flagged behavior retains the message ordinal so the dashboard can link to the exact turn. Metrics use an explicitly versioned tokenizer and detector policy. Missing transcript, timing, model-usage, or contract evidence stays unavailable rather than becoming zero.

## Blinded grading

The `harness-test collaboration prepare` command creates randomized grading packets from completed version-3 trials. A packet contains only the task prompt, communication contract, user-visible transcript, and final trial outcome. It excludes contender labels, model identity, source commits, routing, token cost, and trial identifiers.

`harness-test collaboration record` accepts results validated against a checked-in schema. Every rubric dimension has a 1–5 score and short rationale. The result separately records whether Tim would want to work with the assistant again, grader model and effort, rubric version, usage, duration, and standardized cost. Import attaches the evidence to a new immutable report that supersedes the source report.

## Calibration

The calibration flow creates randomized A/B packets from two eligible transcripts for the same scenario. A versioned label records the preferred side and an optional annoyance reason without exposing contender identity during labeling. Imported labels map back to trial identities, remain inspectable, and report automated-grader agreement only when both transcripts have compatible completed grades.

Automated preference is advisory until at least 15 human labels exist. The dashboard states calibration size and agreement instead of treating an uncalibrated model judge as ground truth.

## Scenario and contender support

The repository defines ten conversational contracts: direct repository question, clear small edit, ambiguous feature, mid-task status, user correction, technical disagreement, recoverable failure, authorized routine action, consequential action, and completed implementation. The scenario catalog freezes identical user turns and communication expectations for every contender. Existing development tasks also receive contracts so retained complete transcripts can be graded without rerunning the coding task.

A personality-only contender may use pinned startup instruction files without plugins or a rubric. This supports the Opus 5 comparison among no local instructions, Studio personality/unslop only, and complete Studio Moser Lite while keeping model, effort, scenario, tools, and runtime conditions fixed.

## Dashboard

The comparison page adds a distinct “Collaboration quality” section before detailed engineering tables. It answers:

- preferred collaborator and the evidence supporting the preference;
- least and most talkative contender;
- avoidable interruption and useful-progress rates;
- communication-token overhead;
- personality-layer effect when the required three Opus variants exist;
- worst observed behavior with an exact transcript-turn link;
- per-scenario outcomes, grader calibration agreement, confidence, and evidence limitations.

The task-evidence page shows the contract, deterministic metrics, rubric scores and rationales, and the safe transcript. No collaboration score changes the correctness verdict or efficiency recommendation.

## Safety and compatibility

Raw provider traces remain ignored and local. Public transcript text passes the existing public-safety checks before report publication. The run-report schema adds optional collaboration fields so historical reports remain valid. A new content-derived report identity covers imported grading and calibration evidence.

No model-backed grader or Opus run starts as part of implementation. Those operations continue to require the existing exact-manifest or explicit review-cost approval.

## Verification

Fixture transcripts cover every deterministic detector, missing evidence, blinding, scenario budgets, rubric versioning, calibration agreement, and public-safety rejection. Dashboard tests verify plain-language conclusions, separation from correctness, per-scenario results, and exact-turn links. The final pass runs Python tests, dashboard tests/build, Ruff, static validation, and desktop/mobile browser inspection.
