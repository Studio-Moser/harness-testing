import assert from "node:assert/strict";
import test from "node:test";

import {HARNESS_CATALOG} from "../src/data/Harness Catalog.js";
import {TOOLBOX_CATALOG} from "../src/data/Toolbox Catalog.js";
import {
  admitResults,
  aggregateHarnesses,
  defaultModel,
  harnessArm,
  normalizeResults,
  renderResults
} from "../src/components/Results.js";

class FakeElement {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.className = "";
    this.listeners = {};
    this.value = "";
    this._text = "";
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent ?? String(child)).join("");
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this._text = ""; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, listener) { this.listeners[name] = listener; }
}

function descendants(node) {
  return [node, ...node.children.flatMap((child) => child instanceof FakeElement ? descendants(child) : [])];
}

function report(runId, jobs, overrides = {}) {
  return {
    schema_version: "3",
    run_id: runId,
    updated_at: "2026-09-15T12:00:00Z",
    finished_at: "2026-09-15T12:00:00Z",
    status: "completed",
    source: {kind: "current", label: null},
    evidence: {review_state: "unreviewed", limitations: []},
    jobs,
    ...overrides
  };
}

function gradedExperiment(harnesses, task, scores) {
  return {
    contenders: harnesses.map((harness) => ({id: harness.identity})),
    trials: harnesses.map((harness, index) => ({
      task_id: task,
      contender_id: harness.identity,
      interaction_count: 4,
      collaboration: {
        status: "complete",
        metrics: {
          unnecessary_question_count: 0,
          unnecessary_approval_request_count: 0,
          slop_phrase_count: 0
        },
        grade: {
          status: "completed",
          dimensions: [
            {name: "directness", score: scores[index]},
            {name: "autonomy", score: scores[index]}
          ]
        }
      }
    }))
  };
}

function job(arm, task, correctness, overrides = {}) {
  return {
    arm,
    task,
    model: "gpt-5.6-sol",
    effort: "medium",
    status: "completed",
    dimensions: {correctness, workflow: 1, efficiency_policy: 1},
    runtime_seconds: 60,
    efficiency: {
      prompt_tokens: 100,
      cached_tokens: 20,
      completion_tokens: 25,
      api_equivalent_cost_usd: 0.01
    },
    comparability: "comparable",
    completed_trials: 1,
    ...overrides
  };
}

test("normalizes only current published observations that map to catalog tests and harness versions", () => {
  const nothing = HARNESS_CATALOG.find(({id}) => id === "nothing-v1");
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v4");
  const reports = [
    report("run-current", [
      job(harnessArm(nothing), "react-active-badge-count", 0),
      job(harnessArm(studio), "react-active-badge-count", 1),
      job("Vunknown", "react-active-badge-count", 1),
      job(harnessArm(studio), "not-in-toolbox", 1)
    ]),
    report("run-old", [job(harnessArm(studio), "react-active-badge-count", 1)], {schema_version: "2"})
  ];

  const observations = normalizeResults(reports, TOOLBOX_CATALOG, HARNESS_CATALOG);

  assert.equal(observations.length, 2);
  assert.deepEqual(observations.map(({harnessId}) => harnessId), ["nothing-v1", "studio-moser-v4"]);
  assert.equal(observations[1].type, "bug-fix");
  assert.equal(observations[1].level, 2);
  assert.equal(observations[1].tokens, 125);
});

test("leaderboard aggregates by test and computes deltas only from paired runs", () => {
  const nothing = HARNESS_CATALOG.find(({id}) => id === "nothing-v1");
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v4");
  const observations = normalizeResults([
    report("run-paired", [
      job(harnessArm(nothing), "react-active-badge-count", 0),
      job(harnessArm(studio), "react-active-badge-count", 1)
    ]),
    report("run-unpaired", [
      job(harnessArm(studio), "react-accent-polish", 0)
    ])
  ], TOOLBOX_CATALOG, HARNESS_CATALOG);

  const rows = aggregateHarnesses(observations, [nothing, studio]);
  const studioRow = rows.find(({id}) => id === "studio-moser-v4");

  assert.equal(defaultModel(observations), "gpt-5.6-sol\0medium");
  assert.equal(studioRow.correctness, 1);
  assert.equal(studioRow.coveredTests, 2);
  assert.equal(studioRow.sharedTests, 1);
  assert.equal(studioRow.deltaFromNothing, 1);
  assert.equal(studioRow.deltaFromPredecessor, null);
});

test("quality comes only from completed blinded collaboration grades", () => {
  const nothing = HARNESS_CATALOG.find(({id}) => id === "nothing-v1");
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v4");
  const observations = normalizeResults([
    report("run-graded", [
      job(harnessArm(nothing), "react-active-badge-count", 1),
      job(harnessArm(studio), "react-active-badge-count", 1)
    ], {experiment: gradedExperiment([nothing, studio], "react-active-badge-count", [3, 5])}),
    report("run-ungraded", [
      job(harnessArm(studio), "react-accent-polish", 1)
    ])
  ], TOOLBOX_CATALOG, HARNESS_CATALOG);

  assert.equal(observations.find(({harnessId}) => harnessId === "nothing-v1").quality, 0.6);
  assert.equal(observations.find(({harnessId, taskId}) => harnessId === "studio-moser-v4" && taskId === "react-active-badge-count").quality, 1);
  assert.equal(observations.find(({taskId}) => taskId === "react-accent-polish").quality, null);

  const studioRow = aggregateHarnesses(observations, [nothing, studio])
    .find(({id}) => id === "studio-moser-v4");
  assert.equal(studioRow.quality, 1);
  assert.equal(studioRow.qualityObservations, 1);
});

test("scoring excludes incomplete evidence and never coerces null paired scores", () => {
  const nothing = HARNESS_CATALOG.find(({id}) => id === "nothing-v1");
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v4");
  const observations = normalizeResults([
    report("run-pending", [
      job(harnessArm(nothing), "react-active-badge-count", null, {status: "pending"}),
      job(harnessArm(studio), "react-active-badge-count", 1)
    ]),
    report("run-complete", [
      job(harnessArm(nothing), "react-active-badge-count", 0),
      job(harnessArm(studio), "react-active-badge-count", 1)
    ])
  ], TOOLBOX_CATALOG, HARNESS_CATALOG);

  assert.equal(admitResults(observations).length, 3);
  const studioRow = aggregateHarnesses(observations, HARNESS_CATALOG)
    .find(({id}) => id === "studio-moser-v4");
  assert.equal(studioRow.deltaFromNothing, 1);
});

test("Results page renders benchmark controls, leaderboard, matrix, and efficiency view", () => {
  const nothing = HARNESS_CATALOG.find(({id}) => id === "nothing-v1");
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v4");
  const reports = [report("run-paired", [
    job(harnessArm(nothing), "react-active-badge-count", 0),
    job(harnessArm(studio), "react-active-badge-count", 1),
    job(harnessArm(studio), "react-active-badge-count", null, {name: "pending", status: "pending"})
  ], {experiment: gradedExperiment([nothing, studio], "react-active-badge-count", [3, 5])})];
  const previousDocument = globalThis.document;
  globalThis.document = {
    createElement: (tag) => new FakeElement(tag),
    createElementNS: (namespace, tag) => new FakeElement(tag)
  };
  try {
    const root = renderResults({tests: TOOLBOX_CATALOG, harnesses: HARNESS_CATALOG, reports});
    assert.equal(root.attributes["aria-label"], "Harness results");
    assert.match(root.textContent, /Results/);
    assert.match(root.textContent, /Harness leaderboard/);
    assert.match(root.textContent, /Test coverage/);
    assert.match(root.textContent, /Quality trade-offs/);
    assert.match(root.textContent, /Quality vs runtime/);
    assert.match(root.textContent, /Quality vs tokens/);
    assert.match(root.textContent, /Quality vs cost/);
    assert.match(root.textContent, /blinded collaboration grades/);
    assert.match(root.textContent, /not yet included in Quality/);
    assert.match(root.textContent, /Studio Moser v4/);
    assert.match(root.textContent, /React active badge count/);
    assert.match(root.textContent, /Current methodology only/);
    assert.match(root.textContent, /admitted comparable observations/);
    assert.match(root.textContent, /shared task cohort/);
    assert.match(root.textContent, /2 harnesses ranked by correctness, then Quality, on 1 shared test/);
    assert.match(root.textContent, /1 pending/);
    assert.doesNotMatch(root.textContent, /recommend/i);

    const nodes = descendants(root);
    const modelSelect = nodes.find((node) => node.tag === "select");
    assert.match(modelSelect.className, /form-select/);
    assert.equal(nodes.filter((node) => node.className === "results-chart-legend").length, 1);
    assert.equal(nodes.filter((node) => node.className === "results-chart-leader").length, 0);
    assert.ok(root.textContent.indexOf("Quality trade-offs") < root.textContent.indexOf("Test coverage"));

    const bugFixes = nodes.find((node) => node.tag === "button" && node.textContent === "Bug fixes");
    bugFixes.listeners.click();
    assert.match(root.textContent, /React active badge count/);
    assert.doesNotMatch(root.textContent, /React accent polish/);
  } finally {
    globalThis.document = previousDocument;
  }
});
