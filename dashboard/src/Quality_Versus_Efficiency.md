---
theme: dashboard
title: Quality versus efficiency
toc: false
---

# Quality versus efficiency

All correct development-history observations remain in view. Runtime, tokens, observed API-equivalent cost, comparability, and evidence state stay separate; there is no composite ranking.

```js
import * as Plot from "@observablehq/plot";
import {
  evidenceLabel,
  formatObservedCost,
  observationTokens,
  runObservations,
  seriesLabel
} from "./components/Run_History.js";
import {formatScore, formatSeconds, formatTimestamp} from "./components/Results.js";

const report = await FileAttachment("./data/Public_Results.json").json();
const observations = runObservations(report.run_reports, report.results);
const correct = observations.filter((item) => item.dimensions.correctness === 1);
const plotted = correct.map((item) => ({
  ...item,
  tokens: observationTokens(item),
  evidence: evidenceLabel(item),
  comparison: item.comparability === "comparable" ? "Comparable" : "Diagnostic only"
})).filter((item) => item.runtimeSeconds != null && item.tokens != null);
```

```js
plotted.length
  ? resize((width) => Plot.plot({
      width,
      height: 460,
      marginLeft: 72,
      grid: true,
      x: {label: "Runtime (seconds)"},
      y: {label: "Prompt plus completion tokens"},
      color: {legend: true},
      symbol: {legend: true},
      marks: [
        Plot.dot(plotted, {
          x: "runtimeSeconds",
          y: "tokens",
          fill: "evidence",
          symbol: "comparison",
          opacity: (item) => item.reviewState === "reviewed" ? 1 : 0.7,
          r: 7,
          tip: true,
          title: (item) => `${item.task}\n${item.provider} ${item.arm}\n${item.comparison}\nEvidence: ${item.evidence}\nCost: ${formatObservedCost(item.observedCost)}`
        })
      ]
    }))
  : html`<div class="note">No correct observations with both runtime and token telemetry are available.</div>`
```

Symbol identifies comparable versus diagnostic-only evidence; color and tooltip text identify review state. Lower opacity marks evidence that has not been reviewed. These cues never turn a diagnostic point into a formal comparison.

## Correct-observation details

```js
correct.length
  ? Inputs.table(correct.map((item) => ({
      finished: formatTimestamp(item.finishedAt ?? item.runFinishedAt),
      run: item.runId,
      task: item.task,
      provider: item.provider,
      arm: item.arm,
      role: item.role,
      evidence: evidenceLabel(item),
      comparison: seriesLabel(item),
      workflow: formatScore(item.dimensions.workflow),
      efficiency_policy: formatScore(item.dimensions.efficiency_policy),
      runtime: formatSeconds(item.runtimeSeconds),
      tokens: observationTokens(item)?.toLocaleString("en-US") ?? "Unavailable",
      observed_cost: formatObservedCost(item.observedCost),
      comprehensive_tests: item.efficiency.comprehensive_tests ?? "Unavailable",
      premature_suites: item.efficiency.premature_comprehensive_tests ?? "Unavailable"
    })))
  : html`<div class="note">No correct public-safe observations are available.</div>`
```

Observed cost is API-equivalent telemetry. Incremental subscription spend is not captured.
