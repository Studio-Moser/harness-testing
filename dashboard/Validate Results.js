import {rm} from "node:fs/promises";
import {fileURLToPath} from "node:url";

import {loadCampaignSummary} from "./src/data/Campaign Summary.json.js";
import {loadPublishedReports} from "./src/data/Published Results.json.js";

// Observable production builds accept stale loader output. Never let that
// bypass the current privacy/schema validator or display an obsolete verdict.
await loadPublishedReports();
await loadCampaignSummary();
for (const name of ["Published Results.json", "Toolbox.json", "Campaign Summary.json"]) {
  await rm(fileURLToPath(new URL(`./src/.observablehq/cache/data/${name}`, import.meta.url)), {force: true});
}
