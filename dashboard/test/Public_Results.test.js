import assert from "node:assert/strict";
import {afterEach, test} from "node:test";
import {cp, mkdir, mkdtemp, readFile, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {dirname, join, resolve} from "node:path";
import {fileURLToPath} from "node:url";

import {loadPublicResults} from "../src/data/Public_Results.json.js";
import {
  deliveryLabel,
  latestResults,
  totalRuntime,
  totalTokens
} from "../src/components/Results.js";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const fixtureRoot = resolve(repositoryRoot, "tests", "Fixtures", "Public_Results");
const temporaries = [];

afterEach(async () => {
  await Promise.all(temporaries.splice(0).map((path) => rm(path, {recursive: true})));
});

async function testRoot() {
  const root = await mkdtemp(join(tmpdir(), "harness-dashboard-"));
  temporaries.push(root);
  await mkdir(resolve(root, "policy"));
  await mkdir(resolve(root, "results"));
  await cp(
    resolve(repositoryRoot, "policy", "Public_Result.schema.json"),
    resolve(root, "policy", "Public_Result.schema.json")
  );
  return root;
}

async function loadFrom(root) {
  return loadPublicResults({
    resultsDirectory: resolve(root, "results"),
    schemaPath: resolve(root, "policy", "Public_Result.schema.json")
  });
}

async function fixture(name) {
  return JSON.parse(await readFile(resolve(fixtureRoot, name), "utf8"));
}

test("loads only finalized public results, preserves nulls, and groups compatibility", async () => {
  const root = await testRoot();
  const valid = await fixture("Valid.json");
  await writeFile(resolve(root, "results", "Valid.json"), JSON.stringify(valid));
  await mkdir(resolve(root, "jobs"));
  await cp(
    resolve(fixtureRoot, "Raw_Harbor_Job.json"),
    resolve(root, "jobs", "Must_Not_Be_Read.json")
  );

  const report = await loadFrom(root);

  assert.equal(report.results.length, 1);
  assert.equal(report.results[0].efficiency.reasoning_tokens, null);
  assert.equal(report.results[0].efficiency.test_seconds, null);
  assert.deepEqual(report.compatibility_series, [
    {
      key: valid.compatibility.key,
      result_ids: [valid.result_id]
    }
  ]);
});

test("rejects raw Harbor and secret-path fixtures instead of filtering them", async (context) => {
  for (const name of ["Raw_Harbor_Job.json", "Secret_Path.json"]) {
    await context.test(name, async () => {
      const root = await testRoot();
      await cp(resolve(fixtureRoot, name), resolve(root, "results", name));

      await assert.rejects(loadFrom(root), /public result schema validation failed/);
    });
  }
});

test("excludes a schema-valid non-finalized result", async () => {
  const root = await testRoot();
  const partial = await fixture("Valid.json");
  partial.run.finalized = false;
  partial.review.partial = true;
  await writeFile(resolve(root, "results", "Partial.json"), JSON.stringify(partial));

  const report = await loadFrom(root);

  assert.deepEqual(report.results, []);
  assert.deepEqual(report.compatibility_series, []);
});

test("sorts results and compatibility groups deterministically", async () => {
  const root = await testRoot();
  const earlier = await fixture("Valid.json");
  const later = structuredClone(earlier);
  later.result_id = `sha256:${"b".repeat(64)}`;
  later.run.id = "33333333-3333-4333-8333-333333333333";
  later.run.trial_id = "44444444-4444-4444-8444-444444444444";
  later.run.started_at = "2026-08-30T04:43:22.285378Z";
  later.run.finished_at = "2026-08-30T04:44:22.669536Z";
  later.compatibility.key = `sha256:${"c".repeat(64)}`;
  await writeFile(resolve(root, "results", "Z.json"), JSON.stringify(earlier));
  await writeFile(resolve(root, "results", "A.json"), JSON.stringify(later));

  const report = await loadFrom(root);

  assert.deepEqual(
    report.results.map((result) => result.result_id),
    [earlier.result_id, later.result_id]
  );
  assert.deepEqual(
    report.compatibility_series.map((series) => series.key),
    [earlier.compatibility.key, later.compatibility.key]
  );
});

test("report helpers keep unknown telemetry unavailable and label delivery surfaces", async () => {
  const valid = await fixture("Valid.json");
  assert.equal(totalRuntime(valid), valid.efficiency.agent_seconds + valid.efficiency.verifier_seconds);
  assert.equal(totalTokens(valid), valid.efficiency.prompt_tokens + valid.efficiency.completion_tokens);
  valid.efficiency.prompt_tokens = null;
  assert.equal(totalTokens(valid), null);

  const codex = structuredClone(valid);
  codex.arm.id = "A1";
  assert.match(deliveryLabel(codex), /Superpowers skills-only/);
  const claude = structuredClone(codex);
  claude.provider.agent = "claude-code";
  assert.match(deliveryLabel(claude), /Superpowers hook-capable/);

  assert.deepEqual(latestResults([valid, valid]), [valid]);
});
