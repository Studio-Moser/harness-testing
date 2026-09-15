import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";

import {TOOLBOX_CATALOG, enrichCatalog} from "./Toolbox Catalog.js";

const here = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(here, "../../..");
const tests = await enrichCatalog(TOOLBOX_CATALOG, {repositoryRoot});

process.stdout.write(JSON.stringify({schemaVersion: 1, tests}));
