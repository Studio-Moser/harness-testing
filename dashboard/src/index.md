---
style: ./Toolbox.css
title: Harness Test Toolbox
toc: false
---

```js
import {renderToolbox} from "./components/Toolbox.js";
const {tests} = await FileAttachment("./data/Toolbox.json").json();

for (const link of document.querySelectorAll("[data-nav]")) link.removeAttribute("aria-current");
document.querySelector('[data-nav="toolbox"]')?.setAttribute("aria-current", "page");
display(renderToolbox(tests));
```
