---
theme: dashboard
title: Trends
toc: false
---

# Development trends

Every public-safe observation is shown. Lines connect only observations with the same non-null compatibility series; point labels carry the evidence state so color is never the only cue.

```js
import * as Plot from "@observablehq/plot";
import {
  evidenceLabel,
  observationTokens,
  runObservations
} from "./components/Run_History.js";

const report = await FileAttachment("./data/Public_Results.json").json();
const observations = runObservations(report.run_reports, report.results);
const all = "All";
const filterValues = (values) => [
  all,
  ...[...new Set(values.map((value) => value ?? "Unavailable"))]
    .filter((value) => value !== all)
    .sort()
];
```

```js
const selectedProvider = view(Inputs.select(filterValues(observations.map((item) => item.provider)), {label: "Provider"}));
```

```js
const selectedArm = view(Inputs.select(filterValues(observations.map((item) => item.arm)), {label: "Arm"}));
```

```js
const selectedTask = view(Inputs.select(filterValues(observations.map((item) => item.task)), {label: "Task"}));
```

```js
const selectedProfile = view(Inputs.select(filterValues(observations.map((item) => item.profile)), {label: "Profile"}));
```

```js
const selectedMethodology = view(Inputs.select(filterValues(observations.map((item) => item.methodology)), {label: "Methodology"}));
```

```js
const selectedReview = view(Inputs.select(filterValues(observations.map((item) => item.reviewState)), {label: "Review state"}));
```

```js
const filteredObservations = observations.filter((item) =>
  (selectedProvider === all || (item.provider ?? "Unavailable") === selectedProvider) &&
  (selectedArm === all || (item.arm ?? "Unavailable") === selectedArm) &&
  (selectedTask === all || (item.task ?? "Unavailable") === selectedTask) &&
  (selectedProfile === all || (item.profile ?? "Unavailable") === selectedProfile) &&
  (selectedMethodology === all || (item.methodology ?? "Unavailable") === selectedMethodology) &&
  (selectedReview === all || (item.reviewState ?? "Unavailable") === selectedReview)
);
const dated = filteredObservations.map((item) => ({
  ...item,
  date: new Date(item.finishedAt ?? item.runFinishedAt ?? item.startedAt),
  evidence: evidenceLabel(item)
}));
const quality = dated.flatMap((item) => [
  {item, date: item.date, metric: "Correctness", value: item.dimensions.correctness},
  {item, date: item.date, metric: "Workflow", value: item.dimensions.workflow},
  {item, date: item.date, metric: "Efficiency policy", value: item.dimensions.efficiency_policy}
]).filter((point) => point.value != null).map((point) => ({
  ...point,
  provider: point.item.provider,
  arm: point.item.arm,
  task: point.item.task,
  evidence: point.item.evidence,
  seriesKey: point.item.seriesKey,
  lineGroup: point.item.seriesKey == null ? null : `${point.item.seriesKey}\0${point.metric}`
}));
const qualityLines = quality.filter((point) => point.lineGroup != null);
const telemetry = dated.map((item) => ({
  ...item,
  tokens: observationTokens(item)
}));
const runtime = telemetry.filter((item) => item.runtimeSeconds != null);
const tokens = telemetry.filter((item) => item.tokens != null);
const cost = telemetry.filter((item) => item.observedCost != null);
const churn = telemetry.flatMap((item) => [
  {item, date: item.date, metric: "Comprehensive tests", value: item.efficiency.comprehensive_tests},
  {item, date: item.date, metric: "Premature comprehensive tests", value: item.efficiency.premature_comprehensive_tests}
]).filter((point) => point.value != null).map((point) => ({
  ...point,
  evidence: point.item.evidence,
  lineGroup: point.item.seriesKey == null ? null : `${point.item.seriesKey}\0${point.metric}`
}));
const discovery = telemetry.filter((item) => item.skillEvaluation?.mode === "discovery").map((item) => ({
  ...item,
  value: item.skillEvaluation.invocation === "implicit" ? 1 : 0,
  skill: item.skillEvaluation.name
}));
```

```js
observations.length
  ? html`<div class="note">Showing ${filteredObservations.length.toLocaleString("en-US")} of ${observations.length.toLocaleString("en-US")} job observations. Points without a defensible series remain visible but are never joined by a line.</div>`
  : html`<div class="note">No public-safe run reports have been published.</div>`
```

<div class="grid grid-cols-2">
  <div class="card">${resize((width) => Plot.plot({
    title: "Quality dimensions",
    width,
    height: 330,
    y: {domain: [0, 1], grid: true, label: "Score"},
    color: {legend: true},
    symbol: {legend: true},
    marks: [
      Plot.ruleY([0, 1]),
      Plot.lineY(qualityLines, {x: "date", y: "value", z: "lineGroup", stroke: "metric", opacity: 0.35}),
      Plot.dot(quality, {
        x: "date",
        y: "value",
        fill: "evidence",
        symbol: "metric",
        r: 5,
        tip: true,
        title: (point) => `${point.task}\n${point.provider} ${point.arm}\n${point.metric}: ${point.value}\nEvidence: ${point.evidence}`
      })
    ]
  }))}</div>
  <div class="card">${resize((width) => Plot.plot({
    title: "Runtime",
    width,
    height: 330,
    y: {grid: true, label: "Seconds"},
    color: {legend: true},
    marks: [
      Plot.ruleY([0]),
      Plot.lineY(runtime.filter((item) => item.seriesKey != null), {x: "date", y: "runtimeSeconds", z: "seriesKey", stroke: "provider", opacity: 0.35}),
      Plot.dot(runtime, {x: "date", y: "runtimeSeconds", fill: "evidence", r: 5, tip: true, title: (item) => `${item.task}\n${item.provider} ${item.arm}\n${item.runtimeSeconds} seconds\nEvidence: ${item.evidence}`})
    ]
  }))}</div>
  <div class="card">${resize((width) => Plot.plot({
    title: "Prompt plus completion tokens",
    width,
    height: 330,
    y: {grid: true, label: "Tokens"},
    color: {legend: true},
    marks: [
      Plot.ruleY([0]),
      Plot.lineY(tokens.filter((item) => item.seriesKey != null), {x: "date", y: "tokens", z: "seriesKey", stroke: "provider", opacity: 0.35}),
      Plot.dot(tokens, {x: "date", y: "tokens", fill: "evidence", r: 5, tip: true, title: (item) => `${item.task}\n${item.provider} ${item.arm}\n${item.tokens.toLocaleString("en-US")} tokens\nEvidence: ${item.evidence}`})
    ]
  }))}</div>
  <div class="card">${resize((width) => Plot.plot({
    title: "Observed API-equivalent cost",
    width,
    height: 330,
    y: {grid: true, label: "USD"},
    color: {legend: true},
    marks: [
      Plot.ruleY([0]),
      Plot.lineY(cost.filter((item) => item.seriesKey != null), {x: "date", y: "observedCost", z: "seriesKey", stroke: "provider", opacity: 0.35}),
      Plot.dot(cost, {x: "date", y: "observedCost", fill: "evidence", r: 5, tip: true, title: (item) => `${item.task}\n${item.provider} ${item.arm}\n$${item.observedCost.toFixed(4)} API-equivalent\nEvidence: ${item.evidence}`})
    ]
  }))}</div>
</div>

Observed API-equivalent cost is telemetry, not incremental subscription spend. Unavailable measurements are omitted from their chart, never rendered as zero.

## Testing churn

```js
churn.length
  ? resize((width) => Plot.plot({
      width,
      height: 320,
      y: {grid: true, label: "Invocations"},
      color: {legend: true},
      marks: [
        Plot.ruleY([0]),
        Plot.lineY(churn.filter((point) => point.lineGroup != null), {x: "date", y: "value", z: "lineGroup", stroke: "metric", opacity: 0.35}),
        Plot.dot(churn, {x: "date", y: "value", fill: "evidence", r: 5, tip: true, title: (point) => `${point.item.task}\n${point.metric}: ${point.value}\nEvidence: ${point.evidence}`})
      ]
    }))
  : html`<div class="note">Testing-invocation counters are unavailable in the selected run reports. They appear when linked decision-grade evidence supplies them.</div>`
```

## Skill discovery

```js
discovery.length
  ? resize((width) => Plot.plot({
      width,
      height: 300,
      y: {domain: [0, 1], ticks: [0, 1], label: "Observed"},
      color: {legend: true},
      marks: [
        Plot.ruleY([0, 1]),
        Plot.dot(discovery, {x: "date", y: "value", fill: "evidence", r: 6, tip: true, title: (item) => `${item.provider}\n${item.skill}\n${item.value ? "Observed" : "Not observed"}\nEvidence: ${item.evidence}`})
      ]
    }))
  : html`<div class="note">Skill-discovery observations are unavailable for the selected history.</div>`
```
