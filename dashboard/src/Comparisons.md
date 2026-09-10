---
style: ./Comparison.css
title: Harness comparison
toc: false
---

# Harness comparison

Compare engineering correctness, cost, and user-visible collaboration under the same test conditions.

```js
import {renderComparison} from "./components/Comparisons.js";
const report = await FileAttachment("./data/Public_Results.json").json();
const state = Object.fromEntries(new URLSearchParams(location.search));
display(renderComparison(report.run_reports, state));
```
