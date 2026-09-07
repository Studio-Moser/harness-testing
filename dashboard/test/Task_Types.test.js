import assert from "node:assert/strict";
import {readdir, readFile} from "node:fs/promises";
import {test} from "node:test";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";

import {TASK_TYPES, summarizeTaskTypes, taskType} from "../src/components/Task_Types.js";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

const usage = {
  input_tokens: 10,
  cache_read_tokens: 2,
  cache_write_tokens: 3,
  output_tokens: 5
};

function report({taskIds = ["react-accent-polish"], attempts = 1, contenders = [{id: "a", label: "A"}]} = {}) {
  return {
    experiment: {
      conditions: {task_ids: taskIds, attempts},
      comparison: {contenders}
    }
  };
}

function trial(overrides = {}) {
  return {
    task_id: "react-accent-polish",
    attempt: 1,
    contender_id: "a",
    status: "completed",
    correctness: true,
    usage_complete: true,
    cost_usd: 0.25,
    pricing_digest: "pricing-v1",
    duration_seconds: 12,
    model_usage: [usage],
    ...overrides
  };
}

function group(groups, id) {
  return groups.find((item) => item.id === id);
}

test("maps frozen workflow and Quill tasks to their declared types", () => {
  assert.deepEqual(TASK_TYPES.map(({id}) => id), ["polish", "small", "grouped", "feature"]);
  assert.equal(taskType("react-accent-polish"), "polish");
  assert.equal(taskType("react-active-badge-count"), "small");
  assert.equal(taskType("react-grouped-ui-updates"), "grouped");
  assert.equal(taskType("react-saved-view-feature"), "feature");
  assert.equal(taskType("rust-quoted-value-parser"), "small");
  assert.equal(taskType("rust-workspace-warning-summary"), "feature");
  assert.equal(taskType("static-accessible-disclosure"), "small");
  assert.equal(taskType("static-grouped-page-updates"), "grouped");
  assert.equal(taskType("static-pricing-copy-polish"), "polish");
  assert.equal(taskType("quill-shared-toolbar-focus"), "feature");
  assert.equal(taskType("outside-the-fixed-suite"), "unclassified");
});

test("matches every current workflow task.toml change_class", async () => {
  const workflowRoot = resolve(repositoryRoot, "tasks", "workflow");
  const entries = await readdir(workflowRoot, {withFileTypes: true});
  const workflowTasks = entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();

  for (const taskId of workflowTasks) {
    const contents = await readFile(resolve(workflowRoot, taskId, "task.toml"), "utf8");
    const changeClass = contents.match(/^change_class = "([^"]+)"$/m)?.[1];
    assert.ok(changeClass, `${taskId} must declare change_class`);
    assert.equal(taskType(taskId), changeClass, taskId);
  }
});

test("always includes known groups and places unknown scheduled tasks in unclassified", () => {
  const groups = summarizeTaskTypes(report({taskIds: ["react-accent-polish", "outside-the-fixed-suite"]}), [
    trial(),
    trial({task_id: "outside-the-fixed-suite"})
  ]);

  assert.deepEqual(groups.map(({id}) => id), ["polish", "small", "grouped", "feature", "unclassified"]);
  assert.deepEqual(group(groups, "polish").task_ids, ["react-accent-polish"]);
  assert.deepEqual(group(groups, "unclassified").task_ids, ["outside-the-fixed-suite"]);
  assert.equal(group(groups, "small").rows[0].scheduled, 0);
  assert.equal(group(groups, "small").rows[0].complete, true);
});

test("aggregates exact scheduled evidence and keeps contenders scoped to comparison rows", () => {
  const current = report({
    taskIds: ["react-accent-polish", "react-active-badge-count"],
    attempts: 2,
    contenders: [{id: "a", label: "Current A"}]
  });
  current.experiment.contenders = [{id: "ignored", label: "Ignored"}];
  const groups = summarizeTaskTypes(current, [
    trial({attempt: 1, cost_usd: 0.25, duration_seconds: 10}),
    trial({attempt: 2, cost_usd: 0.5, duration_seconds: 20}),
    trial({task_id: "react-active-badge-count", attempt: 1}),
    trial({task_id: "react-active-badge-count", attempt: 2, correctness: false}),
    trial({task_id: "react-accent-polish", attempt: 3}),
    trial({task_id: "outside-the-fixed-suite", attempt: 1}),
    trial({contender_id: "ignored"})
  ]);

  const polish = group(groups, "polish").rows[0];
  assert.equal(polish.id, "a");
  assert.equal(polish.scheduled, 2);
  assert.equal(polish.selected, 2);
  assert.equal(polish.passed, 2);
  assert.equal(polish.complete, true);
  assert.equal(polish.total_cost_usd, 0.75);
  assert.equal(polish.pricing_digest, "pricing-v1");
  assert.equal(polish.mean_duration_seconds, 15);
  assert.equal(polish.total_tokens, 40);
  assert.equal(polish.trials.length, 2);

  const small = group(groups, "small").rows[0];
  assert.equal(small.selected, 2);
  assert.equal(small.passed, 1);
  assert.equal(small.complete, true);
});

test("marks missing or duplicate slots incomplete without inflating passes or metrics", () => {
  const groups = summarizeTaskTypes(report({attempts: 2}), [
    trial({attempt: 1}),
    trial({attempt: 1, correctness: false, cost_usd: 99}),
    trial({attempt: 3, cost_usd: 99})
  ]);
  const row = group(groups, "polish").rows[0];

  assert.equal(row.scheduled, 2);
  assert.equal(row.selected, 1);
  assert.equal(row.passed, 0);
  assert.equal(row.complete, false);
  assert.equal(row.total_cost_usd, null);
  assert.equal(row.mean_duration_seconds, null);
  assert.equal(row.total_tokens, null);
  assert.equal(row.trials.length, 0);
});

test("leaves each metric unavailable when its required evidence is absent", () => {
  const groups = summarizeTaskTypes(report(), [
    trial({usage_complete: false, cost_usd: null, duration_seconds: null, model_usage: [{...usage, output_tokens: null}]})
  ]);
  const row = group(groups, "polish").rows[0];

  assert.equal(row.complete, true);
  assert.equal(row.total_cost_usd, null);
  assert.equal(row.mean_duration_seconds, null);
  assert.equal(row.total_tokens, null);
});

test("requires a matching recorded pricing identity for cost totals", () => {
  const mismatched = summarizeTaskTypes(report({attempts: 2}), [
    trial({attempt: 1, pricing_digest: "pricing-v1"}),
    trial({attempt: 2, pricing_digest: "pricing-v2"})
  ]);
  const missing = summarizeTaskTypes(report(), [trial({pricing_digest: null})]);

  assert.equal(group(mismatched, "polish").rows[0].complete, true);
  assert.equal(group(mismatched, "polish").rows[0].total_cost_usd, null);
  assert.equal(group(mismatched, "polish").rows[0].pricing_digest, null);
  assert.equal(group(missing, "polish").rows[0].total_cost_usd, null);
  assert.equal(group(missing, "polish").rows[0].pricing_digest, null);
});

test("does not classify inherited object properties as task types", () => {
  assert.equal(taskType("__proto__"), "unclassified");
  assert.equal(taskType("constructor"), "unclassified");
});


test("pending or infrastructure-only slots cannot look like complete measurements", () => {
  for (const status of ["pending", "cancelled", "infrastructure_failure", "task_definition_gap"]) {
    const row = group(summarizeTaskTypes(report(), [trial({status})]), "polish").rows[0];
    assert.equal(row.complete, false);
    assert.equal(row.total_cost_usd, null);
    assert.equal(row.mean_duration_seconds, null);
  }
  const duplicate = group(summarizeTaskTypes(report(), [trial(), trial()]), "polish").rows[0];
  assert.deepEqual(duplicate.trials, []);
});
