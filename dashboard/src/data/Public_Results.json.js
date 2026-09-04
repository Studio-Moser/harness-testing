import {readdir, readFile} from "node:fs/promises";
import {createHash} from "node:crypto";
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

function runReportSortKey(report) {
  return [
    report.finished_at ?? report.updated_at,
    report.run_id,
    report.report_id ?? ""
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

function schemaFailure(name, validator, description = "public result") {
  const details = (validator.errors ?? [])
    .map((error) => `${error.instancePath || "$"} ${error.message}`)
    .join("; ");
  return new Error(`${name}: ${description} schema validation failed: ${details}`);
}

const privateFields = new Set([
  "command_output",
  "env",
  "environment",
  "environment_variables",
  "extra",
  "prompt",
  "prompts",
  "reasoning",
  "reasoning_content",
  "tool_output",
  "trajectory",
  "trajectories"
]);
const sensitiveKey = /(?:^|_)(?:api_key|access_token|refresh_token|auth_token|authorization|password|secret|credential)(?:$|_)/i;
const localPath = /(?:file:\/\/|\/Users\/|\/home\/|[A-Za-z]:\\Users\\)/;
const secretValue = /(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret)\s*[:=]|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}/i;

function publicSafetyErrors(value, path = "$") {
  const errors = [];
  if (Array.isArray(value)) {
    value.forEach((child, index) => errors.push(...publicSafetyErrors(child, `${path}[${index}]`)));
  } else if (value !== null && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      const normalized = key.replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase();
      const childPath = `${path}.${key}`;
      if (privateFields.has(normalized) || sensitiveKey.test(normalized)) {
        errors.push(`forbidden public field: ${childPath}`);
      }
      errors.push(...publicSafetyErrors(child, childPath));
    }
  } else if (typeof value === "string" && (localPath.test(value) || secretValue.test(value))) {
    errors.push(`sensitive or local-only string: ${path}`);
  }
  return errors;
}

function identityValue(value) {
  if (Array.isArray(value)) return value.map(identityValue);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort(compareText).map((key) => [key, identityValue(value[key])])
    );
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("run report identity requires finite numbers");
    const [mantissa, rawExponent] = value.toExponential(16).split("e");
    const exponent = Number.parseInt(rawExponent, 10);
    return `${mantissa}e${exponent >= 0 ? "+" : ""}${exponent}`;
  }
  return value;
}

function runReportId(report) {
  const {report_id: ignored, ...unsigned} = report;
  void ignored;
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(identityValue(unsigned)))
    .digest("hex")}`;
}

async function readRunReport(path, name, validator, kind) {
  let report;
  try {
    report = JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    throw new Error(`${name}: invalid ${kind} run report JSON`, {cause: error});
  }
  if (!validator(report)) throw schemaFailure(name, validator, `${kind} run report`);
  const safetyErrors = publicSafetyErrors(report);
  if (safetyErrors.length) {
    throw new Error(`${name}: ${kind} run report safety validation failed: ${safetyErrors.join("; ")}`);
  }
  if (kind === "published" && report.schema_version !== "2") {
    throw new Error(`${name}: published run report schema validation failed: version 2 required`);
  }
  if (report.schema_version === "2" && report.report_id !== runReportId(report)) {
    throw new Error(`${name}: ${kind} run report identity does not match its content`);
  }
  return report;
}

function combinedRunReports(publishedRuns, localRuns) {
  const combined = new Map();
  for (const report of [...publishedRuns, ...localRuns.filter((run) => run.schema_version === "2")]) {
    const previous = combined.get(report.run_id);
    if (previous === undefined) {
      combined.set(report.run_id, report);
      continue;
    }
    const comparison = compareText(report.updated_at, previous.updated_at);
    if (comparison > 0) {
      combined.set(report.run_id, report);
    } else if (comparison === 0 && report.report_id !== previous.report_id) {
      throw new Error(`${report.run_id}: run reports conflict at the same update time`);
    }
  }
  return [...combined.values()].sort((left, right) =>
    compareText(runReportSortKey(left), runReportSortKey(right))
  );
}

export async function loadPublicResults({
  resultsDirectory = resolve(repositoryRoot, "results"),
  publishedReportsDirectory,
  schemaPath = resolve(repositoryRoot, "policy", "Public_Result.schema.json"),
  runsDirectory = resolve(repositoryRoot, "runs", "generated"),
  runReportSchemaPath = resolve(repositoryRoot, "policy", "Run_Report.schema.json")
} = {}) {
  const schema = JSON.parse(await readFile(schemaPath, "utf8"));
  const validate = compileSchema(schema);
  const runReportSchema = JSON.parse(await readFile(runReportSchemaPath, "utf8"));
  const validateRunReport = compileSchema(runReportSchema);
  const finalized = [];
  const publishedDirectory = publishedReportsDirectory
    ?? (process.env.HARNESS_PUBLISHED_REPORTS_DIRECTORY?.trim()
      || resolve(repositoryRoot, "dashboard-data", "reports"));

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

  const publishedRuns = [];
  for (const entry of await resultEntries(publishedDirectory)) {
    publishedRuns.push(
      await readRunReport(
        resolve(publishedDirectory, entry.name),
        entry.name,
        validateRunReport,
        "published"
      )
    );
  }

  const localRuns = [];
  for (const entry of await localRunReportEntries(runsDirectory)) {
    let report;
    try {
      report = await readRunReport(
        entry.path,
        `${entry.directory}/Run_Report.json`,
        validateRunReport,
        "local"
      );
    } catch (error) {
      if (error?.cause?.code === "ENOENT") continue;
      throw error;
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
    schema_version: "2",
    results: finalized,
    run_reports: combinedRunReports(publishedRuns, localRuns),
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
