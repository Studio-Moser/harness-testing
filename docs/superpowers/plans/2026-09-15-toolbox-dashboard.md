# Harness Test Toolbox Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the results dashboard UI with a read-only Toolbox that accurately inventories the 15 selected Harness Tests by work type and task level, exposes coverage gaps through faceted navigation, and keeps detailed test apparatus discoverable without showing results or recommendations.

**Architecture:** Observable Framework remains the static build and data-loader host. A checked-in editorial catalog supplies the product-language fields that source files cannot provide; a build-time loader enriches the nine controlled tests from their real task directories and emits one browser-safe JSON artifact. A plain JavaScript component owns URL-backed filtering, counts, grouping, and semantic rendering. Tabler CSS is pinned from its CDN and a small local stylesheet supplies the Toolbox-specific layout.

**Tech Stack:** Observable Framework 1.13.4, Node.js ES modules and `node:test`, plain browser JavaScript, native HTML controls and `<details>`, CSS, Tabler CSS 1.5.1 from jsDelivr.

**Spec:** [2026-09-15 Toolbox Dashboard Design](../specs/2026-09-15-toolbox-dashboard-design.md)

## Global Constraints

- Invoke `frontend-design:frontend-design` before implementing the page shell and CSS. Preserve the approved wireframe hierarchy: compact top navigation, two count-bearing filter rows, a live overlap summary, level-grouped cards, and collapsed structured detail sections.
- Do not display run results, winners, recommendations, cost, elapsed time, tokens, grades, or confidence. This page describes the test toolbox only.
- Do not mutate experiment evidence, task fixtures, Harbor state, or DeepSWE source material.
- Treat the nine controlled test prompts as local source text. For DeepSWE, store a faithful summary and link to the exact upstream file pinned at commit `8cae5984d5dd0ee37445beff0e928dc10c331116`; do not copy the full prompt into this repository.
- Keep the catalog schema explicit and validated. Fail the build for duplicate IDs, missing required fields, a missing local prompt, an unsupported type/level, or a catalog count other than 15.
- Run the red-green cycle for every JavaScript behavior. Configuration and human-authored prose do not need source-text tests.
- The accepted coverage contract is:

  | Type | L1 | L2 | L3 | L4 | Total |
  | --- | ---: | ---: | ---: | ---: | ---: |
  | Polish | 2 | 0 | 2 | 0 | 4 |
  | Bug fix | 0 | 3 | 0 | 1 | 4 |
  | Feature | 0 | 0 | 2 | 5 | 7 |
  | Total | 2 | 3 | 4 | 6 | 15 |

---

## Task 1: Build the authoritative Toolbox catalog

**Files:**

- Create: `dashboard/src/data/Toolbox Catalog.js`
- Create: `dashboard/src/data/Toolbox.json.js`
- Create: `dashboard/test/Toolbox Catalog.test.js`

- [ ] **Step 1: Write failing catalog contract tests**

  Add tests that import `validateCatalog`, `enrichCatalog`, and `TOOLBOX_CATALOG`. The production changes each test catches are: an omitted/extra Toolbox test, a classification drift that hides a coverage gap, a duplicate ID, an invalid type/level, a missing local source file, and accidental inclusion of the routing diagnostic.

  ```js
  import assert from "node:assert/strict";
  import test from "node:test";
  import {
    TOOLBOX_CATALOG,
    enrichCatalog,
    validateCatalog
  } from "../src/data/Toolbox Catalog.js";

  const EXPECTED_CELLS = {
    "polish:1": 2,
    "polish:2": 0,
    "polish:3": 2,
    "polish:4": 0,
    "bug-fix:1": 0,
    "bug-fix:2": 3,
    "bug-fix:3": 0,
    "bug-fix:4": 1,
    "feature:1": 0,
    "feature:2": 0,
    "feature:3": 2,
    "feature:4": 5
  };

  test("the catalog exposes the accepted 15-test coverage contract", () => {
    validateCatalog(TOOLBOX_CATALOG);
    assert.equal(TOOLBOX_CATALOG.length, 15);
    for (const [cell, count] of Object.entries(EXPECTED_CELLS)) {
      const [type, level] = cell.split(":");
      assert.equal(
        TOOLBOX_CATALOG.filter((entry) => entry.type === type && entry.level === Number(level)).length,
        count,
        cell
      );
    }
    assert.equal(TOOLBOX_CATALOG.some(({id}) => id === "react-bulk-dashboard-updates"), false);
  });
  ```

  Add focused assertions that `validateCatalog([...TOOLBOX_CATALOG, TOOLBOX_CATALOG[0]])` throws for a duplicate ID and that an entry with `type: "research"` or `level: 5` throws. Use a temporary directory fixture to prove `enrichCatalog` reads a controlled test's exact `Comparison Instruction.md` and `Protected_Files.json`, then fails when either required file is absent.

- [ ] **Step 2: Run the catalog test and verify RED**

  Run: `cd dashboard && node --test 'test/Toolbox Catalog.test.js'`

  Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `Toolbox Catalog.js`.

- [ ] **Step 3: Implement the editorial catalog and validator**

  Export one frozen array with these exact IDs and classifications:

  ```js
  const CONTROLLED = "controlled";
  const DEEP_SWE = "deep-swe";

  export const TOOLBOX_CATALOG = Object.freeze([
    {id: "react-accent-polish", type: "polish", level: 1, sourceKind: CONTROLLED},
    {id: "static-pricing-copy-polish", type: "polish", level: 1, sourceKind: CONTROLLED},
    {id: "react-active-badge-count", type: "bug-fix", level: 2, sourceKind: CONTROLLED},
    {id: "rust-quoted-value-parser", type: "bug-fix", level: 2, sourceKind: CONTROLLED},
    {id: "static-accessible-disclosure", type: "bug-fix", level: 2, sourceKind: CONTROLLED},
    {id: "react-grouped-ui-updates", type: "polish", level: 3, sourceKind: CONTROLLED},
    {id: "static-grouped-page-updates", type: "polish", level: 3, sourceKind: CONTROLLED},
    {id: "react-saved-view-feature", type: "feature", level: 3, sourceKind: CONTROLLED},
    {id: "rust-workspace-warning-summary", type: "feature", level: 3, sourceKind: CONTROLLED},
    {id: "happy-dom-abort-pending-body-reads", type: "bug-fix", level: 4, sourceKind: DEEP_SWE},
    {id: "quill-shared-toolbar-focus", type: "feature", level: 4, sourceKind: DEEP_SWE},
    {id: "yjs-map-conflict-detection", type: "feature", level: 4, sourceKind: DEEP_SWE},
    {id: "katex-multicolumn-array-spans", type: "feature", level: 4, sourceKind: DEEP_SWE},
    {id: "wasmi-trap-coredumps", type: "feature", level: 4, sourceKind: DEEP_SWE},
    {id: "pest-character-class-coalescing", type: "feature", level: 4, sourceKind: DEEP_SWE}
  ].map((entry) => Object.freeze(entry)));
  ```

  Flesh out every entry with non-empty `title`, `purpose`, `promptSummary`, `stack`, `setupSummary`, `expectedProcess`, `expectedHarnessBehavior`, `verification`, and `learningGoal` fields. Controlled entries also have `taskPath`. DeepSWE entries have `repository`, `commit`, and `promptUrl` fields. Keep these product-language fields editorial; do not invent result claims.

  Export `validateCatalog(entries)` and `enrichCatalog(entries, {repositoryRoot})`. Validation must check the 15-entry count, uniqueness, allowed types (`polish`, `bug-fix`, `feature`), levels 1–4, non-empty required fields, controlled local paths, and the pinned DeepSWE commit. Enrichment must use Node standard-library file reads to add:

  ```js
  {
    prompt: {
      kind: "local",
      exact: "Work in `/app` and change the `--cta-background` custom property from `#2563eb` to `#6d28d9`. Keep this to the source value; preserve component behavior.\n\nPreserve existing project tests, package metadata, build configuration, and check scripts. Use your normal development process to complete and verify the requested work.",
      url: null
    },
    apparatus: {
      protectedFiles: [".dockerignore", "Dockerfile", "eslint.config.js", "index.html", "package-lock.json", "package.json", "scripts/Check_Token.mjs", "src/App.css", "src/App.test.tsx", "src/App.tsx", "src/main.tsx", "tsconfig.app.json", "tsconfig.json", "tsconfig.node.json", "vite.config.ts"],
      qaCaseCount: 5,
      hasReferenceSolution: true,
      hasCorrectnessCheck: true,
      hasWorkflowCheck: true,
      hasEfficiencyCheck: true
    },
    setupState: {defined: true, materialized: false, queued: false}
  }
  ```

  For DeepSWE, set `prompt.kind` to `upstream`, `exact` to `null`, and `url` to the pinned URL. Derive `materialized` from the presence of a matching local Harbor task directory under the repository's configured work area when that path exists; otherwise leave it false. Set `queued` only from a checked-in explicit catalog field, not from run results.

- [ ] **Step 4: Implement the Observable data loader**

  `Toolbox.json.js` should resolve the repository root relative to `import.meta.url`, call `enrichCatalog`, and write only JSON to stdout:

  ```js
  import {fileURLToPath} from "node:url";
  import {dirname, resolve} from "node:path";
  import {TOOLBOX_CATALOG, enrichCatalog} from "./Toolbox Catalog.js";

  const here = dirname(fileURLToPath(import.meta.url));
  const repositoryRoot = resolve(here, "../../../..");
  const tests = await enrichCatalog(TOOLBOX_CATALOG, {repositoryRoot});
  process.stdout.write(JSON.stringify({schemaVersion: 1, tests}));
  ```

- [ ] **Step 5: Run the catalog test and verify GREEN**

  Run: `cd dashboard && node --test 'test/Toolbox Catalog.test.js'`

  Expected: PASS.

- [ ] **Step 6: Commit the catalog slice**

  ```bash
  git add 'dashboard/src/data/Toolbox Catalog.js' dashboard/src/data/Toolbox.json.js 'dashboard/test/Toolbox Catalog.test.js'
  git commit -m "feat: add Harness Test toolbox catalog"
  ```

## Task 2: Implement URL-backed faceted filtering and semantic cards

**Files:**

- Create: `dashboard/src/components/Toolbox.js`
- Create: `dashboard/test/Toolbox.test.js`

- [ ] **Step 1: Write failing state and coverage tests**

  The production changes these tests catch are incorrect URL normalization, conjunctive filtering that behaves like OR, counts that disappear after a selection, hidden zero-coverage cells, and unstable grouping/order.

  ```js
  import assert from "node:assert/strict";
  import test from "node:test";
  import {
    facetCounts,
    filterTests,
    groupTests,
    selectionFromSearch,
    selectionUrl
  } from "../src/components/Toolbox.js";

  const tests = [
    {id: "b", title: "Bravo", type: "bug-fix", level: 2},
    {id: "a", title: "Alpha", type: "polish", level: 1},
    {id: "c", title: "Charlie", type: "feature", level: 4}
  ];

  test("type and level combine as an intersection", () => {
    assert.deepEqual(filterTests(tests, {type: "bug-fix", level: 2}).map(({id}) => id), ["b"]);
    assert.deepEqual(filterTests(tests, {type: "polish", level: 2}), []);
  });

  test("facet counts preserve zero-coverage combinations", () => {
    const counts = facetCounts(tests, {type: "polish", level: 2});
    assert.equal(counts.overlap, 0);
    assert.equal(counts.types["bug-fix"], 1);
    assert.equal(counts.levels[3], 0);
  });

  test("query parameters round-trip and invalid values fall back to All", () => {
    assert.deepEqual(selectionFromSearch("?type=bug-fix&level=2"), {type: "bug-fix", level: 2});
    assert.deepEqual(selectionFromSearch("?type=nope&level=9"), {type: "all", level: "all"});
    assert.equal(selectionUrl({type: "feature", level: 4}), "?type=feature&level=4");
    assert.equal(selectionUrl({type: "all", level: "all"}), "?");
  });

  test("groups are level-ascending with alphabetical cards", () => {
    assert.deepEqual(groupTests(tests).map((group) => [group.level, group.tests.map(({id}) => id)]), [
      [1, ["a"]],
      [2, ["b"]],
      [4, ["c"]]
    ]);
  });
  ```

- [ ] **Step 2: Run the component test and verify RED**

  Run: `cd dashboard && node --test test/Toolbox.test.js`

  Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `Toolbox.js`.

- [ ] **Step 3: Implement the pure state functions**

  Export exactly these functions:

  ```js
  export function selectionFromSearch(search) {}
  export function selectionUrl(selection) {}
  export function filterTests(tests, selection) {}
  export function facetCounts(tests, selection) {}
  export function groupTests(tests) {}
  export function renderToolbox(tests, {location = window.location, history = window.history} = {}) {}
  ```

  Counts in each type button must reflect the selected level; counts in each level button must reflect the selected type. The separate overlap summary shows the fully filtered count. All buttons remain visible at zero. `history.replaceState` must update only `type` and `level`, preserve the pathname and hash, and omit `all` parameters.

- [ ] **Step 4: Add failing render tests using a minimal real document fixture**

  Reuse the repository's existing small fake-element testing pattern only where needed. Assert observable behavior: navigation has accessible labels, the selected filters expose `aria-pressed="true"`, a zero-result selection renders the coverage-gap empty state, level headings are ascending, and every card exposes the six named sections:

  - What it tests
  - Task brief
  - Test setup
  - Expected agent process
  - Verification
  - What we learn

  Also assert that a DeepSWE card links to its pinned upstream prompt while a controlled card renders its exact local prompt inside its details section.

- [ ] **Step 5: Run the render tests and verify RED**

  Run: `cd dashboard && node --test test/Toolbox.test.js`

  Expected: FAIL because `renderToolbox` is not yet implemented.

- [ ] **Step 6: Implement semantic rendering and interactions**

  Build elements with `document.createElement`; do not inject catalog text through `innerHTML`. Render:

  - a labeled Type filter row with All, Polish, Bug fix, Feature;
  - a labeled Level filter row with All, L1 Atomic, L2 Focused, L3 Coordinated, L4 Complex;
  - an `aria-live="polite"` overlap statement;
  - level groups containing cards sorted alphabetically;
  - always-visible card metadata for title, type, level, stack, source, setup state, and task ID;
  - native `<details>` sections for the six detail groups;
  - an explicit zero-coverage message when no test matches.

  Filter clicks update the URL, button accessibility state, counts, overlap summary, and card list without a reload.

- [ ] **Step 7: Run the component test and verify GREEN**

  Run: `cd dashboard && node --test test/Toolbox.test.js`

  Expected: PASS.

- [ ] **Step 8: Commit the interaction slice**

  ```bash
  git add dashboard/src/components/Toolbox.js dashboard/test/Toolbox.test.js
  git commit -m "feat: add Toolbox filtering and cards"
  ```

## Task 3: Replace the dashboard shell and styling

**Files:**

- Modify: `dashboard/observablehq.config.js`
- Modify: `dashboard/src/index.md`
- Create: `dashboard/src/Toolbox.css`
- Delete: `dashboard/src/Comparison.css`
- Delete: `dashboard/src/Comparisons.md`
- Delete: `dashboard/src/Legacy_Run_Detail.md`
- Delete: `dashboard/src/Quality_Versus_Efficiency.md`
- Delete: `dashboard/src/Run_Detail.md`
- Delete: `dashboard/src/Task_Matrix.md`
- Delete: `dashboard/src/Trends.md`
- Delete: `dashboard/src/Version_History.md`
- Delete: `dashboard/src/components/Collaboration.js`
- Delete: `dashboard/src/components/Comparisons.js`
- Delete: `dashboard/src/components/Results.js`
- Delete: `dashboard/src/components/Run_History.js`
- Delete: `dashboard/src/components/Task_Types.js`
- Delete: `dashboard/src/data/Public_Results.json.js`
- Delete: `dashboard/test/Comparisons.test.js`
- Delete: `dashboard/test/Public_Results.test.js`
- Delete: `dashboard/test/Run_History.test.js`
- Delete: `dashboard/test/Task_Types.test.js`

- [ ] **Step 1: Invoke and apply the frontend design skill**

  Read `frontend-design:frontend-design` in full before editing the page. Use the accepted design as the constraint, not an invitation to add new features: light neutral canvas, restrained blue accent, compact top navigation, count-bearing filter controls, high-information cards, and 3/2/1 responsive columns. Avoid gradients, hero marketing language, decorative illustration, charts, or result-oriented UI.

- [ ] **Step 2: Replace the Observable page and configuration**

  Configure Toolbox as the only page and disable the old sidebar. Pin Tabler CSS from:

  `https://cdn.jsdelivr.net/npm/@tabler/core@1.5.1/dist/css/tabler.min.css`

  Load local `Toolbox.css`, fetch `./data/Toolbox.json`, and mount the component:

  ```md
  ---
  style: ./Toolbox.css
  title: Harness Test Toolbox
  toc: false
  ---

  ```js
  import {renderToolbox} from "./components/Toolbox.js";
  const {tests} = await FileAttachment("./data/Toolbox.json").json();
  display(renderToolbox(tests));
  ```
  ```

  The page copy must explain that the Toolbox inventories what is tested and what an agent/harness must do; it must not imply that runs or recommendations appear here.

- [ ] **Step 3: Implement the responsive visual system**

  Define a small set of local CSS custom properties and Toolbox component classes. Preserve visible focus rings, at least 44px touch targets for filter controls, readable line lengths, sufficient contrast, and reduced-motion behavior. Use native responsive CSS:

  - 3 columns above 1180px;
  - 2 columns from 760px through 1179px;
  - 1 column below 760px;
  - filter rows wrap without horizontal page scrolling;
  - details summaries retain clear open/closed affordances.

- [ ] **Step 4: Remove the old results presentation**

  Delete the listed pages, presentation components, results-only loader, styles, and their obsolete tests. Do not delete any files outside `dashboard/` and do not touch local experiment evidence.

- [ ] **Step 5: Run the complete dashboard test suite**

  Run: `cd dashboard && npm test`

  Expected: all Toolbox tests PASS with no warnings.

- [ ] **Step 6: Build the static dashboard**

  Run: `cd dashboard && npm run build`

  Expected: build exits 0, emits `dist/index.html` and the Toolbox JSON artifact, and reports no broken page imports.

- [ ] **Step 7: Commit the page replacement**

  ```bash
  git add -A dashboard
  git commit -m "feat: replace results UI with Harness Test Toolbox"
  ```

## Task 4: Prove the shipped page and independently review it

**Files:**

- Modify only if proof finds a defect: `dashboard/src/components/Toolbox.js`, `dashboard/src/Toolbox.css`, `dashboard/src/data/Toolbox Catalog.js`, or their matching tests

- [ ] **Step 1: Start the Observable preview on a stable local port**

  Run: `cd dashboard && npm run dev -- --host 127.0.0.1 --port 3000`

  Expected: preview serves the Toolbox at `http://127.0.0.1:3000/`.

- [ ] **Step 2: Exercise the acceptance paths in a real browser**

  Verify and record these exact observations:

  - the default shows 15 tests grouped L1, L2, L3, L4;
  - Type = Bug fix and Level = L2 shows 3 cards and URL `?type=bug-fix&level=2`;
  - Type = Polish and Level = L2 shows the zero-coverage state while all filter controls remain available;
  - refreshing a filtered URL restores the selection;
  - expanding a controlled test shows the exact local task brief and apparatus;
  - expanding a DeepSWE test shows a summary plus a pinned upstream link, not copied prompt text;
  - keyboard focus is visible and native details are operable;
  - the layout has 3, 2, and 1 columns at desktop, tablet, and phone widths without page-level horizontal overflow.

- [ ] **Step 3: Request the required independent UI review**

  Give the reviewer the design spec, the frozen diff/commit range, and the running page. Ask only for spec violations, catalog inaccuracies, accessibility failures, and material visual hierarchy problems. Do not ask for feature expansion.

- [ ] **Step 4: Address only confirmed defects with TDD**

  For behavior defects, add a failing test, observe RED, apply the minimum fix, and observe GREEN. For CSS-only defects, make the smallest edit and repeat the exact browser observation that exposed it.

- [ ] **Step 5: Run the final proof pass**

  Run:

  ```bash
  cd dashboard
  npm test
  npm run build
  ```

  Expected: both commands exit 0. Then repeat the filtered and zero-coverage browser paths once against the final build.

- [ ] **Step 6: Commit review fixes, if any**

  ```bash
  git add dashboard
  git commit -m "fix: address Toolbox review findings"
  ```

  Skip this commit when the independent review finds no defect.
