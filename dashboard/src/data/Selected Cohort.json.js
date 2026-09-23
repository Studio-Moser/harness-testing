import {readFile} from "node:fs/promises";
import {safetyErrors} from "./Published Results.json.js";

const path = process.env.HARNESS_SELECTED_COHORT?.trim();
const selection = path ? JSON.parse(await readFile(path, "utf8")) : null;
if (safetyErrors(selection).length) throw new Error("Unsafe observational cohort metadata");
process.stdout.write(JSON.stringify(selection));
