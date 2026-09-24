import {cp, mkdir, readdir, rm} from "node:fs/promises";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";

const dashboardDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const stagingDirectory = resolve(dashboardDirectory, ".dist-staging");
const outputDirectory = resolve(dashboardDirectory, "dist");
const stagedEntries = await readdir(stagingDirectory);

await mkdir(outputDirectory, {recursive: true});

for (const entry of await readdir(outputDirectory)) {
  await rm(resolve(outputDirectory, entry), {force: true, recursive: true});
}

for (const entry of stagedEntries) {
  await cp(resolve(stagingDirectory, entry), resolve(outputDirectory, entry), {
    force: true,
    recursive: true
  });
}

await rm(stagingDirectory, {force: true, recursive: true});
