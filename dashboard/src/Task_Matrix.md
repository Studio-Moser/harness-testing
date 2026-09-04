---
theme: dashboard
title: Task matrix
toc: false
---

# Task matrix

Every reported job is retained, including failed jobs and jobs whose scores or telemetry are unavailable. Evidence and compatibility labels travel with the values.

```js
import {
  evidenceLabel,
  formatObservedCost,
  observationTokens,
  runObservations,
  seriesLabel
} from "./components/Run_History.js";
import {formatCount, formatScore, formatSeconds, formatTimestamp} from "./components/Results.js";

const report = await FileAttachment("./data/Public_Results.json").json();
const observations = runObservations(report.run_reports, report.results);
const cellState = (item) => {
  if (item.jobStatus === "failed") return "Failed";
  if (new Set(["pending", "running", "incomplete"]).has(item.jobStatus)) return "Missing result";
  return Object.values(item.dimensions).every((value) => value == null) ? "Scores unavailable" : "Reported";
};
const rows = observations.map((item) => ({
  finished: formatTimestamp(item.finishedAt ?? item.runFinishedAt),
  run: item.runId,
  provider: item.provider,
  arm: item.arm,
  role: item.role,
  task: item.task,
  pack: item.taskPack,
  profile: item.profile ?? "Unavailable",
  cell: cellState(item),
  evidence: evidenceLabel(item),
  comparison: seriesLabel(item),
  correctness: formatScore(item.dimensions.correctness),
  workflow: formatScore(item.dimensions.workflow),
  efficiency_policy: formatScore(item.dimensions.efficiency_policy),
  runtime: formatSeconds(item.runtimeSeconds),
  tokens: formatCount(observationTokens(item)),
  observed_cost: formatObservedCost(item.observedCost),
  commands: formatCount(item.efficiency.commands),
  targeted_tests: formatCount(item.efficiency.targeted_tests),
  package_tests: formatCount(item.efficiency.package_tests),
  comprehensive_tests: formatCount(item.efficiency.comprehensive_tests),
  premature_suites: formatCount(item.efficiency.premature_comprehensive_tests),
  duplicate_commands: formatCount(item.efficiency.duplicate_successful_commands),
  retries: formatCount(item.efficiency.retries),
  timeouts: formatCount(item.efficiency.timeouts)
}));
```

```js
rows.length
  ? Inputs.table(rows, {
      columns: [
        "finished",
        "run",
        "provider",
        "arm",
        "role",
        "task",
        "pack",
        "profile",
        "cell",
        "evidence",
        "comparison",
        "correctness",
        "workflow",
        "efficiency_policy",
        "runtime",
        "tokens",
        "observed_cost",
        "commands",
        "targeted_tests",
        "package_tests",
        "comprehensive_tests",
        "premature_suites",
        "duplicate_commands",
        "retries",
        "timeouts"
      ]
    })
  : html`<div class="note">No public-safe run reports have been published.</div>`
```

“Unavailable” means the source report did not contain that measurement. It is never treated as zero. Observed costs are API-equivalent telemetry, not incremental subscription spend.
