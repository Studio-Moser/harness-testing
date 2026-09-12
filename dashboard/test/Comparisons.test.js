import assert from "node:assert/strict";
import test from "node:test";
import {codeReviewCountLabel, codeReviewCoverageLabel, comparisonReports, comparisonVerdict, internalReviewCoverageLabel, renderComparison, renderTaskTypes, renderEvidence, renderHistory, selectComparison, comparisonUrl, summarizeCodeReview, summarizeInternalReview, summarizeTests, versionHistory, sortNumericRows, trialLabel} from "../src/components/Comparisons.js";
import {collaborationVerdict, renderCollaboration, summarizeCollaboration, transcriptAnchor} from "../src/components/Collaboration.js";

function report(id, version, purpose = "candidate") {
  return {schema_version: "3", report_id: id, run_id: `run-${id}`, updated_at: `2026-09-05T12:00:0${id}Z`, experiment: {label: id, purpose, contenders: [{id: version, family: "studio-moser", label: version}], predecessor_result_ids: [], comparison: {status: "insufficient_evidence"}}};
}

test("selects comparison evidence explicitly and never defaults to a later diagnostic", () => {
  const reports = [report("1", "v1"), report("2", "v2", "diagnostic"), {schema_version: "2"}];
  assert.equal(comparisonReports(reports).length, 1);
  assert.equal(selectComparison(reports).report_id, "1");
  assert.equal(selectComparison(reports, "missing"), null);
  assert.equal(selectComparison(reports, "2").report_id, "2");
});

test("URL selections are encoded and preserved across views", () => {
  const url = new URL(comparisonUrl("/Run_Detail", {comparison: "sha256:a", task: "a & b", version: "v1"}), "https://example.invalid");
  assert.equal(url.searchParams.get("task"), "a & b");
  assert.equal(url.searchParams.get("comparison"), "sha256:a");
  assert.equal(url.searchParams.get("version"), "v1");
});

test("version history groups reruns and preserves explicit predecessors", () => {
  const reports = [report("1", "v1"), report("2", "v1"), report("3", "branch")];
  reports[2].experiment.predecessor_result_ids = ["1"];
  const versions = versionHistory(reports);
  assert.equal(versions.find(v => v.id === "v1").runs.length, 2);
  assert.deepEqual(versions.find(v => v.id === "branch").runs[0].experiment.predecessor_result_ids, ["1"]);
});

test("sorts measurements numerically with nulls last in either direction", () => {
  const rows = [{time: 102.8}, {time: 38.5}, {time: null}];
  assert.deepEqual(sortNumericRows(rows, "time").map(row => row.time), [38.5, 102.8, null]);
  assert.deepEqual(sortNumericRows(rows, "time", false).map(row => row.time), [102.8, 38.5, null]);
  assert.equal(rows[0].time, 102.8);
});


test("trial labels distinguish protected failures and incomplete execution", () => {
  assert.equal(trialLabel({status:"completed", correctness:true, protected_state:true}), "Passed");
  assert.equal(trialLabel({status:"completed", correctness:true, protected_state:false}), "Protected-state check failed");
  assert.equal(trialLabel({status:"completed", correctness:true, protected_state:null}), "Tests passed · protected state unknown");
  assert.equal(trialLabel({status:"timeout", correctness:true, protected_state:true}), "timeout");
  assert.equal(trialLabel({status:"completed", correctness:null, protected_state:null}), "Ungraded");
  assert.equal(trialLabel({status:"task_definition_gap", correctness:false, protected_state:true}), "task definition gap");
  assert.equal(trialLabel({status:"infrastructure_failure", correctness:false, protected_state:false}), "infrastructure failure");
  assert.equal(trialLabel({status:"infrastructure_failure", incomplete_reasons:["provider_transport_interrupted"]}), "Provider connection interrupted");
});

test("task evidence explains bounded provider recovery without hiding elapsed time", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag)};
  try {
    const current = typedReport();
    const trial = current.experiment.trials[0];
    trial.status = "infrastructure_failure";
    trial.duration_seconds = 700;
    trial.incomplete_reasons = ["provider_transport_interrupted"];
    trial.provider_recovery = {allowance_seconds: 600, transport_error_count: 4, extension_applied: true};
    const text = renderEvidence([current], {comparison: "typed"}).textContent;
    assert.match(text, /Provider connection interrupted/);
    assert.match(text, /4 transport errors.*10m 0s recovery allowance activated/);
    assert.match(text, /Elapsed time includes connection waits/);
    assert.match(text, /excluded from harness quality judgments/);
  } finally { globalThis.document = previousDocument; }
});

test("derives exact review coverage and keeps unknown evaluation cost distinct from zero", () => {
  const contender = {id: "harness", scheduled: 4};
  const reviewed = summarizeCodeReview(contender, [
    {contender_id: "harness", code_review: {status: "completed", protocol_id: "review-v1", cost_usd: 0, usage_complete: true, findings: [{severity: "P1", status: "confirmed"}, {severity: "P3", status: "unconfirmed"}]}},
    {contender_id: "harness", code_review: {status: "blocked", protocol_id: "review-v1", cost_usd: null, usage_complete: false, findings: []}},
    {contender_id: "harness", code_review: {status: "incomplete", protocol_id: "review-v1", cost_usd: 0.2, usage_complete: false, findings: []}},
    {contender_id: "harness"}
  ]);
  assert.deepEqual(reviewed.confirmed, {P0: 0, P1: 1, P2: 0, P3: 0});
  assert.equal(reviewed.unconfirmed, 1);
  assert.equal(reviewed.evaluation_cost_usd, null);
  assert.equal(codeReviewCoverageLabel(reviewed), "1 completed · 1 blocked · 1 incomplete · 1 missing of 4");
  assert.equal(codeReviewCountLabel(reviewed, 0), "0 recorded");

  const aggregate = summarizeCodeReview({id: "harness", code_review: {status: "completed", completed: 1, scheduled: 1, protocol_id: "review-v1", confirmed: {P0: 0, P1: 0, P2: 0, P3: 0}, unconfirmed: 0, evaluation_cost_usd: 0}}, []);
  assert.equal(aggregate.evaluation_cost_usd, 0);
  assert.equal(codeReviewCountLabel(aggregate, 0), "0");
  const derivedZero = summarizeCodeReview({id: "harness", scheduled: 1}, [{contender_id: "harness", code_review: {status: "completed", protocol_id: "review-v1", cost_usd: 0, usage_complete: true, findings: []}}]);
  assert.equal(derivedZero.evaluation_cost_usd, 0);
  assert.equal(codeReviewCountLabel(summarizeCodeReview({id: "unreviewed", scheduled: 1}), 0), "Unknown");
});

test("test-only and diagnostic reports cannot present an overall code quality winner", () => {
  const base = report("1", "v1");
  base.experiment.purpose = "candidate";
  base.experiment.trials = [];
  base.experiment.comparison = {status: "recommended", winner_id: "v1", summary: "The harness passed the tests.", contenders: [{id: "v1", label: "Harness", scheduled: 1}]};
  assert.match(comparisonVerdict(base).heading, /^Tests only/);
  assert.match(comparisonVerdict(base).summary, /does not establish remaining code quality/);
  base.experiment.purpose = "diagnostic";
  assert.match(comparisonVerdict(base).heading, /^Diagnostic result/);
  assert.match(comparisonVerdict(base).summary, /limited task sample/);
  assert.match(comparisonVerdict(base).summary, /cannot establish an overall harness winner/);
});

test("confirmed defects disqualify their contender while unconfirmed claims block all winners", () => {
  const base = report("1", "v1");
  const clean = {status: "completed", completed: 1, scheduled: 1, protocol_id: "review-v1", confirmed: {P0: 0, P1: 0, P2: 0, P3: 0}, unconfirmed: 0, evaluation_cost_usd: 0};
  const defect = {...clean, confirmed: {...clean.confirmed, P2: 1}};
  base.experiment.trials = [];
  base.experiment.comparison = {status: "recommended", winner_id: "clean", summary: "Clean passed.", contenders: [{id: "clean", label: "Clean", code_review: clean}, {id: "defect", label: "Defect", code_review: defect}]};
  assert.equal(comparisonVerdict(base).heading, "Clean is the supported choice");
  base.experiment.comparison.contenders[1].code_review = {...defect, unconfirmed: 1};
  assert.equal(comparisonVerdict(base).heading, "Reviewer claims remain unresolved");
});

test("internal repair counts stay unknown until every scheduled trial documents them", () => {
  const partial = summarizeInternalReview({id: "harness", scheduled: 2}, [
    {contender_id: "harness", code_review: {internal_review: {status: "recorded", found: 2, fixed: 1, unresolved: 1}}},
    {contender_id: "harness", code_review: {internal_review: {status: "unknown", found: null, fixed: null, unresolved: null}}}
  ]);
  assert.deepEqual(partial, {recorded: 1, scheduled: 2, found: null, fixed: null, unresolved: null, known: false});
  assert.equal(internalReviewCoverageLabel(partial), "Unknown (1 / 2 trials documented)");

  const complete = summarizeInternalReview({id: "harness", code_review: {internal_review: {recorded: 2, scheduled: 2, found: 3, fixed: 2, unresolved: 1}}});
  assert.deepEqual(complete, {recorded: 2, scheduled: 2, found: 3, fixed: 2, unresolved: 1, known: true});
});

class FakeElement {
  constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; this._text = ""; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent ?? String(child)).join(""); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this._text = ""; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener() {}
}

test("comparison table uses raw test passes, protected-state notes, and total execution cost", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag)};
  try {
    const trial = {task_id: "task-one", contender_id: "quill", attempt: 1, status: "completed", correctness: true, protected_state: null};
    assert.deepEqual(summarizeTests({id: "quill", scheduled: 1}, [trial]), {passed: 1, scheduled: 1, protected_unknown: 1, evidence_complete: true});
    const current = {
      schema_version: "3", report_id: "diagnostic", updated_at: "2026-09-06T12:00:00Z", evidence: {review_state: "unreviewed"},
      experiment: {
        label: "Quill diagnostic", purpose: "diagnostic", baseline_result_ids: [], predecessor_result_ids: [], supersedes_report_id: null,
        conditions: {kickoff: {model: "model", effort: "high", provider: "openai", runtime_version: "1"}, task_ids: ["task-one"], attempts: 1, decision_policy: "policy"},
        contenders: [{id: "quill", label: "Quill", family: "quill"}], trials: [trial],
        change: {summary: "Diagnostic sample", hypothesis: "Inspect behavior", rerun_reason: null, diff_digest: "sha256:diff"},
        comparison: {status: "insufficient_evidence", winner_id: null, summary: "Not enough evidence.", reasons: ["diagnostic_only"], provisional: true, policy_id: "policy", pairs: [], limitations: [], contenders: [{id: "quill", label: "Quill", family: "quill", scheduled: 1, successes: 0, eligible: false, coverage_complete: true, counts: {completed: 1}, total_cost_usd: 3.24, mean_duration_seconds: 12, total_tokens: 100}]}
      }
    };
    const text = renderComparison([current], {comparison: "diagnostic"}).textContent;
    assert.match(text, /HarnessTests passedExecution cost/);
    assert.match(text, /Protected state unknown1 \/ 1\$3\.24/);
    assert.match(text, /Not reviewedUnknownUnknownUnknownUnknownUnknownUnknown/);
    assert.match(text, /Internal repair evidenceCounts describe review findings and fixes recorded during the original implementation/);
    assert.match(text, /Unknown \(0 \/ 1 trials documented\)UnknownUnknownUnknown/);
    trial.protected_state = true;
    const contender = current.experiment.comparison.contenders[0];
    contender.successes = 1;
    let updated = renderComparison([current], {comparison: "diagnostic"}).textContent;
    assert.match(updated, /Code review not recorded1 \/ 1/);
    assert.doesNotMatch(updated, /Failed required checks|Failed task checks/);
    contender.code_review = {status: "completed", scheduled: 1, completed: 1, protocol_id: "review-v1", confirmed: {P0: 0, P1: 0, P2: 1, P3: 0}, unconfirmed: 0};
    assert.match(renderComparison([current], {comparison: "diagnostic"}).textContent, /Confirmed remaining defects1 \/ 1/);
    contender.code_review.unconfirmed = 1;
    assert.match(renderComparison([current], {comparison: "diagnostic"}).textContent, /Unresolved review claims1 \/ 1/);
    contender.code_review.status = "incomplete";
    assert.match(renderComparison([current], {comparison: "diagnostic"}).textContent, /Code review incomplete1 \/ 1/);
    contender.successes = 0;
    trial.correctness = false;
    assert.match(renderComparison([current], {comparison: "diagnostic"}).textContent, /Failed task checks0 \/ 1/);
    contender.coverage_complete = false;
    assert.match(renderComparison([current], {comparison: "diagnostic"}).textContent, /Incomplete task evidence0 \/ 1/);

  } finally {
    globalThis.document = previousDocument;
  }
});

test("history summarizes current and predecessor internal repair evidence", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag)};
  try {
    const current = report("4", "current");
    current.experiment.baseline_result_ids = [];
    current.experiment.trials = [];
    current.experiment.change = {summary: "Changed behavior", hypothesis: "Improve quality", rerun_reason: null};
    current.experiment.comparison = {
      status: "no_clear_winner",
      contenders: [{id: "current", label: "Current", code_review: {status: "completed", completed: 1, scheduled: 1, protocol_id: "review-v1", confirmed: {P0: 0, P1: 0, P2: 0, P3: 0}, unconfirmed: 0, evaluation_cost_usd: 1, internal_review: {recorded: 1, scheduled: 1, found: 2, fixed: 2, unresolved: 0}}}],
      history: {status: "no_clear_change", summary: "No test change.", predecessor_contenders: [{id: "prior", label: "Prior", code_review: {status: "completed", completed: 1, scheduled: 1, protocol_id: "review-v1", confirmed: {P0: 0, P1: 0, P2: 0, P3: 0}, unconfirmed: 0, evaluation_cost_usd: 1, internal_review: {recorded: 0, scheduled: 1, found: null, fixed: null, unresolved: null}}}]}
    };
    const text = renderHistory([current]).textContent;
    assert.match(text, /Internal repair evidence: 2 found · 2 fixed · 0 unresolved \(1 \/ 1 trials documented\)/);
    assert.match(text, /Prior predecessor.*internal repair evidence: unknown \(0 \/ 1 trials documented\)/i);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("task evidence renders safe review findings and explicit unknown internal evidence", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag)};
  try {
    const current = {
      schema_version: "3",
      report_id: "reviewed",
      evidence: {review_state: "reviewed"},
      experiment: {
        label: "Reviewed comparison",
        purpose: "candidate",
        baseline_result_ids: [],
        contenders: [{id: "harness", label: "Harness"}],
        conditions: {task_ids: ["task-one"]},
        trials: [{
          task_id: "task-one", contender_id: "harness", attempt: 1, status: "completed", correctness: true, protected_state: true,
          duration_seconds: 10, cost_usd: 0.1, usage_complete: true, child_count: 0, interaction_count: 0, incomplete_reasons: [], model_usage: [], session_usage: [],
          code_review: {protocol_id: "review-v1", status: "completed", duration_seconds: 5, cost_usd: null, usage_complete: false, model_usage: [], findings: [{severity: "P1", status: "confirmed", title: "Escaped value is lost", file: "src/parser.js", line: 42, category: "correctness"}]}
        }]
      }
    };
    const text = renderEvidence([current], {comparison: "reviewed"}).textContent;
    assert.match(text, /P1 · confirmed · Escaped value is lost · src\/parser\.js:42/);
    assert.match(text, /Evaluation: 5\.0s · cost unknown · usage incomplete/);
    assert.match(text, /Internal repair evidence: unknown/);
    assert.match(text, /Report provenance · independently checked; comparison evidence provisional\. This is separate from final-patch code review/);
  } finally {
    globalThis.document = previousDocument;
  }
});

function typedReport() {
  const contenders = [{id: "nothing", label: "Nothing"}, {id: "studio", label: "Studio Moser"}];
  return {schema_version: "3", report_id: "typed", updated_at: "2026-09-07T00:00:00Z", experiment: {
    label: "Typed diagnostic", purpose: "diagnostic", baseline_result_ids: [], contenders,
    conditions: {task_ids: ["quill-shared-toolbar-focus"], attempts: 1},
    comparison: {contenders},
    trials: contenders.map((row, i) => ({task_id: "quill-shared-toolbar-focus", contender_id: row.id, attempt: 1,
      status: "completed", correctness: true, protected_state: null, usage_complete: true,
      pricing_digest: "pricing-v1", cost_usd: i + 1, duration_seconds: (i + 1) * 60, interaction_count: 0,
      model_usage: [{input_tokens: 10, output_tokens: 2, cache_read_tokens: 0, cache_write_tokens: 0}],
      session_usage: [{session: "root", model: "sol", effort: "medium", input_tokens: 7, cache_read_tokens: 3, cache_write_tokens: 1, output_tokens: 2}],
      code_review: {status: "completed", protocol_id: "same", findings: [{status: "confirmed", severity: "P2"}]}
    }))
  }};
}

test("task evidence distinguishes whole-tree totals from session ownership", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag)};
  try {
    const text = renderEvidence([typedReport()], {comparison: "typed"}).textContent;
    assert.match(text, /Whole-tree execution: completed · 1m 0s · \$1\.00/);
    assert.match(text, /Orchestrator and child usage/);
    assert.match(text, /Orchestrator: sol · medium effort · 7 input \+ 3 cache read \+ 1 cache write \+ 2 output tokens/);
  } finally {
    globalThis.document = previousDocument;
  }
});

function descendants(node) { return [node, ...node.children.flatMap(descendants)]; }

function collaborationTrial(contenderId, {tokens = 100, workAgain = true, score = 4, violations = [], scenario = "clear_small_edit", communicationRatio = 0.2} = {}) {
  return {
    trial_id: `sha256:${contenderId.padEnd(64, "0")}`,
    task_id: "react-active-badge-count",
    contender_id: contenderId,
    attempt: 1,
    status: "completed",
    correctness: true,
    protected_state: true,
    duration_seconds: 8,
    cost_usd: 0.01,
    usage_complete: true,
    child_count: 0,
    interaction_count: 0,
    incomplete_reasons: [],
    model_usage: [],
    session_usage: [],
    collaboration: {
      status: "complete",
      reasons: [],
      contract: {scenario, expectations: {progress_updates: {maximum: 2}, questions: {maximum: 0}, approval_requests: {maximum: 0}, final_answer_words: {maximum: 100}}},
      metrics: {
        assistant_tokens: tokens,
        final_answer_words: Math.round(tokens / 2),
        progress_update_count: 1,
        useful_progress_update_count: 1,
        communication_to_model_output_ratio: communicationRatio,
        unnecessary_question_count: 0,
        unnecessary_approval_request_count: 0,
        slop_phrase_count: 0,
        violations
      },
      transcript: [
        {ordinal: 1, role: "user", kind: "user", content: "Fix the count.", elapsed_seconds: 0},
        {ordinal: 2, role: "assistant", kind: "progress", content: "I found the stale selector.", elapsed_seconds: 2},
        {ordinal: 3, role: "assistant", kind: "final", content: "Fixed and tested.", elapsed_seconds: 8}
      ],
      grade: {
        status: "completed",
        would_work_again: workAgain,
        dimensions: ["directness", "proportionality", "progress_usefulness", "autonomy", "candor", "warmth", "restraint", "completion_clarity"].map(name => ({name, score, rationale: `${name} was observable.`}))
      }
    }
  };
}

test("collaboration summary names an automated leader only with complete blind grading", () => {
  const contenders = [{id: "nothing", label: "Nothing"}, {id: "studio", label: "Studio Moser"}];
  const trials = [
    collaborationTrial("nothing", {tokens: 220, workAgain: false, score: 2}),
    collaborationTrial("studio", {tokens: 90, workAgain: true, score: 5})
  ];
  const summaries = summarizeCollaboration(contenders, trials);
  assert.equal(summaries[1].meanAssistantTokens, 90);
  assert.equal(summaries[1].meanRubricScore, 5);
  assert.equal(summaries[1].wouldWorkAgain, 1);
  assert.match(collaborationVerdict({experiment: {}}, contenders, trials).heading, /Studio Moser is the automated collaboration leader/);
  delete trials[1].collaboration.grade;
  assert.equal(collaborationVerdict({experiment: {}}, contenders, trials).heading, "Collaboration grading is incomplete");
});

test("dashboard answers who is easier to work with and shows calibrated human preference", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag)};
  try {
    const current = typedReport();
    current.experiment.contenders[0].family = "nothing";
    current.experiment.contenders[1].family = "studio-moser";
    current.experiment.comparison.contenders[0].family = "nothing";
    current.experiment.comparison.contenders[1].family = "studio-moser";
    current.experiment.conditions.kickoff = {model: "opus", effort: "high", provider: "claude", runtime_version: "1"};
    current.experiment.conditions.decision_policy = "policy";
    current.experiment.change = {summary: "Add personality guidance", hypothesis: "Reduce annoying responses", rerun_reason: null, diff_digest: "sha256:diff"};
    Object.assign(current.experiment.comparison, {status: "insufficient_evidence", winner_id: null, summary: "No engineering winner.", reasons: [], provisional: true, policy_id: "policy", pairs: [], limitations: []});
    current.experiment.trials = [
      collaborationTrial("nothing", {tokens: 220, workAgain: false, score: 2, violations: [{kind: "long_final_answer", ordinal: 3, detail: "Too long"}]}),
      collaborationTrial("studio", {tokens: 90, workAgain: true, score: 5})
    ];
    current.experiment.collaboration_calibration = {
      calibrated: true,
      labels: [
        {preferred_contender_id: "studio", other_contender_id: "nothing", grader_agreement: true, scenario: "clear_small_edit", annoyance_reason: "Nothing kept talking."},
        {preferred_contender_id: "studio", other_contender_id: "nothing", grader_agreement: true, scenario: "clear_small_edit", annoyance_reason: null}
      ]
    };
    const view = renderCollaboration(current, current.experiment.comparison.contenders, current.experiment.trials);
    assert.match(view.textContent, /Studio Moser was preferred in Tim’s blinded comparison/);
    assert.match(view.textContent, /2 of 2 blinded choices/);
    assert.match(view.textContent, /Visible assistant tokens/);
    assert.match(view.textContent, /Would work again/);
    assert.match(view.textContent, /Studio Moser was least talkative at 90 visible assistant tokens per trial/);
    assert.match(view.textContent, /1 of 1 progress updates contained recognized new information/);
    assert.match(view.textContent, /communication was 20\.0% of billed model output tokens/);
    assert.match(view.textContent, /Compare conversation scenariosScenario.*Clear small edit/);
    assert.match(view.textContent, /Nothing kept talking/);
    const evidence = descendants(view).find(node => node.tag === "a" && node.textContent === "long final answer");
    assert.equal(new URL(evidence.href, "https://example.invalid").hash, `#${transcriptAnchor(current.experiment.trials[0], 3)}`);
  } finally { globalThis.document = previousDocument; }
});

test("dashboard isolates personality-only communication from the complete harness", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag)};
  try {
    const contenders = [
      {id: "nothing", family: "nothing", label: "Nothing"},
      {id: "personality", family: "studio-personality", label: "Studio personality only"},
      {id: "studio", family: "studio-moser", label: "Studio Moser Lite"}
    ];
    const trials = [
      collaborationTrial("nothing", {tokens: 220}),
      collaborationTrial("personality", {tokens: 80}),
      collaborationTrial("studio", {tokens: 110})
    ];
    const view = renderCollaboration({report_id: "comparison", experiment: {}}, contenders, trials);
    assert.match(view.textContent, /Personality-only used 80 visible assistant tokens per trial, compared with 220 for no instructions and 110 for Studio Moser/);
  } finally { globalThis.document = previousDocument; }
});

test("task evidence exposes the visible transcript and blind grader rationale at stable anchors", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag)};
  try {
    const current = typedReport();
    current.experiment.trials = [collaborationTrial("nothing")];
    current.experiment.trials[0].task_id = "quill-shared-toolbar-focus";
    const view = renderEvidence([current], {comparison: "typed"});
    assert.match(view.textContent, /User · 0\.0sFix the count/);
    assert.match(view.textContent, /Progress · 2\.0sI found the stale selector/);
    assert.match(view.textContent, /Would work together again: yes/);
    assert.match(view.textContent, /Directness · 4 \/ 5directness was observable/);
    const message = descendants(view).find(node => node.attributes?.id === transcriptAnchor(current.experiment.trials[0], 2));
    assert.ok(message);
  } finally { globalThis.document = previousDocument; }
});

test("task types show observed quality and efficiency with untested categories, never a category winner", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag)};
  try {
    const current = typedReport();
    const view = renderTaskTypes(current, current.experiment.trials);
    assert.match(view.textContent, /By task type/);
    assert.match(view.textContent, /PolishNot tested/);
    assert.match(view.textContent, /Small changesNot tested/);
    assert.match(view.textContent, /All harnesses passed the task tests/);
    assert.match(view.textContent, /Nothing: 1 confirmed/);
    assert.match(view.textContent, /Nothing had the lowest recorded execution cost/);
    assert.match(view.textContent, /protected-file verification is unknown/i);
    assert.match(view.textContent, /do not establish a winner/);
    const target = descendants(view).find(node => node.tag === "a" && node.textContent === "Nothing");
    const url = new URL(target.href, "https://example.invalid");
    assert.equal(url.searchParams.get("type"), "feature");
    assert.equal(url.searchParams.get("version"), "nothing");
    assert.equal(url.searchParams.get("comparison"), "typed");
    current.experiment.trials[0].code_review.protocol_id = "other";
    assert.match(renderTaskTypes(current, current.experiment.trials).textContent, /Review protocols differ/);
    current.experiment.trials.pop();
    const incomplete = renderTaskTypes(current, current.experiment.trials).textContent;
    assert.match(incomplete, /Trial evidence is incomplete or ambiguous/);
    assert.doesNotMatch(incomplete, /lowest recorded/);
  } finally { globalThis.document = previousDocument; }
});

test("type evidence filters preserve exact baselines and expose invalid or empty selections", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag)};
  try {
    const current = typedReport();
    current.experiment.conditions.task_ids.push("react-accent-polish");
    const baseline = structuredClone(current);
    baseline.report_id = "baseline";
    baseline.experiment.trials = [current.experiment.trials.pop()];
    const unrelated = structuredClone(baseline);
    unrelated.report_id = "unrelated";
    unrelated.experiment.trials[0].contender_id = "unrelated";
    current.experiment.baseline_result_ids = ["baseline"];
    const reports = [current, baseline, unrelated];
    const view = renderEvidence(reports, {comparison: "typed", type: "feature", version: "studio"});
    assert.match(view.textContent, /Studio Moser · trial 1/);
    assert.doesNotMatch(view.textContent, /Nothing · trial 1|react accent polish|unrelated · trial/);
    assert.match(renderEvidence(reports, {comparison: "typed", type: "grouped"}).textContent, /No tasks of this type/);
    assert.match(renderEvidence(reports, {comparison: "typed", type: "invalid"}).textContent, /That task type is unavailable/);
    assert.match(renderEvidence(reports, {comparison: "typed", type: "feature", task: "react-accent-polish"}).textContent, /That task is not part of this task type/);
  } finally { globalThis.document = previousDocument; }
});
