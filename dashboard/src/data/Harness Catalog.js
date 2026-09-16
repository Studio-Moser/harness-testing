const SUPERPOWERS = Object.freeze({
  sourceName: "Superpowers",
  name: "Superpowers",
  kind: "Plugin",
  version: "6.3.0",
  commit: "b36e0829c6d0140e93cfef2ca599b1b07d4a7797",
  url: "https://github.com/obra/superpowers",
  description: "Structured workflows for discovery, planning, debugging, test-driven development, review, and branch completion."
});

function studioSource(commit) {
  return Object.freeze({
    sourceName: "Studio Harness",
    name: "Studio Moser",
    kind: "Plugin collection",
    version: "1.0.0",
    commit,
    url: "https://github.com/Studio-Moser/skills-n-stuff",
    description: "The complete Studio Moser collection: Harness routing, specialist development workflows, PM operations, research, capture, and design tools."
  });
}

export const HARNESS_FAMILIES = Object.freeze({
  nothing: Object.freeze({
    name: "Nothing",
    shortName: "Bare runtime",
    role: "primary",
    stage: 0,
    purpose: "The provider-native coding agent with its normal built-in capabilities and no additional harness instructions.",
    question: "What can the same agent, model, task environment, and authority accomplish without an added harness?",
    effects: ["Preserves the provider's normal coding behavior", "Establishes the incremental value and cost reference", "Keeps native tools and delegation available"]
  }),
  superpowers: Object.freeze({
    name: "Superpowers",
    shortName: "Workflow baseline",
    role: "primary",
    stage: 1,
    purpose: "The bare runtime plus the pinned Superpowers plugin, with no Studio Moser collection or routing rubric.",
    question: "How much do general software-engineering workflows help before Studio Moser adds its own routing and specialist capabilities?",
    effects: ["Introduces explicit discovery, planning, debugging, testing, and review workflows", "Provides a stronger baseline than a bare agent alone", "Leaves model selection to the native runtime"]
  }),
  "studio-moser": Object.freeze({
    name: "Studio Moser",
    shortName: "Full collection",
    role: "primary",
    stage: 2,
    purpose: "The full Studio Moser collection, its declared Superpowers dependency, and a frozen personal model-routing rubric.",
    question: "How does each Studio Moser revision change correctness, process, and whole-tree efficiency compared with its explicit predecessor and the reference harnesses?",
    effects: ["Classifies work and selects proportionate workflows", "Makes specialist skills available for design, review, research, PM, capture, and execution", "Uses the frozen rubric for normal model and effort routing when the task warrants it"]
  }),
  "studio-personality": Object.freeze({
    name: "Studio personality only",
    shortName: "Communication baseline",
    role: "baseline",
    stage: 0,
    purpose: "The bare runtime plus one frozen Studio Moser house-style file, without plugins, skills, or model routing.",
    question: "Does Studio Moser's communication guidance change collaboration quality when engineering capabilities stay otherwise bare?",
    effects: ["Isolates tone, clarity, scope discipline, and completion communication", "Avoids attributing engineering workflows to writing guidance", "Does not replace a primary engineering contender"]
  })
});

const COMMON_STUDIO_DELIVERY = Object.freeze([
  "Every marketplace plugin and declared skill in the pinned collection is accounted for",
  "Superpowers is installed separately at its own immutable pin",
  "The private rubric snapshot is delivered only to the experiment bundle; credentials and unrelated personal state are excluded"
]);

const COMMON_STUDIO_IDENTITY = Object.freeze([
  "Identity covers both source trees, the full plugin and skill inventory, startup instructions, rubric bytes, and delivery configuration",
  "Changing any one of those inputs creates a new Studio Moser version",
  "The display label and test results do not affect identity"
]);

function studioVersion({id, versionOrder, predecessorId, commit, identity, changeSummary, changeDetails, latest = false}) {
  const studio = studioSource(commit);
  return Object.freeze({
    id,
    family: "studio-moser",
    versionLabel: `v${versionOrder}`,
    versionOrder,
    predecessorId,
    latest,
    state: "ready",
    sourceLabel: `Source commit ${commit.slice(0, 7)}`,
    changeSummary,
    changeDetails,
    layers: [studio, SUPERPOWERS],
    sources: [studio, SUPERPOWERS],
    rubric: {mode: "enabled", description: "Frozen, reviewed personal model-routing rubric"},
    startup: "Harness baseline instructions from the pinned collection",
    delivery: COMMON_STUDIO_DELIVERY,
    identity,
    identityNotes: COMMON_STUDIO_IDENTITY
  });
}

export const HARNESS_CATALOG = Object.freeze([
  Object.freeze({
    id: "nothing-v1",
    family: "nothing",
    versionLabel: "v1",
    versionOrder: 1,
    predecessorId: null,
    latest: true,
    state: "ready",
    sourceLabel: "No added harness",
    changeSummary: "Establish the bare provider runtime as the reference configuration.",
    changeDetails: ["No plugins", "No routing rubric", "No added startup files"],
    layers: [],
    sources: [],
    rubric: {mode: "disabled", description: "No routing rubric"},
    startup: "No added startup files",
    delivery: ["An empty harness bundle is delivered through the same comparison path", "Task resources, available executors, credentials, limits, and evaluator stay common", "The kickoff model controls only the root agent; normal native behavior remains available"],
    identity: "sha256:6b0b5c24b83e9a5f055fdbe207ad472605f9552c20c23e46e5e03d3f011af521",
    identityNotes: ["The empty effective bundle still receives a content-derived identity", "Changing shared test conditions does not create a new harness version", "The display name is descriptive and is not part of version identity"]
  }),
  Object.freeze({
    id: "superpowers-v1",
    family: "superpowers",
    versionLabel: "v1",
    versionOrder: 1,
    predecessorId: null,
    latest: true,
    state: "ready",
    sourceLabel: "Superpowers 6.3.0",
    changeSummary: "Add the pinned Superpowers workflow plugin to the bare runtime.",
    changeDetails: ["Adds general engineering workflows", "Keeps the routing rubric disabled", "Adds no Studio Moser startup rules"],
    layers: [SUPERPOWERS],
    sources: [SUPERPOWERS],
    rubric: {mode: "disabled", description: "No routing rubric"},
    startup: "No added startup files",
    delivery: ["The exact pinned plugin is installed through the provider's native plugin surface", "The same plugin contents are assembled for Codex or Claude", "No Studio Moser instructions or private configuration are mounted"],
    identity: "sha256:ffcf688e90c42843df70916681dda34d2d9bf838afa3200173cbc86dc5b782d7",
    identityNotes: ["Identity covers the pinned source tree, complete skill inventory, and provider delivery files", "A source or inventory change creates a different version", "The display name and test results do not affect identity"]
  }),
  studioVersion({
    id: "studio-moser-v1",
    versionOrder: 1,
    predecessorId: null,
    commit: "0004abb6180d82b90b342f88244998fd618963f0",
    identity: "sha256:45e8190c8e8d3577771ea1f1a1e1130eef5bb5c026facbd12bbe84c1529b3167",
    changeSummary: "Establish the first full-collection Studio Moser version in this catalog.",
    changeDetails: ["Full Studio Moser collection", "Pinned Superpowers dependency", "Frozen routing rubric"]
  }),
  studioVersion({
    id: "studio-moser-v2",
    versionOrder: 2,
    predecessorId: "studio-moser-v1",
    commit: "481a99a3fce47e7c1d7ae533cb007d2e95860fcd",
    identity: "sha256:4d7cac115fc866c56e2d9975cf5446db622379f826cc46e168d7e0ff5472a67f",
    changeSummary: "Require direct evidence before waiving independent review for public contract changes.",
    changeDetails: ["Strengthens the risk-gate review decision", "Requires named contract assertions and observed results", "Adds regression coverage for Lite mode"]
  }),
  studioVersion({
    id: "studio-moser-v3",
    versionOrder: 3,
    predecessorId: "studio-moser-v2",
    commit: "771c633a6a959bb03d4f0df2002280b81df5d6cd",
    identity: "sha256:b54f0eb5a341f745de39494c84129692a63bd3b067d03149b50ae576afb143bc",
    changeSummary: "Scope verification to repository-required and behavior-relevant checks.",
    changeDetails: ["Removes generic checklist behavior", "Requires availability checks before optional tools", "Keeps missing required checks visible as unmet gates"]
  }),
  studioVersion({
    id: "studio-moser-v4",
    versionOrder: 4,
    predecessorId: "studio-moser-v3",
    commit: "f989eb1b6cef1248fefa89f8de3f3c6349f330f2",
    identity: "sha256:fe632a155dbeb1028e319e725c115bb468dedbd8ccef659ec9514745deacb0cc",
    changeSummary: "Deliver verification selection in startup instructions.",
    changeDetails: ["Moves the verification rule into the baseline agent instructions", "Makes the rule available before skill selection", "Updates Lite-mode contract coverage"],
    latest: true
  }),
  Object.freeze({
    id: "studio-personality-v1",
    family: "studio-personality",
    versionLabel: "Template",
    versionOrder: 1,
    predecessorId: null,
    latest: true,
    state: "draft",
    sourceLabel: "Startup guidance only",
    changeSummary: "Define a personality-only baseline that freezes one reviewed House Style snapshot per experiment.",
    changeDetails: ["No plugins", "No routing rubric", "One startup guidance file"],
    layers: [{name: "House Style snapshot", kind: "Startup file", version: "Frozen per experiment", description: "The exact reviewed communication instructions selected for that diagnostic."}],
    sources: [],
    rubric: {mode: "disabled", description: "No routing rubric"},
    startup: "One frozen House Style.md snapshot",
    delivery: ["The selected startup file is copied into the contender bundle", "No Studio Moser or Superpowers plugin is installed", "Each materialized snapshot receives its own content-derived identity"],
    identity: null,
    identityNotes: ["This card is a baseline template, not one fixed materialized version", "Identity is created from the exact startup-file bytes and delivery configuration", "Editing the guidance creates a new baseline version"]
  })
]);

const REQUIRED_TEXT = ["id", "family", "versionLabel", "sourceLabel", "changeSummary", "startup"];
const REQUIRED_LISTS = ["changeDetails", "layers", "sources", "delivery", "identityNotes"];

export function familyVersions(catalog, family) {
  return catalog.filter((version) => version.family === family).sort((a, b) => a.versionOrder - b.versionOrder);
}

export function primaryHarnesses(catalog) {
  return catalog.filter(({family}) => HARNESS_FAMILIES[family]?.role === "primary");
}

export function validateHarnessCatalog(catalog) {
  if (!Array.isArray(catalog) || catalog.length === 0) throw new Error("Harness catalog must not be empty");
  const ids = new Set();
  for (const version of catalog) {
    const id = version?.id || "unknown";
    if (ids.has(id)) throw new Error(`${id}: duplicate id`);
    ids.add(id);
    for (const field of REQUIRED_TEXT) {
      if (typeof version[field] !== "string" || version[field].trim() === "") throw new Error(`${id}: missing ${field}`);
    }
    for (const field of REQUIRED_LISTS) {
      if (!Array.isArray(version[field])) throw new Error(`${id}: missing ${field}`);
    }
    if (version.changeDetails.length === 0) throw new Error(`${id}: missing changeDetails`);
    if (!HARNESS_FAMILIES[version.family]) throw new Error(`${id}: unsupported family`);
    if (!new Set(["ready", "draft"]).has(version.state)) throw new Error(`${id}: invalid state`);
    if (!Number.isInteger(version.versionOrder) || version.versionOrder < 1) throw new Error(`${id}: invalid versionOrder`);
    if (!version.rubric || !new Set(["enabled", "disabled"]).has(version.rubric.mode)) throw new Error(`${id}: invalid rubric`);
    if (version.identity !== null && !/^sha256:[0-9a-f]{64}$/.test(version.identity)) throw new Error(`${id}: invalid identity`);
  }

  for (const family of Object.keys(HARNESS_FAMILIES)) {
    const versions = familyVersions(catalog, family);
    for (const [index, version] of versions.entries()) {
      const expected = index === 0 ? null : versions[index - 1].id;
      if (version.predecessorId !== expected) throw new Error(`${version.id}: predecessor must be ${expected ?? "empty"}`);
    }
    if (versions.length && versions.filter(({latest}) => latest).length !== 1) throw new Error(`${family}: requires exactly one latest version`);
  }
}

validateHarnessCatalog(HARNESS_CATALOG);
