---
style: ./Toolbox.css
title: Results
toc: false
---

```js
import {renderResults} from "./components/Results.js";
import {HARNESS_CATALOG} from "./data/Harness Catalog.js";

const {tests} = await FileAttachment("./data/Toolbox.json").json();
const reports = await FileAttachment("./data/Published Results.json").json();

for (const link of document.querySelectorAll("[data-nav]")) link.removeAttribute("aria-current");
document.querySelector('[data-nav="results"]')?.setAttribute("aria-current", "page");
display(renderResults({tests, harnesses: HARNESS_CATALOG, reports}));
```
