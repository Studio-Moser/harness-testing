import {readFile, rm} from "node:fs/promises";
import {fileURLToPath} from "node:url";

import {loadPublishedReports, safetyErrors} from "./src/data/Published Results.json.js";
import {selectCohort} from "./src/data/Selected Cohort.js";

// Observable production builds accept stale loader output. Never let that
// bypass the current privacy/schema validator or display an obsolete cohort.
const reports = await loadPublishedReports();
if (process.env.HARNESS_SELECTED_COHORT?.trim()) {
  const selection = JSON.parse(await readFile(process.env.HARNESS_SELECTED_COHORT, "utf8"));
  if (safetyErrors(selection).length) throw new Error("Unsafe observational cohort metadata");
  selectCohort(reports, selection);
}
for (const name of ["Published Results.json", "Toolbox.json", "Selected Cohort.json"]) {
  await rm(fileURLToPath(new URL(`./src/.observablehq/cache/data/${name}`, import.meta.url)), {force: true});
}
