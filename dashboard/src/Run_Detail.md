---
style: ./Comparison.css
title: Task evidence
toc: false
---

# Task evidence

Inspect graded trials, recorded model usage, final-patch review findings, internal repair evidence, and separate evaluation cost behind a comparison. Missing review evidence remains explicitly unknown.

```js
import {renderEvidence} from "./components/Comparisons.js";
const report = await FileAttachment("./data/Public_Results.json").json();
const state = Object.fromEntries(new URLSearchParams(location.search));
display(renderEvidence(report.run_reports, state));
```

<a href="./Legacy_Run_Detail.html">Inspect earlier run evidence</a> from the original test configurations.
