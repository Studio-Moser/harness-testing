---
style: ./Toolbox.css
title: Harnesses
---

```js
import {HARNESS_CATALOG} from "./data/Harness Catalog.js";
import {renderHarnesses} from "./components/Harnesses.js";

for (const link of document.querySelectorAll("[data-nav]")) {
  link.removeAttribute("aria-current");
  link.parentElement.classList.toggle("active", link.dataset.nav === "harnesses");
}
document.querySelector('[data-nav="harnesses"]')?.setAttribute("aria-current", "page");
display(renderHarnesses(HARNESS_CATALOG));
```
