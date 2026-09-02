---
theme: dashboard
title: Run detail
toc: false
---

# Run detail

Public provenance, methodology, dimensions, and counters for one sanitized result.

```js
import {
  deliveryLabel,
  formatCost,
  formatScore,
  formatSeconds,
  formatTimestamp,
  resultLabel,
  totalRuntime,
  totalTokens
} from "./components/Results.js";

const report = FileAttachment("./data/Public_Results.json").json();
const results = report.results;
const byId = new Map(results.map((result) => [result.result_id, result]));
const selectedId = view(
  Inputs.select(results.length ? results.map((result) => result.result_id) : [null], {
    label: "Finalized result",
    format: (id) => id == null ? "No finalized results" : resultLabel(byId.get(id))
  })
);
const selected = selectedId == null ? null : byId.get(selectedId);
const efficiencyRows = Object.entries(selected?.efficiency ?? {}).map(([metric, value]) => ({
  metric: metric.replaceAll("_", " "),
  value: value == null ? "Unavailable" : value
}));
```

```js
selected
  ? html`<div class="grid grid-cols-4">
      <div class="card">
        <h2>Delivery</h2>
        <span class="big" style="font-size: 1.2rem;">${deliveryLabel(selected)}</span>
      </div>
      <div class="card">
        <h2>Task</h2>
        <span class="big" style="font-size: 1.2rem;">${selected.task.id}</span>
      </div>
      <div class="card">
        <h2>Finished (UTC)</h2>
        <span class="big" style="font-size: 1.2rem;">${formatTimestamp(selected.run.finished_at)}</span>
      </div>
      <div class="card">
        <h2>Release decision</h2>
        <span class="big">${selected.run.release_decision}</span>
      </div>
    </div>`
  : html`<div class="note">No finalized public result is available.</div>`
```

## Dimensions and totals

```js
selected
  ? Inputs.table([
      {
        correctness: formatScore(selected.dimensions.correctness),
        workflow: formatScore(selected.dimensions.workflow),
        efficiency_policy: formatScore(selected.dimensions.efficiency_policy),
        runtime: formatSeconds(totalRuntime(selected)),
        tokens: totalTokens(selected)?.toLocaleString("en-US") ?? "Unavailable",
        cost: formatCost(selected.efficiency.cost_usd),
        infrastructure: selected.infrastructure.status
      }
    ])
  : html`<div class="note">Unavailable</div>`
```

## Skill evaluation

```js
selected
  ? Inputs.table([
      {
        mode: selected.skill_evaluation.mode,
        skill: selected.skill_evaluation.name ?? "None",
        invocation: selected.skill_evaluation.invocation
      }
    ])
  : html`<div class="note">Unavailable</div>`
```

## Provenance and methodology

```js
selected
  ? Inputs.table([
      {
        result_id: selected.result_id,
        run_id: selected.run.id,
        trial_id: selected.run.trial_id,
        manifest: selected.run.manifest_digest,
        harness_commit: selected.run.harness_testing_commit,
        arm_bundle: selected.arm.bundle_digest,
        task_digest: selected.task.digest,
        dataset: selected.dataset.id,
        dataset_digest: selected.dataset.digest,
        environment_image: selected.provenance.environment_image_digest,
        scorer: selected.provenance.scorer_digest,
        classifier: selected.provenance.classifier_digest,
        methodology_schema: selected.provenance.methodology_schema,
        methodology_digest: selected.provenance.methodology_digest,
        compatibility: selected.compatibility.key
      }
    ])
  : html`<div class="note">Unavailable</div>`
```

## Efficiency counters

```js
efficiencyRows.length
  ? Inputs.table(efficiencyRows, {columns: ["metric", "value"]})
  : html`<div class="note">Unavailable</div>`
```

## Public source links

```js
selected
  ? html`<ul>${selected.source_links.map((link) => html`<li><a href=${link.url}>${link.label}</a>${link.digest == null ? "" : ` · ${link.digest}`}</li>`)}</ul>`
  : html`<div class="note">Unavailable</div>`
```
