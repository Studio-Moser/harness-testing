const TYPES = ["polish", "bug-fix", "feature"];
const LEVELS = [1, 2, 3, 4];

export function selectionFromSearch(search) {
  const params = new URLSearchParams(search);
  const type = TYPES.includes(params.get("type")) ? params.get("type") : "all";
  const levelValue = Number(params.get("level"));
  const level = LEVELS.includes(levelValue) ? levelValue : "all";
  return {type, level};
}

export function selectionUrl(selection) {
  const params = new URLSearchParams();
  if (selection.type !== "all") params.set("type", selection.type);
  if (selection.level !== "all") params.set("level", String(selection.level));
  return `?${params.toString()}`;
}

export function filterTests(tests, selection) {
  return tests.filter((entry) =>
    (selection.type === "all" || entry.type === selection.type)
    && (selection.level === "all" || entry.level === selection.level)
  );
}

export function facetCounts(tests, selection) {
  return {
    overlap: filterTests(tests, selection).length,
    types: Object.fromEntries([
      ["all", tests.length],
      ...TYPES.map((type) => [type, tests.filter((entry) => entry.type === type).length])
    ]),
    levels: Object.fromEntries([
      ["all", tests.length],
      ...LEVELS.map((level) => [level, tests.filter((entry) => entry.level === level).length])
    ])
  };
}

export function groupTests(tests) {
  return LEVELS
    .map((level) => ({
      level,
      tests: tests
        .filter((entry) => entry.level === level)
        .toSorted((left, right) => left.title.localeCompare(right.title))
    }))
    .filter((group) => group.tests.length > 0);
}

const TYPE_LABELS = {
  all: "All types",
  polish: "Polish",
  "bug-fix": "Bug fix",
  feature: "Feature"
};

const LEVEL_LABELS = {
  all: "All difficulties",
  1: "Difficulty 1 · Atomic",
  2: "Difficulty 2 · Focused",
  3: "Difficulty 3 · Coordinated",
  4: "Difficulty 4 · Complex"
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function list(items, className = "toolbox-list") {
  const node = element("ul", className);
  for (const item of items) node.append(element("li", "", item));
  return node;
}

function detail(title, ...content) {
  const node = element("details", "toolbox-detail accordion-item");
  const summary = element("summary", "toolbox-detail-summary accordion-button collapsed", title);
  const toggle = element("span", "accordion-button-toggle");
  toggle.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" class="icon"><path d="M6 9l6 6l6 -6" /></svg>';
  summary.append(toggle);
  node.append(summary, ...content);
  return node;
}

export function readinessLabel(state) {
  return state.materialized ? "Ready" : "Draft";
}

function renderBrief(test) {
  const body = element("div", "toolbox-detail-body");
  body.append(element("p", "toolbox-detail-lede", test.promptSummary));
  if (test.prompt.kind === "local") {
    body.append(element("pre", "toolbox-prompt", test.prompt.exact));
  } else {
    const paragraph = element("p", "toolbox-source-note", "The full third-party prompt stays at its pinned source. ");
    const link = element("a", "", "Open pinned DeepSWE prompt");
    link.setAttribute("href", test.prompt.url);
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noreferrer");
    paragraph.append(link);
    body.append(paragraph);
  }
  return body;
}

function renderSetup(test) {
  const body = element("div", "toolbox-detail-body");
  body.append(element("p", "toolbox-detail-lede", test.setupSummary));

  const facts = element("dl", "toolbox-facts");
  const protectedBoundary = test.apparatus.protectedFiles.length
    ? test.apparatus.protectedFiles.join(", ")
    : test.sourceKind === "deep-swe"
      ? "Unknown / not reported upstream"
      : "None";
  const resourceLabel = ({cpus, memoryMb, storageMb}) =>
    `${cpus} CPU · ${memoryMb / 1024} GB memory · ${storageMb / 1024} GB storage`;
  const rows = [
    ["Base", test.source.repository],
    ["Pinned at", test.source.baseCommit],
    ["Existing tests", test.existingTests.join(", ")],
    ["Agent environment", `${test.environment.workdir} · ${resourceLabel(test.environment.agent)}`],
    ["Verifier isolation", test.environment.verifierIsolation],
    ["Verifier environment", resourceLabel(test.environment.verifier)],
    ["MCP servers", test.environment.mcpServers.length ? test.environment.mcpServers.join(", ") : "None"],
    ["Network", test.limits.network],
    ["Agent limit", `${test.limits.agentTimeoutSeconds / 60} minutes`],
    ["Verifier limit", `${test.limits.verifierTimeoutSeconds / 60} minutes`],
    ["Protected files", protectedBoundary],
    ["Mutable files", test.apparatus.mutableFiles.length ? test.apparatus.mutableFiles.join(", ") : "Repository patch scope"]
  ];
  for (const [term, value] of rows) {
    facts.append(element("dt", "", term), element("dd", "", value));
  }
  body.append(facts);
  return body;
}

function renderVerification(test) {
  const items = [...test.verification];
  const alreadyNamesQa = items.some((item) => /(?:five|5)-case verifier QA/i.test(item));
  if (test.apparatus.qaCaseCount !== null && !alreadyNamesQa) {
    items.push(`${test.apparatus.qaCaseCount}-case verifier QA`);
  }
  return list(items);
}

function renderWhatItTests(test) {
  const body = element("div", "toolbox-detail-body toolbox-what-tests");
  const context = element("div", "toolbox-test-context");
  const provenance = element("p", "toolbox-context-source");
  provenance.append(
    element("span", "toolbox-context-kind", test.sourceKind === "controlled" ? "Controlled fixture" : "Real repository"),
    element("span", "", test.source.label)
  );
  context.append(
    element("p", "toolbox-context-stack", test.stack.join(" · ")),
    provenance,
    element("p", "toolbox-context-id", test.id)
  );
  body.append(
    element("p", "toolbox-detail-lede", test.purpose),
    list(test.expectedHarnessBehavior, "toolbox-what-tests-list"),
    context
  );
  return body;
}

function renderCard(test) {
  const card = element("article", `toolbox-card toolbox-card-level-${test.level} card`);
  card.setAttribute("data-test-id", test.id);

  const header = element("header", "toolbox-card-header card-body");
  const labels = element("div", "toolbox-card-labels");
  labels.append(
    element("span", "toolbox-badge toolbox-badge-type badge bg-secondary-lt", TYPE_LABELS[test.type]),
    element("span", `toolbox-badge toolbox-badge-level badge bg-${["blue", "teal", "orange", "purple"][test.level - 1]}-lt`, LEVEL_LABELS[test.level]),
    element("span", `toolbox-readiness badge bg-${test.setupState.materialized ? "green" : "yellow"}-lt`, readinessLabel(test.setupState))
  );
  const learning = element("div", "toolbox-learning");
  learning.append(
    element("p", "toolbox-learning-label", "What we’ll learn"),
    element("p", "toolbox-learning-goal", test.learningGoal)
  );
  header.append(
    labels,
    element("h3", "toolbox-card-title card-title", test.title),
    learning
  );

  const details = element("div", "toolbox-details accordion");
  details.append(
    detail("What it tests", renderWhatItTests(test)),
    detail("Task brief", renderBrief(test)),
    detail("Test setup", renderSetup(test)),
    detail("Expected agent process", list(test.expectedProcess)),
    detail("Verification", renderVerification(test))
  );

  card.append(element("div", `card-status-top bg-${["blue", "teal", "orange", "purple"][test.level - 1]}`), header, details);
  return card;
}

function filterButton({dimension, value, label, count, selected, onSelect, registry}) {
  const button = element("button", `toolbox-filter nav-link${selected ? " active" : ""}`);
  button.setAttribute("type", "button");
  button.setAttribute("data-filter", dimension);
  button.setAttribute("data-value", String(value));
  button.setAttribute("aria-pressed", String(selected));
  button.append(
    element("span", "toolbox-filter-label", label),
    element("span", "toolbox-filter-count badge bg-secondary-lt ms-2", count)
  );
  button.addEventListener("click", () => onSelect(value));
  registry.set(String(value), button);
  return button;
}

function renderFilterRow({label, dimension, values, labels, counts, selected, onSelect, registry}) {
  const row = element("section", "toolbox-filter-row");
  row.setAttribute("aria-label", `${label} filters`);
  row.append(element("h2", "toolbox-filter-heading", label));
  const controls = element("div", "toolbox-filter-controls nav nav-pills");
  controls.setAttribute("role", "group");
  controls.setAttribute("aria-label", label);
  for (const value of values) {
    controls.append(filterButton({
      dimension,
      value,
      label: labels[value],
      count: counts[value],
      selected: selected === value,
      onSelect,
      registry
    }));
  }
  row.append(controls);
  return row;
}

function renderResults(tests, selection) {
  const filtered = filterTests(tests, selection);
  const results = element("div", "toolbox-results");
  if (filtered.length === 0) {
    const empty = element("section", "toolbox-empty");
    empty.append(
      element("h2", "", "No Harness Tests cover this combination yet"),
      element("p", "", "This is a useful coverage gap in the current toolbox, not a failed test.")
    );
    results.append(empty);
    return results;
  }

  for (const group of groupTests(filtered)) {
    const section = element("section", "toolbox-level-group");
    const heading = element("div", "toolbox-level-heading");
    heading.append(
      element("h2", "mb-0", LEVEL_LABELS[group.level]),
      element("span", "toolbox-level-count badge bg-secondary-lt", `${group.tests.length} ${group.tests.length === 1 ? "test" : "tests"}`)
    );
    const grid = element("div", "toolbox-grid");
    for (const test of group.tests) grid.append(renderCard(test));
    section.append(heading, grid);
    results.append(section);
  }
  return results;
}

export function renderToolbox(tests, {
  location = globalThis.location,
  history = globalThis.history
} = {}) {
  const root = element("section", "toolbox container-xl");
  root.setAttribute("aria-label", "Harness Test Toolbox");
  let selection = selectionFromSearch(location?.search ?? "");
  const initialCounts = facetCounts(tests, selection);
  const typeButtons = new Map();
  const levelButtons = new Map();

  const intro = element("header", "toolbox-intro page-header");
  intro.append(
    element("h1", "page-title fs-1", "Toolbox"),
    element("p", "toolbox-intro-copy", "Explore the work profiles used to compare harnesses: what each test asks, how it is built, what process it expects, and what it can teach us.")
  );

  const filters = element("nav", "toolbox-filters card card-body");
  filters.setAttribute("aria-label", "Harness Test filters");
  filters.append(
    renderFilterRow({
      label: "Type",
      dimension: "type",
      values: ["all", ...TYPES],
      labels: TYPE_LABELS,
      counts: initialCounts.types,
      selected: selection.type,
      onSelect: (value) => select("type", value),
      registry: typeButtons
    }),
    renderFilterRow({
      label: "Difficulty",
      dimension: "level",
      values: ["all", ...LEVELS],
      labels: LEVEL_LABELS,
      counts: initialCounts.levels,
      selected: selection.level,
      onSelect: (value) => select("level", value),
      registry: levelButtons
    })
  );

  const summary = element("div", "toolbox-selection-summary");
  const summaryText = element("p", "");
  summaryText.setAttribute("aria-live", "polite");
  const clear = element("button", "toolbox-clear btn btn-ghost-secondary btn-sm", "Clear filters");
  clear.setAttribute("type", "button");
  clear.addEventListener("click", () => {
    selection = {type: "all", level: "all"};
    updateLocation();
    update();
  });
  summary.append(summaryText, clear);
  const results = element("div", "toolbox-results");
  root.append(intro, filters, summary, results);

  function updateLocation() {
    const query = selectionUrl(selection);
    const suffix = query === "?" ? "" : query;
    history?.replaceState?.(null, "", `${location?.pathname ?? "/"}${suffix}${location?.hash ?? ""}`);
  }

  function select(dimension, value) {
    selection = {...selection, [dimension]: value};
    updateLocation();
    update();
  }

  function updateButtons(registry, selected) {
    for (const [value, button] of registry) {
      button.setAttribute("aria-pressed", String(String(selected) === value));
      button.className = `toolbox-filter nav-link${String(selected) === value ? " active" : ""}`;
    }
  }

  function update() {
    const counts = facetCounts(tests, selection);
    updateButtons(typeButtons, selection.type);
    updateButtons(levelButtons, selection.level);
    summaryText.textContent = `${counts.overlap} matching ${counts.overlap === 1 ? "test" : "tests"} · ${TYPE_LABELS[selection.type]} × ${LEVEL_LABELS[selection.level]}`;
    if (selection.type === "all" && selection.level === "all") clear.setAttribute("disabled", "");
    else clear.removeAttribute("disabled");
    const nextResults = renderResults(tests, selection);
    results.replaceChildren(...Array.from(nextResults.children));
  }

  update();
  return root;
}
