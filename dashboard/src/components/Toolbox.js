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
  const atSelectedLevel = tests.filter((entry) =>
    selection.level === "all" || entry.level === selection.level
  );
  const atSelectedType = tests.filter((entry) =>
    selection.type === "all" || entry.type === selection.type
  );

  return {
    overlap: filterTests(tests, selection).length,
    types: Object.fromEntries([
      ["all", atSelectedLevel.length],
      ...TYPES.map((type) => [type, atSelectedLevel.filter((entry) => entry.type === type).length])
    ]),
    levels: Object.fromEntries([
      ["all", atSelectedType.length],
      ...LEVELS.map((level) => [level, atSelectedType.filter((entry) => entry.level === level).length])
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
  all: "All levels",
  1: "L1 Atomic",
  2: "L2 Focused",
  3: "L3 Coordinated",
  4: "L4 Complex"
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
  const node = element("details", "toolbox-detail");
  node.append(element("summary", "toolbox-detail-summary", title), ...content);
  return node;
}

function statusLabels(state) {
  const labels = ["Defined"];
  labels.push(state.materialized ? "Materialized" : "Not materialized");
  if (state.queued) labels.push("Queued");
  return labels;
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
  const rows = [
    ["Base", test.source.repository],
    ["Pinned at", test.source.baseCommit],
    ["Existing tests", test.existingTests.join(", ")],
    ["Network", test.limits.network],
    ["Agent limit", `${test.limits.agentTimeoutSeconds / 60} minutes`],
    ["Verifier limit", `${test.limits.verifierTimeoutSeconds / 60} minutes`],
    ["Protected files", test.apparatus.protectedFiles.length ? test.apparatus.protectedFiles.join(", ") : "Defined by the upstream task image and verifier"],
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
  if (test.apparatus.qaCaseCount !== null) {
    items.push(`${test.apparatus.qaCaseCount}-case verifier QA`);
  }
  return list(items);
}

function renderCard(test) {
  const card = element("article", "toolbox-card card");
  card.setAttribute("data-test-id", test.id);

  const header = element("header", "toolbox-card-header");
  const eyebrow = element("div", "toolbox-eyebrow");
  eyebrow.append(
    element("span", `toolbox-badge toolbox-badge-${test.type}`, TYPE_LABELS[test.type]),
    element("span", "toolbox-badge toolbox-badge-level", LEVEL_LABELS[test.level]),
    element("span", "toolbox-badge toolbox-badge-source", test.sourceKind === "controlled" ? "Controlled" : "Real repository")
  );
  header.append(
    eyebrow,
    element("h3", "toolbox-card-title", test.title),
    element("p", "toolbox-purpose", test.purpose)
  );

  const metadata = element("div", "toolbox-card-metadata");
  metadata.append(
    element("p", "toolbox-stack", test.stack.join(" · ")),
    element("p", "toolbox-source", test.source.label),
    element("p", "toolbox-id", test.id)
  );
  const statuses = element("div", "toolbox-statuses");
  for (const label of statusLabels(test.setupState)) {
    statuses.append(element("span", "toolbox-status", label));
  }
  metadata.append(statuses);

  const details = element("div", "toolbox-details");
  details.append(
    detail("What it tests", element("div", "toolbox-detail-body", ""), list(test.expectedHarnessBehavior)),
    detail("Task brief", renderBrief(test)),
    detail("Test setup", renderSetup(test)),
    detail("Expected agent process", list(test.expectedProcess)),
    detail("Verification", renderVerification(test)),
    detail("What we learn", element("p", "toolbox-detail-body", test.learningGoal))
  );
  details.children[0].children[1].append(element("p", "toolbox-detail-lede", test.purpose));

  card.append(header, metadata, details);
  return card;
}

function filterButton({dimension, value, label, count, selected, onSelect}) {
  const button = element("button", "toolbox-filter");
  button.setAttribute("type", "button");
  button.setAttribute("data-filter", dimension);
  button.setAttribute("data-value", String(value));
  button.setAttribute("aria-pressed", String(selected));
  button.append(
    element("span", "toolbox-filter-label", label),
    element("span", "toolbox-filter-count", count)
  );
  button.addEventListener("click", () => onSelect(value));
  return button;
}

function renderFilterRow({label, dimension, values, labels, counts, selected, onSelect}) {
  const row = element("section", "toolbox-filter-row");
  row.setAttribute("aria-label", `${label} filters`);
  row.append(element("h2", "toolbox-filter-heading", label));
  const controls = element("div", "toolbox-filter-controls");
  controls.setAttribute("role", "group");
  controls.setAttribute("aria-label", label);
  for (const value of values) {
    controls.append(filterButton({
      dimension,
      value,
      label: labels[value],
      count: counts[value],
      selected: selected === value,
      onSelect
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
      element("span", "toolbox-level-kicker", `L${group.level}`),
      element("h2", "", LEVEL_LABELS[group.level].replace(`L${group.level} `, "")),
      element("span", "toolbox-level-count", `${group.tests.length} ${group.tests.length === 1 ? "test" : "tests"}`)
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
  const root = element("main", "toolbox");
  let selection = selectionFromSearch(location?.search ?? "");

  function updateLocation() {
    const query = selectionUrl(selection);
    const suffix = query === "?" ? "" : query;
    history?.replaceState?.(null, "", `${location?.pathname ?? "/"}${suffix}${location?.hash ?? ""}`);
  }

  function select(dimension, value) {
    selection = {...selection, [dimension]: value};
    updateLocation();
    render();
  }

  function render() {
    const counts = facetCounts(tests, selection);
    const intro = element("header", "toolbox-intro");
    intro.append(
      element("p", "toolbox-kicker", "Harness Test Toolbox"),
      element("h1", "", `${tests.length} Harness Tests`),
      element("p", "toolbox-intro-copy", "Explore the work profiles used to compare harnesses: what each test asks, how it is built, what process it expects, and what it can teach us.")
    );

    const filters = element("nav", "toolbox-filters");
    filters.setAttribute("aria-label", "Harness Test filters");
    filters.append(
      renderFilterRow({
        label: "Type",
        dimension: "type",
        values: ["all", ...TYPES],
        labels: TYPE_LABELS,
        counts: counts.types,
        selected: selection.type,
        onSelect: (value) => select("type", value)
      }),
      renderFilterRow({
        label: "Level",
        dimension: "level",
        values: ["all", ...LEVELS],
        labels: LEVEL_LABELS,
        counts: counts.levels,
        selected: selection.level,
        onSelect: (value) => select("level", value)
      })
    );

    const summary = element("div", "toolbox-selection-summary");
    const summaryText = element(
      "p",
      "",
      `${counts.overlap} matching ${counts.overlap === 1 ? "test" : "tests"} · ${TYPE_LABELS[selection.type]} × ${LEVEL_LABELS[selection.level]}`
    );
    summaryText.setAttribute("aria-live", "polite");
    const clear = element("button", "toolbox-clear", "Clear filters");
    clear.setAttribute("type", "button");
    clear.addEventListener("click", () => {
      selection = {type: "all", level: "all"};
      updateLocation();
      render();
    });
    if (selection.type === "all" && selection.level === "all") clear.setAttribute("disabled", "");
    summary.append(summaryText, clear);

    root.replaceChildren(intro, filters, summary, renderResults(tests, selection));
  }

  render();
  return root;
}
