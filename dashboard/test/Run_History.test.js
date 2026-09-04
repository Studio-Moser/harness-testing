import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {test} from "node:test";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";

import {
  coverageState,
  coverageStates,
  pairedArmComparisons,
  runObservations,
  seriesDeltas
} from "../src/components/Run_History.js";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

async function fixture(path) {
  return JSON.parse(await readFile(resolve(repositoryRoot, path), "utf8"));
}

function observation(overrides = {}) {
  return {
    observationId: "run-a\0job-a",
    runId: "run-a",
    provider: "codex",
    arm: "A0",
    task: "react-saved-view-feature",
    finishedAt: "2026-09-01T00:00:00Z",
    seriesKey: `sha256:${"1".repeat(64)}`,
    dimensions: {correctness: 0.5, workflow: 1, efficiency_policy: 1},
    runtimeSeconds: 20,
    promptTokens: 100,
    completionTokens: 20,
    observedCost: 0.02,
    ...overrides
  };
}

test("normalizes every run job without double-counting finalized evidence", async () => {
  const report = await fixture("tests/Fixtures/Run_Reports/Valid.json");
  const baseline = structuredClone(report.jobs[0]);
  baseline.name = baseline.name.replace("-A2-", "-A0-");
  baseline.arm = "A0";
  baseline.role = "baseline";
  report.jobs.unshift(baseline);
  report.expected_jobs = 2;
  report.completed_jobs = 2;
  report.expected_trials = 2;
  report.completed_trials = 2;

  const finalized = await fixture("tests/Fixtures/Public_Results/Valid.json");
  finalized.run.manifest_digest = report.manifest_digest;
  finalized.run.release_decision = "pass";
  finalized.review.partial = false;
  finalized.review.quarantined = false;
  finalized.provider.agent = "codex";
  finalized.arm.id = "A2";
  finalized.arm.role = "candidate";
  finalized.task.id = report.jobs[1].task;

  const observations = runObservations([report], [finalized]);

  assert.equal(observations.length, report.jobs.length);
  assert.equal(observations[0].reviewState, "unreviewed");
  assert.equal(observations[1].reviewState, "reviewed");
  assert.equal(observations[1].releaseDecision, "pass");
  assert.equal(observations[1].resultId, finalized.result_id);
});

test("only computes deltas inside one non-null series", () => {
  const first = observation();
  const second = observation({
    observationId: "run-b\0job-b",
    runId: "run-b",
    finishedAt: "2026-09-02T00:00:00Z",
    dimensions: {correctness: 1, workflow: 1, efficiency_policy: 0.5},
    runtimeSeconds: 15
  });

  assert.equal(seriesDeltas([first, {...second, seriesKey: null}]).length, 0);
  assert.equal(
    seriesDeltas([first, {...second, seriesKey: `sha256:${"2".repeat(64)}`}]).length,
    0
  );

  const deltas = seriesDeltas([first, second]);
  assert.equal(deltas.length, 1);
  assert.equal(deltas[0].earlier.observationId, first.observationId);
  assert.equal(deltas[0].later.observationId, second.observationId);
  assert.equal(deltas[0].runtimeSeconds, -5);
});

test("pairs A0 and A2 only within the same run provider and task", () => {
  const baseline = observation();
  const candidate = observation({
    observationId: "run-a\0job-b",
    arm: "A2",
    dimensions: {correctness: 1, workflow: 0.5, efficiency_policy: 1}
  });
  const otherRun = observation({
    observationId: "run-b\0job-c",
    runId: "run-b",
    arm: "A2"
  });
  const otherProvider = observation({
    observationId: "run-a\0job-d",
    provider: "claude",
    arm: "A2"
  });
  const otherTask = observation({
    observationId: "run-a\0job-e",
    arm: "A2",
    task: "rust-cli-feature"
  });

  const pairs = pairedArmComparisons([
    baseline,
    candidate,
    otherRun,
    otherProvider,
    otherTask
  ]);

  assert.equal(pairs.length, 1);
  assert.equal(pairs[0].baseline.observationId, baseline.observationId);
  assert.equal(pairs[0].candidate.observationId, candidate.observationId);
});

test("counts partial and failed run coverage as overlapping states", () => {
  const run = {
    status: "failed",
    evidence: {limitations: ["partial-run", "failed-run"]}
  };

  assert.deepEqual(coverageStates(run), ["partial", "failed"]);
  assert.equal(coverageState(run), "failed");
});
