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
const runFixtureRoot = resolve(repositoryRoot, "tests", "Fixtures", "Run_Reports");
const temporaries = [];

afterEach(async () => {
  await Promise.all(temporaries.splice(0).map((path) => rm(path, {recursive: true})));
});

async function testRoot() {
  const root = await mkdtemp(join(tmpdir(), "harness-dashboard-"));
  temporaries.push(root);
  await mkdir(resolve(root, "policy"));
  await mkdir(resolve(root, "results"));
  await mkdir(resolve(root, "published"));
  await mkdir(resolve(root, "runs", "generated"), {recursive: true});
  await cp(
    resolve(repositoryRoot, "policy", "Public_Result.schema.json"),
    resolve(root, "policy", "Public_Result.schema.json")
  );
  return root;
}

async function loadFrom(root) {
  return loadPublicResults({
    resultsDirectory: resolve(root, "results"),
    publishedReportsDirectory: resolve(root, "published"),
    schemaPath: resolve(root, "policy", "Public_Result.schema.json"),
    runsDirectory: resolve(root, "runs", "generated"),
    runReportSchemaPath: resolve(repositoryRoot, "policy", "Run_Report.schema.json")
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
  assert.deepEqual(report.results[0].skill_evaluation, {
    mode: "none",
    name: null,
    invocation: "none"
  });
  assert.deepEqual(report.compatibility_series, [
    {
      key: valid.compatibility.key,
      result_ids: [valid.result_id]
    }
  ]);
});

test("loads safe local run reports separately from finalized public results", async () => {
  const root = await testRoot();
  const reportDirectory = resolve(
    root,
    "runs",
    "generated",
    "d73dda59bad84372f94499627e52325aa49bb01d8141d8eccfbba0cc2375f05a"
  );
  await mkdir(reportDirectory);
  await cp(
    resolve(runFixtureRoot, "Valid.json"),
    resolve(reportDirectory, "Run_Report.json")
  );

  const report = await loadFrom(root);

  assert.equal(report.local_runs.length, 1);
  assert.equal(report.local_runs[0].status, "completed");
  assert.equal(report.local_runs[0].jobs[0].dimensions.correctness, 1);
  assert.equal(report.local_runs[0].jobs[0].efficiency.api_equivalent_cost_usd, 0.01);
  assert.equal(report.run_reports.length, 1);
  assert.deepEqual(report.results, []);
});

test("loads data-branch reports and deduplicates local copies", async () => {
  const root = await testRoot();
  const digest = "d73dda59bad84372f94499627e52325aa49bb01d8141d8eccfbba0cc2375f05a";
  const reportDirectory = resolve(root, "runs", "generated", digest);
  await mkdir(reportDirectory);
  await cp(resolve(runFixtureRoot, "Valid.json"), resolve(root, "published", "run-a.json"));
  await cp(
    resolve(runFixtureRoot, "Valid.json"),
    resolve(reportDirectory, "Run_Report.json")
  );

  const report = await loadFrom(root);

  assert.equal(report.run_reports.length, 1);
  assert.equal(report.local_runs.length, 1);
});

test("rejects malformed published reports", async () => {
  const root = await testRoot();
  await writeFile(resolve(root, "published", "Bad.json"), "{}\n");

  await assert.rejects(loadFrom(root), /published run report schema validation failed/);
});

test("rejects malformed local run reports instead of silently omitting them", async () => {
  const root = await testRoot();
  const reportDirectory = resolve(root, "runs", "generated", "broken");
  await mkdir(reportDirectory);
  await writeFile(resolve(reportDirectory, "Run_Report.json"), "{}\n");

  await assert.rejects(loadFrom(root), /local run report schema validation failed/);
});

test("dashboard pages await the generated result attachment before reading it", async () => {
  for (const name of [
    "index.md",
    "Comparisons.md",
    "Quality_Versus_Efficiency.md",
    "Run_Detail.md",
    "Task_Matrix.md",
    "Trends.md"
  ]) {
    const source = await readFile(resolve(repositoryRoot, "dashboard", "src", name), "utf8");
    assert.match(source, /const report = await FileAttachment\([^\n]+\)\.json\(\);/, name);
    assert.match(source, /runObservations\(report\.run_reports, report\.results\)/, name);
  }
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
