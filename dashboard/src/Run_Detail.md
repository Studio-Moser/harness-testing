---
style: ./Comparison.css
title: Task evidence
toc: false
---

# Task evidence

Inspect the graded trials and recorded model usage behind a comparison.

```js
import {renderEvidence} from "./components/Comparisons.js";
const report = await FileAttachment("./data/Public_Results.json").json();
const state = Object.fromEntries(new URLSearchParams(location.search));
display(renderEvidence(report.run_reports, state));
```

<a href="./Legacy_Run_Detail.html">Inspect earlier run evidence</a> from the original test configurations.
