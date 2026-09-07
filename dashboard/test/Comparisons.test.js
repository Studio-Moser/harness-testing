import assert from "node:assert/strict";
import test from "node:test";
import {codeReviewCountLabel, codeReviewCoverageLabel, comparisonReports, comparisonVerdict, internalReviewCoverageLabel, renderComparison, renderEvidence, renderHistory, selectComparison, comparisonUrl, summarizeCodeReview, summarizeInternalReview, summarizeTests, versionHistory, sortNumericRows, trialLabel} from "../src/components/Comparisons.js";

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
  assert.equal(trialLabel({status:"completed", correctness:true, protected_state:false}), "Protected files changed");
  assert.equal(trialLabel({status:"completed", correctness:true, protected_state:null}), "Tests passed · protected state unknown");
  assert.equal(trialLabel({status:"timeout", correctness:true, protected_state:true}), "timeout");
  assert.equal(trialLabel({status:"completed", correctness:null, protected_state:null}), "Ungraded");
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
