import {readdir, readFile, stat} from "node:fs/promises";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";

import {safetyErrors} from "./Published Results.json.js";

const here = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(here, "../../..");

// Every local campaign summary, newest first, or only the one named by
// HARNESS_CAMPAIGN_SUMMARY. Each campaign has one kickoff model; the page shows the one
// matching the selected model. A summary rebuilt from the same reports replaces the older
// copy. Summaries are derived from retained reports, so they carry no raw traces; each is
// still screened for local paths and secrets before it reaches the page.
export async function loadCampaignSummary() {
  const configured = process.env.HARNESS_CAMPAIGN_SUMMARY?.trim();
  let paths = configured ? [configured] : [];
  if (!configured) {
    const campaigns = resolve(repositoryRoot, "runs", "campaigns");
    let entries;
    try {
      entries = await readdir(campaigns, {withFileTypes: true});
    } catch (error) {
      if (error?.code === "ENOENT") return [];
      throw error;
    }
    const found = [];
    for (const entry of entries.filter((item) => item.isDirectory())) {
      const candidate = resolve(campaigns, entry.name, "Summary.json");
      try {
        found.push({path: candidate, mtimeMs: (await stat(candidate)).mtimeMs});
      } catch (error) {
        if (error?.code !== "ENOENT") throw error;
      }
    }
    paths = found.sort((left, right) => right.mtimeMs - left.mtimeMs).map(({path}) => path);
  }
  const summaries = [];
  const seen = new Set();
  for (const path of paths) {
    const summary = JSON.parse(await readFile(path, "utf8"));
    const unsafe = safetyErrors(summary);
    if (unsafe.length) throw new Error(`campaign summary is not public-safe: ${unsafe.join("; ")}`);
    const reports = JSON.stringify(summary.report_ids ?? null);
    if (seen.has(reports)) continue;
    seen.add(reports);
    summaries.push(summary);
  }
  return summaries;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.stdout.write(JSON.stringify(await loadCampaignSummary()));
}
