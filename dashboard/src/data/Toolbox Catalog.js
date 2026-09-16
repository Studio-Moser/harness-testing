import {access, readFile, readdir} from "node:fs/promises";
import {constants} from "node:fs";
import {join} from "node:path";

const DEEP_SWE_COMMIT = "8cae5984d5dd0ee37445beff0e928dc10c331116";
const APPROVED_IDS = new Set([
  "react-accent-polish",
  "static-pricing-copy-polish",
  "react-active-badge-count",
  "rust-quoted-value-parser",
  "static-accessible-disclosure",
  "react-grouped-ui-updates",
  "static-grouped-page-updates",
  "react-saved-view-feature",
  "rust-workspace-warning-summary",
  "happy-dom-abort-pending-body-reads",
  "quill-shared-toolbar-focus",
  "yjs-map-conflict-detection",
  "katex-multicolumn-array-spans",
  "wasmi-trap-coredumps",
  "pest-character-class-coalescing"
]);
const TYPES = new Set(["polish", "bug-fix", "feature"]);
const LEVELS = new Set([1, 2, 3, 4]);
const REQUIRED_TEXT = [
  "title",
  "purpose",
  "promptSummary",
  "setupSummary",
  "learningGoal"
];
const REQUIRED_LISTS = [
  "stack",
  "expectedProcess",
  "expectedHarnessBehavior",
  "verification",
  "existingTests"
];

function controlled(entry) {
  return {
    sourceKind: "controlled",
    sourceLabel: "Studio Moser fixture",
    repository: "Controlled task fixture",
    baseCommit: "Fixture digest pinned in task.toml",
    queued: false,
    ...entry
  };
}

function deepSwe(entry) {
  return {
    sourceKind: "deep-swe",
    sourceLabel: "DeepSWE real repository",
    deepSweCommit: DEEP_SWE_COMMIT,
    queued: false,
    ...entry,
    promptUrl: `https://github.com/datacurve-ai/deep-swe/blob/${DEEP_SWE_COMMIT}/tasks/${entry.id}/instruction.md`
  };
}

export const TOOLBOX_CATALOG = Object.freeze([
  controlled({
    id: "react-accent-polish",
    title: "React accent polish",
    type: "polish",
    level: 1,
    purpose: "Tests whether an agent can make one exact visual-token change without disturbing component behavior.",
    promptSummary: "Change one CSS custom property from the existing blue to a specified violet.",
    stack: ["React", "TypeScript", "CSS", "Vite"],
    taskPath: "tasks/workflow/react-accent-polish",
    setupSummary: "A small React fixture with one mutable CSS token and protected application, test, and build files.",
    existingTests: ["src/App.test.tsx", "scripts/Check_Token.mjs"],
    expectedProcess: ["Inspect the token definition", "Make the one-value edit", "Run the narrow token check"],
    expectedHarnessBehavior: ["Classify as polish", "Avoid unnecessary planning or delegation", "Select direct proof instead of a broad test cycle"],
    verification: ["Source-token check", "Protected-file hashes", "Separate correctness, workflow, and efficiency verifiers", "Five-case verifier QA"],
    learningGoal: "Whether the harness keeps a trivial polish request fast, precise, and proportionate."
  }),
  controlled({
    id: "static-pricing-copy-polish",
    title: "Static pricing-card polish",
    type: "polish",
    level: 1,
    purpose: "Tests a tiny copy-and-spacing polish request in a static page.",
    promptSummary: "Replace one pricing sentence and change one spacing token without altering other behavior.",
    stack: ["HTML", "CSS", "Node.js"],
    taskPath: "tasks/workflow/static-pricing-copy-polish",
    setupSummary: "A static pricing-card fixture with exact copy and CSS-token checks.",
    existingTests: ["test/Pricing_Card.test.js", "scripts/Check_Pricing_Card.mjs"],
    expectedProcess: ["Locate the card copy and spacing token", "Make two bounded edits", "Run the targeted pricing-card check"],
    expectedHarnessBehavior: ["Keep the work in the polish lane", "Use the existing test seam", "Avoid unrelated cleanup"],
    verification: ["Pricing-card source check", "Protected-file hashes", "Separate correctness, workflow, and efficiency verifiers", "Five-case verifier QA"],
    learningGoal: "Whether the harness handles a two-value visual edit without process overhead or collateral changes."
  }),
  controlled({
    id: "react-active-badge-count",
    title: "React active badge count",
    type: "bug-fix",
    level: 2,
    purpose: "Tests a focused selector bug fix with new regression coverage and protected existing tests.",
    promptSummary: "Exclude archived projects from the active badge even when their active flag is true, and add a new regression test.",
    stack: ["React", "TypeScript", "Vitest", "Vite"],
    taskPath: "tasks/workflow/react-active-badge-count",
    setupSummary: "A React dashboard fixture with a faulty domain selector and immutable existing tests.",
    existingTests: ["src/App.test.tsx"],
    expectedProcess: ["Reproduce the selector defect", "Trace all selector callers", "Add a new focused regression test", "Run the package test gate"],
    expectedHarnessBehavior: ["Enter a bug-fix workflow", "Require a failing regression before the fix", "Protect existing tests from edits"],
    verification: ["Behavioral selector tests", "New-test requirement", "Protected-file hashes", "Separate correctness, workflow, and efficiency verifiers", "Five-case verifier QA"],
    learningGoal: "Whether the harness drives root-cause diagnosis and credible regression proof for a small bug."
  }),
  controlled({
    id: "rust-quoted-value-parser",
    title: "Rust quoted-value parser",
    type: "bug-fix",
    level: 2,
    purpose: "Tests a focused parser repair where a quoted value contains the delimiter character.",
    promptSummary: "Make parse_line preserve the complete value in token=\"a=b\".",
    stack: ["Rust", "Cargo"],
    taskPath: "tasks/workflow/rust-quoted-value-parser",
    setupSummary: "A small Rust library with an existing parser and integration tests.",
    existingTests: ["tests/Quoted_Value.rs"],
    expectedProcess: ["Inspect the parser and its callers", "Add or run a named regression", "Fix delimiter handling at the shared parsing point", "Run the crate test gate"],
    expectedHarnessBehavior: ["Use systematic bug diagnosis", "Keep the change at the parser root cause", "Select Rust-native verification"],
    verification: ["Named parser regression", "Cargo package tests", "Protected-file hashes", "Separate correctness, workflow, and efficiency verifiers", "Five-case verifier QA"],
    learningGoal: "Whether the harness can diagnose a compact parsing bug and prove the exact boundary case."
  }),
  controlled({
    id: "static-accessible-disclosure",
    title: "Accessible disclosure controls",
    type: "bug-fix",
    level: 2,
    purpose: "Tests an accessibility repair that must keep mouse, keyboard, and ARIA state aligned.",
    promptSummary: "Make click, Enter, and Space toggle an FAQ answer while synchronizing aria-expanded and hidden.",
    stack: ["HTML", "JavaScript", "Node.js", "Accessibility"],
    taskPath: "tasks/workflow/static-accessible-disclosure",
    setupSummary: "A static FAQ fixture with behavioral and markup tests around one disclosure control.",
    existingTests: ["test/Disclosure.test.js", "test/Markup.test.js"],
    expectedProcess: ["Reproduce mouse and keyboard paths", "Inspect markup and event handling together", "Repair one shared state transition", "Run behavior and markup tests"],
    expectedHarnessBehavior: ["Treat accessibility behavior as correctness", "Test every requested input path", "Preserve semantic state"],
    verification: ["Keyboard and click behavior tests", "ARIA and hidden-state markup tests", "Protected-file hashes", "Separate correctness, workflow, and efficiency verifiers", "Five-case verifier QA"],
    learningGoal: "Whether the harness catches cross-input accessibility requirements instead of fixing only the click symptom."
  }),
  controlled({
    id: "react-grouped-ui-updates",
    title: "Grouped React UI polish",
    type: "polish",
    level: 3,
    purpose: "Tests whether three independent React presentation edits are handled as one coordinated polish batch.",
    promptSummary: "Change an accent token, empty-state heading, and card-gap token while limiting edits to those values.",
    stack: ["React", "TypeScript", "CSS", "Vite"],
    taskPath: "tasks/workflow/react-grouped-ui-updates",
    setupSummary: "A React dashboard fixture with three independent mutable presentation values.",
    existingTests: ["src/App.test.tsx", "scripts/Check_Token.mjs"],
    expectedProcess: ["Map all three requested values", "Batch the bounded source edits", "Run one final targeted gate"],
    expectedHarnessBehavior: ["Recognize a grouped polish task", "Avoid one workflow cycle per value", "Preserve the edit boundary"],
    verification: ["Exact-value checks", "Protected-file hashes", "Separate correctness, workflow, and efficiency verifiers", "Five-case verifier QA"],
    learningGoal: "Whether the harness can batch related low-risk edits without multiplying overhead."
  }),
  controlled({
    id: "static-grouped-page-updates",
    title: "Grouped static-page polish",
    type: "polish",
    level: 3,
    purpose: "Tests a coordinated static-page batch spanning copy, spacing, and semantic markup.",
    promptSummary: "Change the hero heading and section spacing, then wrap primary content in a main landmark.",
    stack: ["HTML", "CSS", "Node.js"],
    taskPath: "tasks/workflow/static-grouped-page-updates",
    setupSummary: "A static page fixture with exact content, token, and landmark checks.",
    existingTests: ["test/Page.test.js", "scripts/Check_Page.mjs"],
    expectedProcess: ["Locate the three independent targets", "Make one coordinated edit pass", "Run the page-level proof once"],
    expectedHarnessBehavior: ["Keep semantic markup inside the polish batch", "Use a proportionate final gate", "Avoid unrelated page redesign"],
    verification: ["Page structure and value tests", "Protected-file hashes", "Separate correctness, workflow, and efficiency verifiers", "Five-case verifier QA"],
    learningGoal: "Whether the harness coordinates cross-file static-page polish while respecting scope."
  }),
  controlled({
    id: "react-saved-view-feature",
    title: "Persisted React saved views",
    type: "feature",
    level: 3,
    purpose: "Tests a bounded stateful feature with persistence, restoration, and invalid-data fallback behavior.",
    promptSummary: "Persist all, active, and archived dashboard views in localStorage and restore them safely on reload.",
    stack: ["React", "TypeScript", "localStorage", "Vitest", "Vite"],
    taskPath: "tasks/workflow/react-saved-view-feature",
    setupSummary: "A React fixture with saved-view domain functions and focused tests already present.",
    existingTests: ["src/domain/Saved_View.test.ts", "src/domain/View_Filter.test.ts", "src/App.test.tsx"],
    expectedProcess: ["Clarify valid and invalid stored states", "Inspect the existing storage boundary", "Implement persistence and restoration", "Run focused domain tests and one final suite"],
    expectedHarnessBehavior: ["Use a feature workflow", "Preserve the existing storage abstraction", "Cover state transitions and fallback behavior"],
    verification: ["Saved-view domain tests", "View-filter tests", "Application tests", "Protected-file hashes", "Separate correctness, workflow, and efficiency verifiers", "Five-case verifier QA"],
    learningGoal: "Whether the harness turns a compact feature brief into complete state behavior and proportionate proof."
  }),
  controlled({
    id: "rust-workspace-warning-summary",
    title: "Rust workspace warning summary",
    type: "feature",
    level: 3,
    purpose: "Tests a coordinated feature propagated across a model crate, summary crate, and CLI output.",
    promptSummary: "Carry warning_count through event_model, summary, and summary_cli JSON without editing immutable regression tests.",
    stack: ["Rust", "Cargo workspace", "JSON CLI"],
    taskPath: "tasks/workflow/rust-workspace-warning-summary",
    setupSummary: "A three-crate Rust workspace with immutable regression tests at each relevant boundary.",
    existingTests: ["crates/event_model/tests/Event.rs", "crates/summary/tests/Warning_Count.rs", "crates/summary_cli/tests/Json_Output.rs"],
    expectedProcess: ["Trace the warning signal across crate boundaries", "Update each data shape and output layer", "Run focused crate checks", "Run one workspace gate"],
    expectedHarnessBehavior: ["Plan a coordinated multi-package change", "Respect immutable tests", "Verify both library and CLI contracts"],
    verification: ["Event-model tests", "Summary tests", "CLI JSON tests", "Protected-file hashes", "Separate correctness, workflow, and efficiency verifiers", "Five-case verifier QA"],
    learningGoal: "Whether the harness maintains a coherent data contract across a small multi-package feature."
  }),
  deepSwe({
    id: "happy-dom-abort-pending-body-reads",
    title: "Happy DOM shutdown semantics",
    type: "bug-fix",
    level: 4,
    purpose: "Tests a real-repository async lifecycle bug spanning body reads, navigation, disposal, and scheduled callbacks.",
    promptSummary: "Make interrupted Request, Response, and multipart reads reject with AbortError during shutdown while preserving successful and buffered reads.",
    stack: ["TypeScript", "Happy DOM", "Async I/O"],
    repository: "https://github.com/capricorn86/happy-dom",
    baseCommit: "82a0888cb2c87a6123e05424b528f8e8c9b3e426",
    setupSummary: "A pinned Happy DOM repository and separate verifier in an offline 2-CPU, 8-GB container.",
    existingTests: ["Repository test suite", "DeepSWE hidden verifier"],
    expectedProcess: ["Reproduce each shutdown path", "Trace ownership of pending reads and timers", "Design consistent abort semantics", "Add targeted regressions", "Run affected and repository-level tests", "Review lifecycle cleanup"],
    expectedHarnessBehavior: ["Use systematic debugging before editing", "Coordinate investigation and regression coverage", "Retain scope across multiple async subsystems"],
    verification: ["Existing repository tests", "Separate DeepSWE verifier", "Frozen base commit", "Patch artifact review"],
    learningGoal: "Whether the harness materially improves investigation and correctness on a difficult cross-cutting bug."
  }),
  deepSwe({
    id: "quill-shared-toolbar-focus",
    title: "Shared toolbar across Quill editors",
    type: "feature",
    level: 4,
    purpose: "Tests a complex UI feature with shared ownership, focus routing, dynamic controls, cleanup, and disabled states.",
    promptSummary: "Allow several Quill editors to share one toolbar while routing state and actions to the active live editor without duplicate UI or stale wiring.",
    stack: ["TypeScript", "Quill", "DOM", "UI state"],
    repository: "https://github.com/slab/quill",
    baseCommit: "539cbffd0a13b18e9c65eb84dd35e6596e403158",
    queued: true,
    setupSummary: "A pinned Quill repository, cached Harbor task wrapper, and separate verifier in an offline 2-CPU, 8-GB container.",
    existingTests: ["Repository test suite", "DeepSWE hidden verifier"],
    expectedProcess: ["Map toolbar and theme ownership", "Brainstorm active-editor semantics", "Design shared lifecycle state", "Implement focus, cleanup, disabled, and mutation paths", "Add focused regressions", "Run relevant suites and review"],
    expectedHarnessBehavior: ["Use feature discovery and design before implementation", "Maintain a multi-case requirement checklist", "Apply browser-oriented QA and review"],
    verification: ["Existing Quill tests", "Separate DeepSWE verifier", "Frozen base commit", "Patch artifact review"],
    learningGoal: "Whether the harness helps an agent sustain design coherence across a large, interaction-heavy feature."
  }),
  deepSwe({
    id: "yjs-map-conflict-detection",
    title: "Yjs map conflict detection",
    type: "feature",
    level: 4,
    purpose: "Tests a distributed-data feature requiring deterministic conflict semantics, atomic error behavior, and public reporting APIs.",
    promptSummary: "Add allow, collect, and error policies for ambiguous same-key map writes with deterministic conflict records and summaries.",
    stack: ["JavaScript", "Yjs", "CRDTs", "Distributed state"],
    repository: "https://github.com/yjs/yjs",
    baseCommit: "7795050a749bd1111cbbdd9d0219b27226a8e710",
    setupSummary: "A pinned Yjs repository and separate verifier in an offline 2-CPU, 8-GB container.",
    existingTests: ["Repository test suite", "DeepSWE hidden verifier"],
    expectedProcess: ["Study transaction and merged-update semantics", "Design conflict identity and deterministic resolution", "Implement atomic policy handling", "Add API and integration coverage", "Run convergence and regression tests", "Review public behavior"],
    expectedHarnessBehavior: ["Front-load architecture and invariants", "Track a wide acceptance contract", "Use specialist review for distributed-state correctness"],
    verification: ["Existing Yjs tests", "Separate DeepSWE verifier", "Frozen base commit", "Patch artifact review"],
    learningGoal: "Whether the harness improves reasoning about ambiguous distributed writes and atomic public behavior."
  }),
  deepSwe({
    id: "katex-multicolumn-array-spans",
    title: "KaTeX multicolumn array spans",
    type: "feature",
    level: 4,
    purpose: "Tests a parser-and-renderer feature spanning validation, layout, HTML output, and MathML output.",
    promptSummary: "Add multicolumn spans to array-like environments with strict validation, alignment overrides, vertical-rule handling, and MathML attributes.",
    stack: ["JavaScript", "KaTeX", "Parser", "HTML", "MathML"],
    repository: "https://github.com/KaTeX/KaTeX",
    baseCommit: "89bede495dc2c85e1c57ba627a18526f71d57396",
    setupSummary: "A pinned KaTeX repository and separate verifier in an offline 2-CPU, 8-GB container.",
    existingTests: ["Repository test suite", "DeepSWE hidden verifier"],
    expectedProcess: ["Trace parser and array layout models", "Design span validation and row-local rules", "Implement HTML and MathML output", "Add parser and render regressions", "Run affected and full tests", "Review output parity"],
    expectedHarnessBehavior: ["Coordinate work across parse and render layers", "Maintain an environment-and-error matrix", "Use output-specific verification"],
    verification: ["Existing KaTeX tests", "Separate DeepSWE verifier", "Frozen base commit", "Patch artifact review"],
    learningGoal: "Whether the harness keeps a syntax feature consistent across validation and multiple render targets."
  }),
  deepSwe({
    id: "wasmi-trap-coredumps",
    title: "wasmi trap coredumps",
    type: "feature",
    level: 4,
    purpose: "Tests a systems feature with binary-format rules, runtime stack capture, re-entrant execution, memory, globals, and configuration APIs.",
    promptSummary: "Generate opt-in standards-shaped Wasm coredumps for traps and expose their bytes on errors.",
    stack: ["Rust", "wasmi", "WebAssembly", "Binary encoding"],
    repository: "https://github.com/wasmi-labs/wasmi",
    baseCommit: "e1f76e285b9ad68a952b7cf5297bbb7ab91e6028",
    setupSummary: "A pinned wasmi repository and separate verifier in an offline 2-CPU, 8-GB container.",
    existingTests: ["Repository test suite", "DeepSWE hidden verifier"],
    expectedProcess: ["Research the coredump wire format", "Map runtime frame, instance, memory, and global state", "Design capture across re-entrant stacks", "Implement encoding and configuration", "Add binary and execution regressions", "Run broad Rust verification and review"],
    expectedHarnessBehavior: ["Call for domain research before coding", "Split substantial independent investigation when useful", "Enforce format-level and runtime-level proof"],
    verification: ["Existing wasmi tests", "Separate DeepSWE verifier", "Frozen base commit", "Patch artifact review"],
    learningGoal: "Whether the harness helps manage a specification-heavy systems feature without losing binary or runtime edge cases."
  }),
  deepSwe({
    id: "pest-character-class-coalescing",
    title: "pest character-class coalescing",
    type: "feature",
    level: 4,
    purpose: "Tests an optimizer feature involving new IR variants, ordered rewrite rules, range normalization, and negated predicates.",
    promptSummary: "Coalesce qualifying choice chains into merged character classes as a final top-down optimizer pass.",
    stack: ["Rust", "pest", "Parser optimizer", "Intermediate representation"],
    repository: "https://github.com/pest-parser/pest",
    baseCommit: "79dd30d11aab6f0fba3cd79bd48f456209b966b3",
    setupSummary: "A pinned pest repository and separate verifier in an offline 2-CPU, 8-GB container.",
    existingTests: ["Repository test suite", "DeepSWE hidden verifier"],
    expectedProcess: ["Understand optimizer ordering and IR consumers", "Design qualification and merge invariants", "Implement new expression variants and top-down pass", "Add positive, partial-run, case-folding, and negation tests", "Run optimizer and workspace suites", "Review semantic preservation"],
    expectedHarnessBehavior: ["Use design work for optimizer invariants", "Track the transformation matrix", "Demand semantic and ordering regressions"],
    verification: ["Existing pest tests", "Separate DeepSWE verifier", "Frozen base commit", "Patch artifact review"],
    learningGoal: "Whether the harness improves disciplined implementation of a broad compiler-style transformation."
  })
].map((entry) => Object.freeze(entry)));

export function validateCatalog(entries) {
  if (!Array.isArray(entries) || entries.length !== 15) {
    throw new Error(`Toolbox catalog must contain exactly 15 entries; received ${entries?.length ?? "invalid"}`);
  }

  const ids = new Set();
  for (const entry of entries) {
    const id = entry?.id || "unknown";
    if (ids.has(id)) throw new Error(`${id}: duplicate id`);
    ids.add(id);
    if (!APPROVED_IDS.has(id)) throw new Error(`${id}: not in the Toolbox allowlist`);
    if (!TYPES.has(entry.type)) throw new Error(`${id}: unsupported type`);
    if (!LEVELS.has(entry.level)) throw new Error(`${id}: unsupported level`);
    for (const field of REQUIRED_TEXT) {
      if (typeof entry[field] !== "string" || entry[field].trim() === "") {
        throw new Error(`${id}: missing ${field}`);
      }
    }
    for (const field of REQUIRED_LISTS) {
      if (!Array.isArray(entry[field]) || entry[field].length === 0) {
        throw new Error(`${id}: missing ${field}`);
      }
    }
    if (!new Set(["controlled", "deep-swe"]).has(entry.sourceKind)) {
      throw new Error(`${id}: unsupported sourceKind`);
    }
    for (const field of ["sourceLabel", "repository", "baseCommit"]) {
      if (typeof entry[field] !== "string" || entry[field].trim() === "") {
        throw new Error(`${id}: missing ${field}`);
      }
    }
    if (entry.sourceKind === "controlled") {
      if (!entry.taskPath) throw new Error(`${id}: missing taskPath`);
    } else {
      if (entry.deepSweCommit !== DEEP_SWE_COMMIT) {
        throw new Error(`${id}: DeepSWE commit is not pinned`);
      }
      const expectedUrl = `https://github.com/datacurve-ai/deep-swe/blob/${DEEP_SWE_COMMIT}/tasks/${id}/instruction.md`;
      if (entry.promptUrl !== expectedUrl) throw new Error(`${id}: missing pinned promptUrl`);
    }
  }
}

function numberInSection(toml, section, key) {
  const sectionMatch = toml.match(new RegExp(`\\[${section}\\]([\\s\\S]*?)(?=\\n\\[|$)`));
  const valueMatch = sectionMatch?.[1].match(new RegExp(`^${key}\\s*=\\s*([0-9.]+)`, "m"));
  if (!valueMatch) throw new Error(`task.toml: missing ${section}.${key}`);
  return Number(valueMatch[1]);
}

function stringInSection(toml, section, key) {
  const sectionMatch = toml.match(new RegExp(`\\[${section}\\]([\\s\\S]*?)(?=\\n\\[|$)`));
  const valueMatch = sectionMatch?.[1].match(new RegExp(`^${key}\\s*=\\s*"([^"]*)"`, "m"));
  if (!valueMatch) throw new Error(`task.toml: missing ${section}.${key}`);
  return valueMatch[1];
}

function arrayInSection(toml, section, key) {
  const sectionMatch = toml.match(new RegExp(`\\[${section}\\]([\\s\\S]*?)(?=\\n\\[|$)`));
  const valueMatch = sectionMatch?.[1].match(new RegExp(`^${key}\\s*=\\s*(\\[[^\\n]*\\])`, "m"));
  if (!valueMatch) throw new Error(`task.toml: missing ${section}.${key}`);
  return JSON.parse(valueMatch[1]);
}

async function exists(path) {
  try {
    await access(path, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

async function deepSweMaterialized(repositoryRoot, id) {
  const datasets = join(repositoryRoot, ".cache", "deepswe", "datasets");
  if (!(await exists(datasets))) return false;
  for (const digest of await readdir(datasets)) {
    if (await exists(join(datasets, digest, "tasks", id, "task.toml"))) return true;
  }
  return false;
}

async function requiredText(path, id) {
  try {
    return (await readFile(path, "utf8")).trim();
  } catch (error) {
    throw new Error(`${id}: missing ${path.split("/").at(-1)}`, {cause: error});
  }
}

async function enrichControlled(entry, repositoryRoot) {
  const root = join(repositoryRoot, entry.taskPath);
  const prompt = await requiredText(join(root, "Comparison Instruction.md"), entry.id);
  const taskToml = await requiredText(join(root, "task.toml"), entry.id);
  const protectedFiles = JSON.parse(await requiredText(join(root, "tests", "Protected_Files.json"), entry.id));
  const qa = JSON.parse(await requiredText(join(root, "tests", "QA.json"), entry.id));

  return {
    ...entry,
    prompt: {kind: "local", exact: prompt, url: null},
    source: {
      label: entry.sourceLabel,
      repository: entry.repository,
      baseCommit: stringInSection(taskToml, "metadata", "fixture_digest")
    },
    apparatus: {
      protectedFiles: Object.keys(protectedFiles.files ?? {}).sort(),
      mutableFiles: Object.keys(protectedFiles.mutable_files ?? {}).sort(),
      qaCaseCount: Object.keys(qa.cases ?? {}).length,
      hasReferenceSolution: await exists(join(root, "solution", "solve.sh")),
      hasCorrectnessCheck: await exists(join(root, "tests", "reward", "Correctness.py")),
      hasWorkflowCheck: await exists(join(root, "tests", "workflow", "Final_Gate.py")),
      hasEfficiencyCheck: await exists(join(root, "tests", "efficiency", "Testing_Churn.py"))
    },
    limits: {
      agentTimeoutSeconds: numberInSection(taskToml, "agent", "timeout_sec"),
      verifierTimeoutSeconds: numberInSection(taskToml, "verifier", "timeout_sec"),
      network: "No external network hosts allowed"
    },
    environment: {
      workdir: stringInSection(taskToml, "environment", "workdir"),
      verifierIsolation: stringInSection(taskToml, "verifier", "environment_mode"),
      agent: {
        cpus: numberInSection(taskToml, "environment", "cpus"),
        memoryMb: numberInSection(taskToml, "environment", "memory_mb"),
        storageMb: numberInSection(taskToml, "environment", "storage_mb")
      },
      verifier: {
        cpus: numberInSection(taskToml, "verifier.environment", "cpus"),
        memoryMb: numberInSection(taskToml, "verifier.environment", "memory_mb"),
        storageMb: numberInSection(taskToml, "verifier.environment", "storage_mb")
      },
      mcpServers: arrayInSection(taskToml, "environment", "mcp_servers")
    },
    setupState: {defined: true, materialized: true, queued: entry.queued}
  };
}

async function enrichDeepSwe(entry, repositoryRoot) {
  return {
    ...entry,
    prompt: {kind: "upstream", exact: null, url: entry.promptUrl},
    source: {label: entry.sourceLabel, repository: entry.repository, baseCommit: entry.baseCommit},
    apparatus: {
      protectedFiles: [],
      mutableFiles: [],
      qaCaseCount: null,
      hasReferenceSolution: false,
      hasCorrectnessCheck: true,
      hasWorkflowCheck: false,
      hasEfficiencyCheck: false
    },
    limits: {
      agentTimeoutSeconds: 5400,
      verifierTimeoutSeconds: 1800,
      network: "No internet access"
    },
    environment: {
      workdir: "/app",
      verifierIsolation: "separate",
      agent: {cpus: 2, memoryMb: 8192, storageMb: 20480},
      verifier: {cpus: 2, memoryMb: 8192, storageMb: 20480},
      mcpServers: []
    },
    setupState: {
      defined: true,
      materialized: await deepSweMaterialized(repositoryRoot, entry.id),
      queued: entry.queued
    }
  };
}

export async function enrichCatalog(entries, {repositoryRoot}) {
  validateCatalog(entries);
  return Promise.all(entries.map((entry) =>
    entry.sourceKind === "controlled"
      ? enrichControlled(entry, repositoryRoot)
      : enrichDeepSwe(entry, repositoryRoot)
  ));
}
