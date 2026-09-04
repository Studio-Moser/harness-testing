import {readdir, readFile} from "node:fs/promises";
import {dirname, resolve} from "node:path";
import {fileURLToPath, pathToFileURL} from "node:url";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const loaderDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(loaderDirectory, "../../..");

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function resultSortKey(result) {
  return [
    result.run.finished_at,
    result.provider.name,
    result.provider.agent,
    result.arm.id,
    result.task.id,
    result.result_id
  ].join("\0");
}

async function resultEntries(directory) {
  try {
    const entries = await readdir(directory, {withFileTypes: true});
    return entries
      .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
      .sort((left, right) => compareText(left.name, right.name));
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }
}

async function localRunReportEntries(directory) {
  try {
    const entries = await readdir(directory, {withFileTypes: true});
    return entries
      .filter((entry) => entry.isDirectory())
      .sort((left, right) => compareText(left.name, right.name))
      .map((entry) => ({
        directory: entry.name,
        path: resolve(directory, entry.name, "Run_Report.json")
      }));
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }
}

function compileSchema(schema) {
  const ajv = new Ajv2020({allErrors: true, strict: true});
  addFormats(ajv);
  return ajv.compile(schema);
}

function schemaFailure(name, validator) {
  const details = (validator.errors ?? [])
    .map((error) => `${error.instancePath || "$"} ${error.message}`)
    .join("; ");
  return new Error(`${name}: public result schema validation failed: ${details}`);
}

export async function loadPublicResults({
  resultsDirectory = resolve(repositoryRoot, "results"),
  schemaPath = resolve(repositoryRoot, "policy", "Public_Result.schema.json"),
  runsDirectory = resolve(repositoryRoot, "runs", "generated"),
  runReportSchemaPath = resolve(repositoryRoot, "policy", "Run_Report.schema.json")
} = {}) {
  const schema = JSON.parse(await readFile(schemaPath, "utf8"));
  const validate = compileSchema(schema);
  const runReportSchema = JSON.parse(await readFile(runReportSchemaPath, "utf8"));
  const validateRunReport = compileSchema(runReportSchema);
  const finalized = [];

  for (const entry of await resultEntries(resultsDirectory)) {
    let result;
    try {
      result = JSON.parse(await readFile(resolve(resultsDirectory, entry.name), "utf8"));
    } catch (error) {
      throw new Error(`${entry.name}: invalid public result JSON`, {cause: error});
    }
    if (!validate(result)) throw schemaFailure(entry.name, validate);
    if (result.run.finalized === true) finalized.push(result);
  }

  const localRuns = [];
  for (const entry of await localRunReportEntries(runsDirectory)) {
    let report;
    try {
      report = JSON.parse(await readFile(entry.path, "utf8"));
    } catch (error) {
      if (error?.code === "ENOENT") continue;
      throw new Error(`${entry.directory}/Run_Report.json: invalid local run report JSON`, {
        cause: error
      });
    }
    if (!validateRunReport(report)) {
      const details = (validateRunReport.errors ?? [])
        .map((error) => `${error.instancePath || "$"} ${error.message}`)
        .join("; ");
      throw new Error(
        `${entry.directory}/Run_Report.json: local run report schema validation failed: ${details}`
      );
    }
    if (entry.directory !== report.manifest_digest.slice("sha256:".length)) {
      throw new Error(`${entry.directory}/Run_Report.json: manifest directory mismatch`);
    }
    localRuns.push(report);
  }

  finalized.sort((left, right) =>
    compareText(resultSortKey(left), resultSortKey(right))
  );
  const grouped = new Map();
  for (const result of finalized) {
    const key = result.compatibility.key;
    const ids = grouped.get(key) ?? [];
    ids.push(result.result_id);
    grouped.set(key, ids);
  }

  return {
    schema_version: "1",
    results: finalized,
    local_runs: localRuns.sort((left, right) =>
      compareText(
        `${left.updated_at}\0${left.run_id}`,
        `${right.updated_at}\0${right.run_id}`
      )
    ),
    compatibility_series: [...grouped]
      .sort(([left], [right]) => compareText(left, right))
      .map(([key, result_ids]) => ({key, result_ids}))
  };
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) {
  process.stdout.write(JSON.stringify(await loadPublicResults()));
}
