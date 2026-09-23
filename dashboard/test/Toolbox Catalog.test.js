import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {mkdir, mkdtemp, rm, symlink, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {fileURLToPath} from "node:url";
import {dirname, join, resolve} from "node:path";
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
  "polish:2": 1,
  "polish:3": 3,
  "polish:4": 1,
  "bug-fix:1": 1,
  "bug-fix:2": 3,
  "bug-fix:3": 1,
  "bug-fix:4": 2,
  "feature:1": 1,
  "feature:2": 3,
  "feature:3": 2,
  "feature:4": 5
};

test("the catalog exposes the accepted 25-test coverage contract", () => {
  validateCatalog(TOOLBOX_CATALOG);
  assert.equal(TOOLBOX_CATALOG.length, 25);

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
    /exactly 25 entries/
  );

  const invalidType = TOOLBOX_CATALOG.map((entry, index) =>
    index === 0 ? {...entry, type: "research"} : entry
  );
  assert.throws(() => validateCatalog(invalidType), /node-cross-module-permissions.*type/);

  const invalidLevel = TOOLBOX_CATALOG.map((entry, index) =>
    index === 0 ? {...entry, level: 5} : entry
  );
  assert.throws(() => validateCatalog(invalidLevel), /node-cross-module-permissions.*level/);

  const replacementId = TOOLBOX_CATALOG.map((entry, index) =>
    index === 0 ? {...entry, id: "unapproved-replacement"} : entry
  );
  assert.throws(() => validateCatalog(replacementId), /unapproved-replacement.*allowlist/);

  const missingDeepSweSource = TOOLBOX_CATALOG.map((entry) =>
    entry.id === "quill-shared-toolbar-focus"
      ? {...entry, repository: "", baseCommit: "", promptUrl: ""}
      : entry
  );
  assert.throws(
    () => validateCatalog(missingDeepSweSource),
    /quill-shared-toolbar-focus.*repository/
  );
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
  assert.equal(
    accent.source.baseCommit,
    "sha256:7d414f0629b2f310caa50d564e0ff6da5fb70f88a6d868ad6c4841f4a6234579"
  );
  assert.deepEqual(accent.environment, {
    workdir: "/app",
    verifierIsolation: "separate",
    agent: {cpus: 2, memoryMb: 4096, storageMb: 10240},
    verifier: {cpus: 2, memoryMb: 4096, storageMb: 10240},
    mcpServers: []
  });
});

test("DeepSWE entries expose summaries and pinned links without copied prompts", async () => {
  const fixtureRoot = await mkdtemp(join(tmpdir(), "toolbox-catalog-"));
  const quillTask = join(
    fixtureRoot,
    ".cache",
    "deepswe",
    "datasets",
    "fixture",
    "tasks",
    "quill-shared-toolbar-focus"
  );

  try {
    await symlink(resolve(repositoryRoot, "tasks"), join(fixtureRoot, "tasks"), "dir");
    await mkdir(quillTask, {recursive: true});
    await writeFile(join(quillTask, "task.toml"), "");

    const tests = await enrichCatalog(TOOLBOX_CATALOG, {repositoryRoot: fixtureRoot});
    const quill = tests.find(({id}) => id === "quill-shared-toolbar-focus");
    const happyDom = tests.find(({id}) => id === "happy-dom-abort-pending-body-reads");

    assert.equal(quill.prompt.kind, "upstream");
    assert.equal(quill.prompt.exact, null);
    assert.equal(
      quill.prompt.url,
      "https://github.com/datacurve-ai/deep-swe/blob/8cae5984d5dd0ee37445beff0e928dc10c331116/tasks/quill-shared-toolbar-focus/instruction.md"
    );
    assert.equal(quill.setupState.defined, true);
    assert.equal(quill.setupState.materialized, true);
    assert.equal(quill.setupState.queued, true);
    assert.equal(happyDom.setupState.materialized, false);
  } finally {
    await rm(fixtureRoot, {recursive: true, force: true});
  }
});

test("enrichment stops when a controlled task source is missing", async () => {
  const missingSource = TOOLBOX_CATALOG.map((entry, index) =>
    index === 0 ? {...entry, taskPath: "tasks/workflow/does-not-exist"} : entry
  );

  await assert.rejects(
    enrichCatalog(missingSource, {repositoryRoot}),
    /node-cross-module-permissions.*Comparison Instruction\.md/
  );
});

test("the Observable loader resolves the repository from its own location", async () => {
  const loader = resolve(here, "../src/data/Toolbox.json.js");
  const {stdout} = await execFileAsync(process.execPath, [loader]);
  const output = JSON.parse(stdout);

  assert.equal(output.schemaVersion, 2);
  assert.equal(output.tests.length, 25);
});
