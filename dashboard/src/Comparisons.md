---
theme: dashboard
title: Comparisons
toc: false
---

# Baseline versus candidate

A0 and A2 are paired only inside the same run, provider, and task. Cross-run changes appear separately and only when both observations share one non-null compatibility series.

```js
import * as Plot from "@observablehq/plot";
import {
  evidenceLabel,
  pairedArmComparisons,
  runObservations,
  seriesDeltas
} from "./components/Run_History.js";
import {formatScore, formatSeconds, formatTimestamp} from "./components/Results.js";

const report = await FileAttachment("./data/Public_Results.json").json();
const observations = runObservations(report.run_reports, report.results);
const pairs = pairedArmComparisons(observations);
const deltas = seriesDeltas(observations);
const signedPercent = (value) => value == null ? "Unavailable" : `${value >= 0 ? "+" : ""}${Math.round(value * 100)} pp`;
const signedNumber = (value, suffix = "") => value == null ? "Unavailable" : `${value >= 0 ? "+" : ""}${value.toLocaleString("en-US", {maximumFractionDigits: 2})}${suffix}`;
const pairScores = pairs.flatMap((pair) => [pair.baseline, pair.candidate]).flatMap((item) => [
  {item, dimension: "Correctness", value: item.dimensions.correctness},
  {item, dimension: "Workflow", value: item.dimensions.workflow},
  {item, dimension: "Efficiency policy", value: item.dimensions.efficiency_policy}
]).filter((point) => point.value != null).map((point) => ({
  ...point,
  provider: point.item.provider,
  arm: point.item.arm,
  task: point.item.task,
  evidence: evidenceLabel(point.item)
}));
```

## Within-run A0/A2 pairs

```js
pairs.length
  ? Inputs.table(pairs.map((pair) => ({
      run: pair.runId,
      provider: pair.provider,
      task: pair.task,
      basis: pair.baseline.comparability === "diagnostic-only" || pair.candidate.comparability === "diagnostic-only" ? "Diagnostic only" : "Comparable within run",
      evidence: `${evidenceLabel(pair.baseline)} / ${evidenceLabel(pair.candidate)}`,
      baseline_correctness: formatScore(pair.baseline.dimensions.correctness),
      candidate_correctness: formatScore(pair.candidate.dimensions.correctness),
      correctness_delta: signedPercent(pair.correctness),
      workflow_delta: signedPercent(pair.workflow),
      efficiency_policy_delta: signedPercent(pair.efficiencyPolicy),
      runtime_delta: signedNumber(pair.runtimeSeconds, " s"),
      token_delta: signedNumber(pair.tokens),
      observed_cost_delta: pair.observedCost == null ? "Unavailable" : `${pair.observedCost >= 0 ? "+" : "-"}$${Math.abs(pair.observedCost).toFixed(4)} API-equivalent`
    })))
  : html`<div class="note">No run contains a complete A0/A2 pair for the same provider and task.</div>`
```

```js
pairScores.length
  ? resize((width) => Plot.plot({
      width,
      height: 360,
      x: {label: "Arm"},
      y: {domain: [0, 1], grid: true, label: "Score"},
      color: {legend: true},
      symbol: {legend: true},
      marks: [
        Plot.ruleY([0, 1]),
        Plot.dot(pairScores, {x: "arm", y: "value", fill: "evidence", symbol: "dimension", r: 6, tip: true, title: (point) => `${point.task}\n${point.provider} ${point.arm}\n${point.dimension}: ${point.value}\nEvidence: ${point.evidence}`})
      ]
    }))
  : html`<div></div>`
```

Within-run pairing is descriptive. A row marked “Diagnostic only” is not a compatibility claim.

## Equal-series cross-run changes

```js
deltas.length
  ? Inputs.table(deltas.map((delta) => ({
      provider: delta.later.provider,
      arm: delta.later.arm,
      task: delta.later.task,
      earlier_run: delta.earlier.runId,
      later_run: delta.later.runId,
      earlier_finish: formatTimestamp(delta.earlier.finishedAt ?? delta.earlier.runFinishedAt),
      later_finish: formatTimestamp(delta.later.finishedAt ?? delta.later.runFinishedAt),
      evidence: `${evidenceLabel(delta.earlier)} → ${evidenceLabel(delta.later)}`,
      correctness_delta: signedPercent(delta.correctness),
      workflow_delta: signedPercent(delta.workflow),
      efficiency_policy_delta: signedPercent(delta.efficiencyPolicy),
      runtime_delta: signedNumber(delta.runtimeSeconds, " s"),
      token_delta: signedNumber(delta.tokens),
      observed_cost_delta: delta.observedCost == null ? "Unavailable" : `${delta.observedCost >= 0 ? "+" : "-"}$${Math.abs(delta.observedCost).toFixed(4)} API-equivalent`,
      series: `${delta.seriesKey.slice(0, 18)}…`
    })))
  : html`<div class="note">No two runs currently share a non-null compatibility series. Cross-run deltas are unavailable; the history remains visible elsewhere without a false comparison.</div>`
```

Observed cost deltas compare API-equivalent telemetry only. They do not measure incremental subscription spend. Current observed values remain available on the [latest run](./) and <a href="./Task_Matrix.html">task matrix</a> views.
