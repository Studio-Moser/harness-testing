---
style: ./Comparison.css
title: Which harness helps?
toc: false
---

# Which harness helps?

Correctness first, then the cost and time required to get working code.

```js
import {renderComparison} from "./components/Comparisons.js";
const report = await FileAttachment("./data/Public_Results.json").json();
const state = Object.fromEntries(new URLSearchParams(location.search));
display(renderComparison(report.run_reports, state));
```
