import assert from "node:assert/strict";
import test from "node:test";

import {
  facetCounts,
  filterTests,
  groupTests,
  renderToolbox,
  selectionFromSearch,
  selectionUrl
} from "../src/components/Toolbox.js";

const tests = [
  {id: "b", title: "Bravo", type: "bug-fix", level: 2},
  {id: "a", title: "Alpha", type: "polish", level: 1},
  {id: "d", title: "Delta", type: "bug-fix", level: 2},
  {id: "c", title: "Charlie", type: "feature", level: 4}
];

test("type and level filters combine as an intersection", () => {
  assert.deepEqual(
    filterTests(tests, {type: "bug-fix", level: 2}).map(({id}) => id),
    ["b", "d"]
  );
  assert.deepEqual(filterTests(tests, {type: "polish", level: 2}), []);
});

test("facet counts respond to the other dimension and preserve zero coverage", () => {
  const counts = facetCounts(tests, {type: "polish", level: 2});

  assert.equal(counts.overlap, 0);
  assert.deepEqual(counts.types, {all: 2, polish: 0, "bug-fix": 2, feature: 0});
  assert.deepEqual(counts.levels, {all: 1, 1: 1, 2: 0, 3: 0, 4: 0});
});

test("query parameters round-trip and invalid values fall back to All", () => {
  assert.deepEqual(selectionFromSearch("?type=bug-fix&level=2"), {type: "bug-fix", level: 2});
  assert.deepEqual(selectionFromSearch("?type=nope&level=9"), {type: "all", level: "all"});
  assert.deepEqual(selectionFromSearch("?type=feature"), {type: "feature", level: "all"});
  assert.equal(selectionUrl({type: "feature", level: 4}), "?type=feature&level=4");
  assert.equal(selectionUrl({type: "all", level: "all"}), "?");
});

test("groups are level-ascending with alphabetical cards", () => {
  assert.deepEqual(groupTests(tests).map((group) => [group.level, group.tests.map(({id}) => id)]), [
    [1, ["a"]],
    [2, ["b", "d"]],
    [4, ["c"]]
  ]);
});

class FakeElement {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this._text = "";
    this.className = "";
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent ?? String(child)).join("");
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this._text = ""; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  click() { this.listeners.click?.({currentTarget: this}); }
}

function descendants(node) {
  return [node, ...node.children.flatMap((child) => child instanceof FakeElement ? descendants(child) : [])];
}

function toolboxFixture() {
  const common = {
    purpose: "Purpose",
    promptSummary: "Prompt summary",
    stack: ["JavaScript"],
    setupSummary: "Setup summary",
    existingTests: ["Existing test"],
    expectedProcess: ["Inspect", "Test"],
    expectedHarnessBehavior: ["Choose a focused workflow"],
    verification: ["Verifier", "Five-case verifier QA"],
    learningGoal: "Learning goal",
    limits: {agentTimeoutSeconds: 900, verifierTimeoutSeconds: 180, network: "No internet"},
    apparatus: {
      protectedFiles: ["package.json"],
      mutableFiles: ["src/index.js"],
      qaCaseCount: 5,
      hasReferenceSolution: true,
      hasCorrectnessCheck: true,
      hasWorkflowCheck: true,
      hasEfficiencyCheck: true
    }
  };

  return [
    {
      ...common,
      id: "controlled-test",
      title: "Controlled test",
      type: "bug-fix",
      level: 2,
      sourceKind: "controlled",
      source: {label: "Studio Moser fixture", repository: "Controlled task fixture", baseCommit: "Pinned digest"},
      prompt: {kind: "local", exact: "Exact local task brief.", url: null},
      setupState: {defined: true, materialized: true, queued: false}
    },
    {
      ...common,
      id: "upstream-test",
      title: "Upstream test",
      type: "feature",
      level: 4,
      sourceKind: "deep-swe",
      source: {label: "DeepSWE real repository", repository: "https://github.com/example/repo", baseCommit: "abc123"},
      prompt: {kind: "upstream", exact: null, url: "https://github.com/example/repo/blob/abc123/instruction.md"},
      setupState: {defined: true, materialized: false, queued: false}
    }
  ];
}

test("rendered Toolbox exposes accessible filters and all structured card sections", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: (tag) => new FakeElement(tag)};
  try {
    const location = {search: "?type=bug-fix&level=2", pathname: "/", hash: ""};
    const root = renderToolbox(toolboxFixture(), {location, history: {replaceState() {}}});
    const nodes = descendants(root);
    const pressed = nodes.filter((node) => node.attributes["aria-pressed"] === "true");

    assert.equal(root.tag, "section");
    assert.equal(root.attributes["aria-label"], "Harness Test Toolbox");
    assert.deepEqual(pressed.map((node) => node.attributes["data-value"]), ["bug-fix", "2"]);
    assert.match(root.textContent, /2 Harness Tests/);
    assert.match(root.textContent, /1 matching test/);
    assert.match(root.textContent, /L2Focused/);
    assert.deepEqual(
      nodes.filter((node) => node.tag === "summary").map((node) => node.textContent),
      ["What it tests", "Task brief", "Test setup", "Expected agent process", "Verification", "What we learn"]
    );
    assert.match(root.textContent, /Exact local task brief\./);
    assert.equal(root.textContent.match(/(?:Five|5)-case verifier QA/g)?.length, 1);
    assert.equal(nodes.filter((node) => node.tag === "details").length, 6);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("zero coverage keeps every filter available and explains the gap", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: (tag) => new FakeElement(tag)};
  try {
    const location = {search: "?type=polish&level=2", pathname: "/", hash: ""};
    const root = renderToolbox(toolboxFixture(), {location, history: {replaceState() {}}});
    const buttons = descendants(root).filter((node) => node.tag === "button");

    assert.equal(buttons.filter((button) => button.attributes["data-filter"] === "type").length, 4);
    assert.equal(buttons.filter((button) => button.attributes["data-filter"] === "level").length, 5);
    assert.match(root.textContent, /No Harness Tests cover this combination yet/);
    assert.match(root.textContent, /Polish0/);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("filter clicks update state, cards, and the bookmarkable URL", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: (tag) => new FakeElement(tag)};
  try {
    const replaced = [];
    const location = {search: "", pathname: "/toolbox", hash: "#catalog"};
    const root = renderToolbox(toolboxFixture(), {
      location,
      history: {replaceState(_state, _title, url) { replaced.push(url); }}
    });
    const feature = descendants(root).find((node) => node.attributes["data-value"] === "feature");
    feature.click();

    assert.equal(replaced.at(-1), "/toolbox?type=feature#catalog");
    assert.match(root.textContent, /Upstream test/);
    assert.doesNotMatch(root.textContent, /Controlled test/);
    const link = descendants(root).find((node) => node.tag === "a" && node.attributes.href);
    assert.equal(link.attributes.href, "https://github.com/example/repo/blob/abc123/instruction.md");
    assert.equal(link.attributes.rel, "noreferrer");
  } finally {
    globalThis.document = previousDocument;
  }
});
