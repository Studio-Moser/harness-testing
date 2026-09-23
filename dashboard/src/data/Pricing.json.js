import {readFile} from "node:fs/promises";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(here, "../../..");
const PROVIDERS = {codex: "openai", claude: "anthropic"};
const FIELDS = ["input", "output", "cache_read", "cache_write"];

// Per-million-token list prices from the pinned [[models]] rows in Versions.toml, keyed
// "provider/model". Used to price each session of a trial; these are API-equivalent
// estimates, not bills.
export function parsePricing(text) {
  const pricing = {};
  for (const block of text.split(/^\[\[models\]\]\s*$/m).slice(1)) {
    const body = block.split(/^\[/m)[0];
    const value = (key) => body.match(new RegExp(`^${key}\\s*=\\s*"([^"]*)"`, "m"))?.[1];
    const provider = PROVIDERS[value("provider")];
    const model = value("model");
    if (!provider || !model) continue;
    const rates = {};
    for (const field of FIELDS) {
      const rate = Number(value(`${field}_usd_per_million_tokens`));
      if (Number.isFinite(rate)) rates[field] = rate;
    }
    pricing[`${provider}/${model}`] = rates;
  }
  return pricing;
}

export async function loadPricing() {
  return parsePricing(await readFile(resolve(repositoryRoot, "Versions.toml"), "utf8"));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.stdout.write(JSON.stringify(await loadPricing()));
}
