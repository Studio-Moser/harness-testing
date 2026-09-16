import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {dirname, resolve} from "node:path";
import test from "node:test";

import {
  HARNESS_CATALOG,
  HARNESS_FAMILIES,
  familyVersions,
  primaryHarnesses,
  validateHarnessCatalog
} from "../src/data/Harness Catalog.js";
import {renderHarnesses} from "../src/components/Harnesses.js";

const here = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(here, "../..");

class FakeElement {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.className = "";
    this._text = "";
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent ?? String(child)).join("");
  }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
}

function descendants(node) {
  return [node, ...node.children.flatMap((child) => child instanceof FakeElement ? descendants(child) : [])];
}

test("catalog distinguishes families and orders every version by explicit ancestry", () => {
  validateHarnessCatalog(HARNESS_CATALOG);

  assert.deepEqual(Object.keys(HARNESS_FAMILIES), [
    "nothing", "superpowers", "studio-moser", "studio-personality"
  ]);
  assert.equal(primaryHarnesses(HARNESS_CATALOG).length, 6);
  assert.deepEqual(familyVersions(HARNESS_CATALOG, "studio-moser").map(({id}) => id), [
    "studio-moser-v1",
    "studio-moser-v2",
    "studio-moser-v3",
    "studio-moser-v4"
  ]);
  assert.deepEqual(familyVersions(HARNESS_CATALOG, "studio-moser").map(({predecessorId}) => predecessorId), [
    null,
    "studio-moser-v1",
    "studio-moser-v2",
    "studio-moser-v3"
  ]);
  assert.equal(familyVersions(HARNESS_CATALOG, "studio-moser").at(-1).latest, true);
  assert.equal(HARNESS_FAMILIES["studio-personality"].role, "baseline");
  assert.equal(HARNESS_CATALOG.find(({id}) => id === "studio-personality-v1").state, "draft");
  assert.equal(HARNESS_CATALOG.filter(({state}) => state === "ready").length, 6);
  assert.equal(HARNESS_CATALOG.find(({id}) => id === "nothing-v1").layers.length, 0);
  assert.equal(HARNESS_CATALOG.find(({id}) => id === "superpowers-v1").layers.length, 1);
  assert.equal(HARNESS_CATALOG.find(({id}) => id === "studio-moser-v4").rubric.mode, "enabled");
});

test("shared dependency pins match Versions.toml and version identities are immutable", async () => {
  const versions = await readFile(resolve(repositoryRoot, "Versions.toml"), "utf8");

  for (const harness of HARNESS_CATALOG) {
    for (const source of harness.sources) {
      assert.match(source.commit, /^[0-9a-f]{40}$/);
      if (source.sourceName === "Superpowers") {
        assert.match(
          versions,
          new RegExp(`name = "Superpowers"[\\s\\S]*?version = "${source.version}"[\\s\\S]*?commit = "${source.commit}"`),
          harness.id
        );
      }
    }
    if (harness.identity !== null) assert.match(harness.identity, /^sha256:[0-9a-f]{64}$/);
  }
});

test("catalog validation rejects duplicate IDs and incomplete cards", () => {
  assert.throws(
    () => validateHarnessCatalog([...HARNESS_CATALOG, HARNESS_CATALOG[0]]),
    /duplicate id/
  );
  assert.throws(
    () => validateHarnessCatalog(HARNESS_CATALOG.map((item, index) => index === 0 ? {...item, changeSummary: ""} : item)),
    /nothing-v1: missing changeSummary/
  );
  assert.throws(
    () => validateHarnessCatalog(HARNESS_CATALOG.map((item) => item.id === "studio-moser-v3" ? {...item, predecessorId: "studio-moser-v1"} : item)),
    /studio-moser-v3: predecessor must be studio-moser-v2/
  );
});

test("Harnesses page exposes the comparison chain and structured details", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: (tag) => new FakeElement(tag)};
  try {
    const root = renderHarnesses(HARNESS_CATALOG);
    const nodes = descendants(root);
    const cards = nodes.filter((node) => node.attributes["data-harness-id"]);
    const summaries = nodes.filter((node) => node.tag === "summary").map((node) => node.textContent);

    assert.equal(root.attributes["aria-label"], "Harness catalog");
    assert.match(root.textContent, /6 ready harness versions, plus 1 draft baseline/);
    assert.deepEqual(cards.map((card) => card.attributes["data-harness-id"]), [
      "studio-moser-v4",
      "studio-moser-v3",
      "studio-moser-v2",
      "studio-moser-v1",
      "nothing-v1",
      "superpowers-v1",
      "studio-personality-v1"
    ]);
    assert.match(root.textContent, /Primary comparison/);
    assert.match(root.textContent, /Baselines3 harnesses/);
    assert.doesNotMatch(root.textContent, /Focused diagnostics/);
    assert.match(root.textContent, /Ready/);
    assert.match(root.textContent, /Draft/);
    assert.match(root.textContent, /Superpowers 6\.3\.0/);
    assert.match(root.textContent, /Studio Moser v4/);
    assert.match(root.textContent, /Source commit 771c633/);
    assert.doesNotMatch(root.textContent, /Collection 1\.0\.0 at/);
    assert.match(root.textContent, /4 versions/);
    assert.match(root.textContent, /Changes from previous version/);
    assert.match(root.textContent, /Deliver verification selection in startup instructions/);
    assert.match(root.textContent, /Latest/);
    assert.match(root.textContent, /content-derived identity/);
    assert.deepEqual(summaries.slice(0, 4), [
      "What it does",
      "Included layers",
      "How it is delivered",
      "Version identity"
    ]);
    assert.equal(summaries.length, HARNESS_CATALOG.length * 4);
    const baselines = nodes.find((node) => node.className.includes("harness-family-baselines"));
    assert.deepEqual(
      descendants(baselines)
        .filter((node) => node.attributes["data-harness-id"])
        .map((node) => node.attributes["data-harness-id"]),
      ["nothing-v1", "superpowers-v1", "studio-personality-v1"]
    );
  } finally {
    globalThis.document = previousDocument;
  }
});
