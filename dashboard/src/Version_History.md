---
style: ./Comparison.css
title: Version history
toc: false
---

# Version history

Follow each Studio Moser version, its intended improvement, and what the tests actually showed.

```js
import {renderHistory} from "./components/Comparisons.js";
const report = await FileAttachment("./data/Public_Results.json").json();
const state = Object.fromEntries(new URLSearchParams(location.search));
display(renderHistory(report.run_reports, state));
```
