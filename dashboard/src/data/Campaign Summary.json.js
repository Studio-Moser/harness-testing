import {readdir, readFile, stat} from "node:fs/promises";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";

import {safetyErrors} from "./Published Results.json.js";

const here = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(here, "../../..");

// The newest local campaign summary, or the one named by HARNESS_CAMPAIGN_SUMMARY.
// A summary is derived from retained reports, so it carries no raw traces; it is still
// screened for local paths and secrets before it reaches the page.
export async function loadCampaignSummary() {
  const configured = process.env.HARNESS_CAMPAIGN_SUMMARY?.trim();
  let path = configured;
  if (!path) {
    const campaigns = resolve(repositoryRoot, "runs", "campaigns");
    let entries;
    try {
      entries = await readdir(campaigns, {withFileTypes: true});
    } catch (error) {
      if (error?.code === "ENOENT") return null;
      throw error;
    }
    let newest = null;
    for (const entry of entries.filter((item) => item.isDirectory())) {
      const candidate = resolve(campaigns, entry.name, "Summary.json");
      let info;
      try {
        info = await stat(candidate);
      } catch (error) {
        if (error?.code === "ENOENT") continue;
        throw error;
      }
      if (newest == null || info.mtimeMs > newest.mtimeMs) newest = {path: candidate, mtimeMs: info.mtimeMs};
    }
    if (newest == null) return null;
    path = newest.path;
  }
  const summary = JSON.parse(await readFile(path, "utf8"));
  const unsafe = safetyErrors(summary);
  if (unsafe.length) throw new Error(`campaign summary is not public-safe: ${unsafe.join("; ")}`);
  return summary;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.stdout.write(JSON.stringify(await loadCampaignSummary()));
}
