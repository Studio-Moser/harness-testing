import {createHash} from "node:crypto";
import {readdir, readFile} from "node:fs/promises";
import {dirname, resolve} from "node:path";
import {fileURLToPath, pathToFileURL} from "node:url";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const here = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(here, "../../..");
const privateFields = new Set([
  "command_output", "env", "environment", "environment_variables", "extra", "prompt",
  "prompts", "reasoning", "reasoning_content", "tool_output", "trajectory", "trajectories"
]);
const sensitiveKey = /(?:^|_)(?:api_key|access_token|refresh_token|auth_token|authorization|password|secret|credential)(?:$|_)/i;
const localPath = /(?:file:\/\/|\/Users\/|\/home\/|[A-Za-z]:\\Users\\)/;
const secretValue = /(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret)\s*[:=]|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}/i;

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function identityValue(value) {
  if (Array.isArray(value)) return value.map(identityValue);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort(compareText).map((key) => [key, identityValue(value[key])]));
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("run report identity requires finite numbers");
    const [mantissa, rawExponent] = value.toExponential(16).split("e");
    const exponent = Number.parseInt(rawExponent, 10);
    return `${mantissa}e${exponent >= 0 ? "+" : ""}${exponent}`;
  }
  return value;
}

function reportId(report) {
  const {report_id: ignored, ...unsigned} = report;
  void ignored;
  return `sha256:${createHash("sha256").update(JSON.stringify(identityValue(unsigned))).digest("hex")}`;
}

function safetyErrors(value, path = "$") {
  const errors = [];
  if (Array.isArray(value)) {
    value.forEach((child, index) => errors.push(...safetyErrors(child, `${path}[${index}]`)));
  } else if (value !== null && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      const normalized = key.replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase();
      const childPath = `${path}.${key}`;
      if (privateFields.has(normalized) || sensitiveKey.test(normalized)) errors.push(`forbidden public field: ${childPath}`);
      errors.push(...safetyErrors(child, childPath));
    }
  } else if (typeof value === "string" && (localPath.test(value) || secretValue.test(value))) {
    errors.push(`sensitive or local-only string: ${path}`);
  }
  return errors;
}

async function defaultReportsDirectory() {
  const configured = process.env.HARNESS_PUBLISHED_REPORTS_DIRECTORY?.trim();
  if (configured) return configured;
  return resolve(repositoryRoot, "dashboard-data", "reports");
}

export async function loadPublishedReports({
  reportsDirectory,
  schemaPath = resolve(repositoryRoot, "policy", "Run_Report.schema.json")
} = {}) {
  const schema = JSON.parse(await readFile(schemaPath, "utf8"));
  const ajv = new Ajv2020({allErrors: true, strict: true});
  addFormats(ajv);
  const validate = ajv.compile(schema);
  const directory = reportsDirectory ?? await defaultReportsDirectory();
  let entries;
  try {
    entries = await readdir(directory, {withFileTypes: true});
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }

  const reportsByRun = new Map();
  for (const entry of entries.filter((item) => item.isFile() && item.name.endsWith(".json")).sort((left, right) => compareText(left.name, right.name))) {
    let report;
    try {
      report = JSON.parse(await readFile(resolve(directory, entry.name), "utf8"));
    } catch (error) {
      throw new Error(`${entry.name}: invalid run report JSON`, {cause: error});
    }
    if (!validate(report)) {
      const details = (validate.errors ?? []).map((error) => `${error.instancePath || "$"} ${error.message}`).join("; ");
      throw new Error(`${entry.name}: schema validation failed: ${details}`);
    }
    const unsafe = safetyErrors(report);
    if (unsafe.length) throw new Error(`${entry.name}: public safety validation failed: ${unsafe.join("; ")}`);
    if (report.report_id != null && report.report_id !== reportId(report)) {
      throw new Error(`${entry.name}: report identity does not match its content`);
    }
    const previous = reportsByRun.get(report.run_id);
    if (previous == null || compareText(previous.updated_at, report.updated_at) < 0) {
      reportsByRun.set(report.run_id, report);
    } else if (previous.updated_at === report.updated_at && previous.report_id !== report.report_id) {
      throw new Error(`${report.run_id}: run reports conflict at the same update time`);
    }
  }
  return [...reportsByRun.values()].sort((left, right) => compareText(
    `${left.updated_at}\0${left.run_id}`,
    `${right.updated_at}\0${right.run_id}`
  ));
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) process.stdout.write(JSON.stringify(await loadPublishedReports()));
