const SUPERPOWERS = Object.freeze({
  sourceName: "Superpowers",
  name: "Superpowers",
  kind: "Plugin",
  version: "6.3.0",
  commit: "b36e0829c6d0140e93cfef2ca599b1b07d4a7797",
  url: "https://github.com/obra/superpowers",
  description: "Structured workflows for discovery, planning, debugging, test-driven development, review, and branch completion."
});

function studioSource(commit, version = "1.0.0") {
  return Object.freeze({
    sourceName: "Studio Harness",
    name: "Studio Moser",
    kind: "Plugin collection",
    version,
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

function studioVersion({id, versionOrder, versionLabel = `v${versionOrder}`, predecessorId, commit, collectionVersion = "1.0.0", superpowers = true, startup = "Harness baseline instructions from the pinned collection", identity, extraIdentities = [], changeSummary, changeDetails, latest = false}) {
  const studio = studioSource(commit, collectionVersion);
  const layers = superpowers ? [studio, SUPERPOWERS] : [studio];
  return Object.freeze({
    id,
    family: "studio-moser",
    versionLabel,
    versionOrder,
    predecessorId,
    latest,
    state: "ready",
    sourceLabel: `Source commit ${commit.slice(0, 7)}`,
    changeSummary,
    changeDetails,
    layers,
    sources: layers,
    rubric: {mode: "enabled", description: "Frozen, reviewed personal model-routing rubric"},
    startup,
    delivery: COMMON_STUDIO_DELIVERY,
    identity,
    extraIdentities,
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
    // Claude Code delivery of the same empty bundle.
    extraIdentities: ["sha256:c4cd1d72d67f36caaa77f353351e2d96db3a1e7c4770ab226f73af10fe84e1b4"],
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
    id: "studio-moser-v5",
    versionOrder: 5,
    predecessorId: null,
    commit: "3fb970f32d2901b82e3d17c35dbe192604fc7762",
    identity: "sha256:7567e595abce3b09d87d72150e887c6ea9431bd784f60cc5ba174fb14ba08074",
    // Claude Code delivery of the same commit, with the rubric refreshed for Opus 5.5.
    extraIdentities: ["sha256:9bc3b03b4e15d5e45907d301a86a36bd4fb4cfb9389146a3d812bcc41789b124"],
    changeSummary: "Adopt the Lite direct-by-default harness used by the Quill pilot.",
    changeDetails: ["Defaults ordinary work to direct execution", "Retains task-matched specialist skills and personality guidance", "Keeps the frozen model-routing rubric available"],
    latest: false
  }),
  studioVersion({
    id: "studio-moser-v6",
    versionOrder: 6,
    predecessorId: "studio-moser-v5",
    commit: "75bf6c59ad9c87e7c91b6e537af471aee91cd931",
    collectionVersion: "2.0.0",
    superpowers: false,
    identity: "sha256:23674af8933438393e8a2c39a3831e30c4faca1f4eea52ee1c94a7899298c371",
    changeSummary: "Lighter startup, one delegate skill, and report and end-state rules, driven by the v5 benchmark.",
    changeDetails: ["Removes Superpowers and five domain plugins; most skills become slash-only or one-line", "Merges execute, review and computer-use into one delegate skill", "Adds ask-once, named end state, five-line Polish/Small reports and no delegation of small work", "Routing rubric falls back to Opus 5.5 at medium"],
    latest: true
  }),
  studioVersion({
    id: "studio-moser-v6-time-matters",
    versionOrder: 7,
    versionLabel: "v6 + time matters",
    predecessorId: "studio-moser-v6",
    commit: "75bf6c59ad9c87e7c91b6e537af471aee91cd931",
    collectionVersion: "2.0.0",
    superpowers: false,
    startup: "Harness baseline instructions plus one line: \"Time matters: reach the named end state in the fewest turns.\"",
    identity: "sha256:1af29ad6a4d4a2dbacc9c53a1bdbcbbee590c906bdff7329da6f7136b0c219e2",
    changeSummary: "v6 with one added startup line asking for the fewest turns, testing the Opus 5.5 'time matters' advice.",
    changeDetails: ["Identical to v6 except the added startup line", "Measures whether the line cuts turns and cost without losing correctness"]
  }),
  Object.freeze({
    id: "studio-personality-v1",
    family: "studio-personality",
    versionLabel: "v1",
    versionOrder: 1,
    predecessorId: null,
    latest: true,
    state: "ready",
    sourceLabel: "Startup guidance only",
    changeSummary: "Define a personality-only baseline that freezes one reviewed House Style snapshot per experiment.",
    changeDetails: ["No plugins", "No routing rubric", "One startup guidance file"],
    layers: [{name: "House Style snapshot", kind: "Startup file", version: "Frozen per experiment", description: "The exact reviewed communication instructions selected for that diagnostic."}],
    sources: [],
    rubric: {mode: "disabled", description: "No routing rubric"},
    startup: "One frozen House Style.md snapshot",
    delivery: ["The selected startup file is copied into the contender bundle", "No Studio Moser or Superpowers plugin is installed", "Each materialized snapshot receives its own content-derived identity"],
    identity: "sha256:603239729f7be3b2b61bc87ee4230adc929bb1e1bbdf7e1fe2592294a49385e5",
    identityNotes: ["Identity is created from the exact startup-file bytes and delivery configuration", "v1 is the House Style snapshot first run on Claude Code with Opus 5.5", "Editing the guidance creates a new baseline version"]
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
