import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {fileURLToPath} from "node:url";
import {dirname, resolve} from "node:path";
import test from "node:test";
import {promisify} from "node:util";

import {
  TOOLBOX_CATALOG,
  enrichCatalog,
  validateCatalog
} from "../src/data/Toolbox Catalog.js";

const here = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(here, "../..");
const execFileAsync = promisify(execFile);

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

test("catalog validation rejects duplicate IDs and unsupported classifications", () => {
  assert.throws(
    () => validateCatalog([...TOOLBOX_CATALOG, TOOLBOX_CATALOG[0]]),
    /exactly 15 entries/
  );

  const invalidType = TOOLBOX_CATALOG.map((entry, index) =>
    index === 0 ? {...entry, type: "research"} : entry
  );
  assert.throws(() => validateCatalog(invalidType), /react-accent-polish.*type/);

  const invalidLevel = TOOLBOX_CATALOG.map((entry, index) =>
    index === 0 ? {...entry, level: 5} : entry
  );
  assert.throws(() => validateCatalog(invalidLevel), /react-accent-polish.*level/);
});

test("controlled tests are enriched from their tracked task apparatus", async () => {
  const tests = await enrichCatalog(TOOLBOX_CATALOG, {repositoryRoot});
  const accent = tests.find(({id}) => id === "react-accent-polish");

  assert.match(accent.prompt.exact, /change the `--cta-background` custom property/);
  assert.equal(accent.prompt.url, null);
  assert.equal(accent.apparatus.qaCaseCount, 5);
  assert.equal(accent.apparatus.hasReferenceSolution, true);
  assert.equal(accent.apparatus.hasCorrectnessCheck, true);
  assert.equal(accent.apparatus.hasWorkflowCheck, true);
  assert.equal(accent.apparatus.hasEfficiencyCheck, true);
  assert.ok(accent.apparatus.protectedFiles.includes("src/App.tsx"));
  assert.equal(accent.limits.agentTimeoutSeconds, 900);
  assert.equal(accent.limits.verifierTimeoutSeconds, 180);
  assert.equal(accent.limits.network, "No external network hosts allowed");
});

test("DeepSWE entries expose summaries and pinned links without copied prompts", async () => {
  const tests = await enrichCatalog(TOOLBOX_CATALOG, {repositoryRoot});
  const quill = tests.find(({id}) => id === "quill-shared-toolbar-focus");

  assert.equal(quill.prompt.kind, "upstream");
  assert.equal(quill.prompt.exact, null);
  assert.equal(
    quill.prompt.url,
    "https://github.com/datacurve-ai/deep-swe/blob/8cae5984d5dd0ee37445beff0e928dc10c331116/tasks/quill-shared-toolbar-focus/instruction.md"
  );
  assert.equal(quill.setupState.defined, true);
  assert.equal(quill.setupState.materialized, true);
  assert.equal(quill.setupState.queued, true);
});

test("enrichment stops when a controlled task source is missing", async () => {
  const missingSource = TOOLBOX_CATALOG.map((entry, index) =>
    index === 0 ? {...entry, taskPath: "tasks/workflow/does-not-exist"} : entry
  );

  await assert.rejects(
    enrichCatalog(missingSource, {repositoryRoot}),
    /react-accent-polish.*Comparison Instruction\.md/
  );
});

test("the Observable loader resolves the repository from its own location", async () => {
  const loader = resolve(here, "../src/data/Toolbox.json.js");
  const {stdout} = await execFileAsync(process.execPath, [loader]);
  const output = JSON.parse(stdout);

  assert.equal(output.schemaVersion, 1);
  assert.equal(output.tests.length, 15);
});
