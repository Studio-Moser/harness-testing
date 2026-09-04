---
theme: dashboard
title: Trends
toc: false
---

# Compatible trends

Trend lines never cross compatibility keys unless a reviewed mapping explicitly joins them. Null telemetry is unavailable and is omitted from charts rather than rendered as zero.

```js
import * as Plot from "@observablehq/plot";
import {totalRuntime, totalTokens} from "./components/Results.js";

const report = FileAttachment("./data/Public_Results.json").json();
const results = report.results;
const keys = report.compatibility_series.map((series) => series.key);
const selectedKey = view(
  Inputs.select(keys.length ? keys : [null], {
    label: "Compatibility series",
    format: (key) => key == null ? "No compatible series" : `${key.slice(0, 20)}…`
  })
);
const series = selectedKey == null
  ? []
  : results.filter((result) => result.compatibility.key === selectedKey);
const quality = series.flatMap((result) => [
  {
    date: new Date(result.run.finished_at),
    metric: "Correctness",
    value: result.dimensions.correctness,
    run: result.result_id
  },
  {
    date: new Date(result.run.finished_at),
    metric: "Workflow violations",
    value: result.dimensions.workflow == null ? null : 1 - result.dimensions.workflow,
    run: result.result_id
  }
]).filter((point) => point.value != null);
const runtime = series.map((result) => ({
  date: new Date(result.run.finished_at),
  value: totalRuntime(result),
  provider: result.provider.agent,
  run: result.result_id
})).filter((point) => point.value != null);
const tokens = series.map((result) => ({
  date: new Date(result.run.finished_at),
  value: totalTokens(result),
  provider: result.provider.agent,
  run: result.result_id
})).filter((point) => point.value != null);
const cost = series.map((result) => ({
  date: new Date(result.run.finished_at),
  value: result.efficiency.cost_usd,
  provider: result.provider.agent,
  run: result.result_id
})).filter((point) => point.value != null);
const churn = series.flatMap((result) => [
  {
    date: new Date(result.run.finished_at),
    metric: "Comprehensive tests",
    value: result.efficiency.comprehensive_tests,
    run: result.result_id
  },
  {
    date: new Date(result.run.finished_at),
    metric: "Premature comprehensive tests",
    value: result.efficiency.premature_comprehensive_tests,
    run: result.result_id
  }
]).filter((point) => point.value != null);
const discovery = results
  .filter((result) => result.skill_evaluation.mode === "discovery")
  .map((result) => ({
    date: new Date(result.run.finished_at),
    value: result.skill_evaluation.invocation === "implicit" ? 1 : 0,
    provider: result.provider.agent,
    skill: result.skill_evaluation.name,
    run: result.result_id
  }));
const discoveryObserved = discovery.reduce((total, point) => total + point.value, 0);
```

```js
series.length
  ? html`<div class="note">${series.length} finalized result${series.length === 1 ? "" : "s"} in this compatibility series.</div>`
  : html`<div class="note">No finalized results are available for this series.</div>`
```

<div class="grid grid-cols-2">
  <div class="card">${resize((width) => Plot.plot({
    title: "Correctness and workflow violations",
    width,
    height: 300,
    y: {domain: [0, 1], grid: true},
    color: {legend: true},
    marks: [
      Plot.ruleY([0]),
      Plot.lineY(quality, {x: "date", y: "value", stroke: "metric"}),
      Plot.dot(quality, {x: "date", y: "value", stroke: "metric", tip: true})
    ]
  }))}</div>
  <div class="card">${resize((width) => Plot.plot({
    title: "Total runtime",
    width,
    height: 300,
    y: {grid: true, label: "Seconds"},
    color: {legend: true},
    marks: [
      Plot.ruleY([0]),
      Plot.lineY(runtime, {x: "date", y: "value", stroke: "provider"}),
      Plot.dot(runtime, {x: "date", y: "value", stroke: "provider", tip: true})
    ]
  }))}</div>
  <div class="card">${resize((width) => Plot.plot({
    title: "Prompt plus completion tokens",
    width,
    height: 300,
    y: {grid: true, label: "Tokens"},
    color: {legend: true},
    marks: [
      Plot.ruleY([0]),
      Plot.lineY(tokens, {x: "date", y: "value", stroke: "provider"}),
      Plot.dot(tokens, {x: "date", y: "value", stroke: "provider", tip: true})
    ]
  }))}</div>
  <div class="card">${resize((width) => Plot.plot({
    title: "Recorded cost",
    width,
    height: 300,
    y: {grid: true, label: "USD"},
    color: {legend: true},
    marks: [
      Plot.ruleY([0]),
      Plot.lineY(cost, {x: "date", y: "value", stroke: "provider"}),
      Plot.dot(cost, {x: "date", y: "value", stroke: "provider", tip: true})
    ]
  }))}</div>
</div>

<div class="card">${resize((width) => Plot.plot({
  title: "Testing churn",
  width,
  height: 320,
  y: {grid: true, label: "Invocations"},
  color: {legend: true},
  marks: [
    Plot.ruleY([0]),
    Plot.lineY(churn, {x: "date", y: "value", stroke: "metric"}),
    Plot.dot(churn, {x: "date", y: "value", stroke: "metric", tip: true})
  ]
}))}</div>

## Skill discovery

```js
discovery.length
  ? html`<div class="note">Observed ${discoveryObserved} of ${discovery.length} automatic skill selections (${(discoveryObserved / discovery.length * 100).toFixed(1)}%). Discovery is diagnostic and has no pass threshold.</div>`
  : html`<div class="note">No finalized discovery observations are available.</div>`
```

<div class="card">${resize((width) => Plot.plot({
  title: "Automatic skill selection",
  width,
  height: 300,
  y: {domain: [0, 1], ticks: [0, 1], label: "Observed"},
  color: {legend: true},
  marks: [
    Plot.ruleY([0, 1]),
    Plot.dot(discovery, {
      x: "date",
      y: "value",
      fill: "provider",
      tip: true,
      title: (point) => `${point.provider}\n${point.skill}\n${point.value ? "Observed" : "Not observed"}`
    })
  ]
}))}</div>
