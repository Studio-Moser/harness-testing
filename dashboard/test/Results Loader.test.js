import assert from "node:assert/strict";
import {afterEach, test} from "node:test";
import {cp, mkdir, mkdtemp, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {dirname, join, resolve} from "node:path";
import {fileURLToPath} from "node:url";

import {loadPublishedReports} from "../src/data/Published Results.json.js";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const temporaries = [];

afterEach(async () => {
  await Promise.all(temporaries.splice(0).map((path) => rm(path, {recursive: true})));
});

async function temporaryReports() {
  const root = await mkdtemp(join(tmpdir(), "harness-results-"));
  temporaries.push(root);
  await mkdir(resolve(root, "reports"));
  return root;
}

test("published results loader validates and sorts current run reports", async () => {
  const root = await temporaryReports();
  await cp(
    resolve(repositoryRoot, "tests", "Fixtures", "Run_Reports", "Comparison.json"),
    resolve(root, "reports", "comparison.json")
  );

  const reports = await loadPublishedReports({
    reportsDirectory: resolve(root, "reports"),
    schemaPath: resolve(repositoryRoot, "policy", "Run_Report.schema.json")
  });

  assert.equal(reports.length, 1);
  assert.equal(reports[0].schema_version, "3");
  assert.equal(reports[0].jobs[0].task, "react-saved-view-feature");
});

test("published results loader counts one canonical snapshot per run", async () => {
  const root = await temporaryReports();
  const fixture = resolve(repositoryRoot, "tests", "Fixtures", "Run_Reports", "Comparison.json");
  await cp(fixture, resolve(root, "reports", "first.json"));
  await cp(fixture, resolve(root, "reports", "duplicate.json"));

  const reports = await loadPublishedReports({
    reportsDirectory: resolve(root, "reports"),
    schemaPath: resolve(repositoryRoot, "policy", "Run_Report.schema.json")
  });

  assert.equal(reports.length, 1);
});

test("published results loader fails closed on malformed reports", async () => {
  const root = await temporaryReports();
  await writeFile(resolve(root, "reports", "bad.json"), "{}\n");

  await assert.rejects(
    loadPublishedReports({
      reportsDirectory: resolve(root, "reports"),
      schemaPath: resolve(repositoryRoot, "policy", "Run_Report.schema.json")
    }),
    /schema validation failed/
  );
});
