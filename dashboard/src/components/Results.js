import {HARNESS_FAMILIES} from "../data/Harness Catalog.js";

const TYPE_LABELS = new Map([
  ["all", "All types"],
  ["polish", "Polish"],
  ["bug-fix", "Bug fixes"],
  ["feature", "Features"]
]);

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function svgElement(tag, attributes = {}, text = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  if (text !== "") node.textContent = text;
  return node;
}

function mean(values) {
  const available = values.filter((value) => Number.isFinite(value));
  return available.length ? available.reduce((sum, value) => sum + value, 0) / available.length : null;
}

function formatPercent(value) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function formatDelta(value) {
  if (value == null) return "—";
  const points = Math.round(value * 100);
  return `${points > 0 ? "+" : ""}${points} pts`;
}

function formatRuntime(value) {
  if (value == null) return "—";
  if (value < 120) return `${Math.round(value)}s`;
  return `${(value / 60).toFixed(1)}m`;
}

function formatTokens(value) {
  if (value == null) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  return value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k` : `${Math.round(value)}`;
}

function formatCost(value) {
  if (value == null) return "—";
  if (value > 0 && value < 0.01) return "<$0.01";
  return `$${value.toFixed(value >= 10 ? 0 : 2)}`;
}

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

export function harnessArm(version) {
  return version.identity == null ? null : `V${version.identity.slice("sha256:".length, "sha256:".length + 16)}`;
}

export function qualityFromGrade(grade) {
  if (grade?.status !== "completed") return null;
  const scores = (grade.dimensions ?? []).map(({score}) => score / 5);
  return mean(scores);
}

function readyHarnesses(harnesses) {
  return harnesses.filter(({identity, state}) => identity != null && state === "ready");
}

export function normalizeResults(reports, tests, harnesses) {
  const testById = new Map(tests.map((entry) => [entry.id, entry]));
  const harnessByArm = new Map(
    readyHarnesses(harnesses).map((version) => [harnessArm(version), version])
  );
  const observations = [];

  for (const report of reports) {
    if (report.schema_version !== "3" || report.source?.kind !== "current") continue;
    const gradedTrials = new Map();
    for (const trial of report.experiment?.trials ?? []) {
      const key = `${trial.contender_id}\0${trial.task_id}`;
      const values = gradedTrials.get(key) ?? [];
      const quality = qualityFromGrade(trial.collaboration?.grade);
      if (quality != null) values.push(quality);
      gradedTrials.set(key, values);
    }
    for (const job of report.jobs ?? []) {
      const test = testById.get(job.task);
      const harness = harnessByArm.get(job.arm);
      if (test == null || harness == null) continue;
      const prompt = job.efficiency?.prompt_tokens;
      const completion = job.efficiency?.completion_tokens;
      const qualityValues = gradedTrials.get(`${harness.identity}\0${test.id}`) ?? [];
      observations.push({
        observationId: `${report.run_id}\0${job.name ?? `${job.arm}-${job.task}`}`,
        runId: report.run_id,
        reportId: report.report_id ?? null,
        updatedAt: job.finished_at ?? report.finished_at ?? report.updated_at,
        harnessId: harness.id,
        harnessFamily: harness.family,
        harnessLabel: `${HARNESS_FAMILIES[harness.family].name} ${harness.versionLabel}`,
        predecessorId: harness.predecessorId,
        taskId: test.id,
        taskTitle: test.title,
        type: test.type,
        level: test.level,
        model: job.model,
        effort: job.effort,
        modelKey: `${job.model}\0${job.effort}`,
        status: job.status,
        runStatus: report.status,
        reviewState: report.evidence?.review_state ?? "unreviewed",
        limitations: report.evidence?.limitations ?? [],
        comparability: job.comparability,
        correctness: job.dimensions?.correctness ?? null,
        workflow: job.dimensions?.workflow ?? null,
        efficiencyPolicy: job.dimensions?.efficiency_policy ?? null,
        quality: mean(qualityValues),
        qualityTrials: qualityValues.length,
        runtime: job.runtime_seconds ?? null,
        tokens: prompt == null || completion == null ? null : prompt + completion,
        cost: job.efficiency?.api_equivalent_cost_usd ?? null,
        completedTrials: job.completed_trials ?? 1
      });
    }
  }

  return observations.sort((left, right) => compareText(
    `${left.updatedAt}\0${left.observationId}`,
    `${right.updatedAt}\0${right.observationId}`
  ));
}

export function defaultModel(observations) {
  const counts = new Map();
  for (const observation of observations) {
    const count = counts.get(observation.modelKey) ?? {quality: 0, admitted: 0};
    count.admitted += 1;
    if (observation.quality != null) count.quality += 1;
    counts.set(observation.modelKey, count);
  }
  return [...counts].sort((left, right) =>
    right[1].quality - left[1].quality ||
    right[1].admitted - left[1].admitted ||
    compareText(left[0], right[0])
  )[0]?.[0] ?? "all";
}

export function filterResults(observations, filters = {}) {
  const {type = "all", level = "all", model = "all"} = filters;
  return observations.filter((observation) =>
    (type === "all" || observation.type === type) &&
    (level === "all" || observation.level === Number(level)) &&
    (model === "all" || observation.modelKey === model)
  );
}

export function admitResults(observations) {
  return observations.filter((observation) =>
    observation.status === "completed" &&
    observation.comparability === "comparable" &&
    observation.reviewState !== "quarantined" &&
    observation.limitations.length === 0 &&
    Number.isFinite(observation.correctness)
  );
}

function averageByTask(observations, field) {
  const tasks = new Map();
  for (const observation of observations) {
    const values = tasks.get(observation.taskId) ?? [];
    values.push(observation[field]);
    tasks.set(observation.taskId, values);
  }
  return mean([...tasks.values()].map((values) => mean(values)));
}

function pairedDelta(observations, candidateId, referenceId) {
  if (referenceId == null || candidateId === referenceId) return null;
  const pairs = new Map();
  for (const observation of observations) {
    if (observation.harnessId !== candidateId && observation.harnessId !== referenceId) continue;
    const key = `${observation.runId}\0${observation.taskId}\0${observation.modelKey}`;
    const pair = pairs.get(key) ?? {candidate: [], reference: []};
    pair[observation.harnessId === candidateId ? "candidate" : "reference"].push(observation.correctness);
    pairs.set(key, pair);
  }
  return mean([...pairs.values()].flatMap(({candidate, reference}) => {
    const candidateMean = mean(candidate);
    const referenceMean = mean(reference);
    return Number.isFinite(candidateMean) && Number.isFinite(referenceMean)
      ? [candidateMean - referenceMean]
      : [];
  }));
}

export function aggregateHarnesses(observations, harnesses, filters = {}) {
  const filtered = admitResults(filterResults(observations, filters));
  const versions = readyHarnesses(harnesses);
  const eligibleVersions = versions.filter(({id}) => filtered.some(({harnessId}) => harnessId === id));
  const eligibleIds = new Set(eligibleVersions.map(({id}) => id));
  const taskSets = eligibleVersions.map(({id}) => new Set(filtered.filter(({harnessId}) => harnessId === id).map(({taskId}) => taskId)));
  const sharedTasks = new Set(taskSets[0] ?? []);
  for (const tasks of taskSets.slice(1)) {
    for (const task of sharedTasks) if (!tasks.has(task)) sharedTasks.delete(task);
  }
  const cohort = filtered.filter(({taskId}) => sharedTasks.has(taskId));
  const nothingId = harnesses.find(({family, state}) => family === "nothing" && state === "ready")?.id ?? null;
  const rows = [];
  for (const harness of versions) {
    const observedValues = filtered.filter(({harnessId}) => harnessId === harness.id);
    const values = cohort.filter(({harnessId}) => harnessId === harness.id);
    rows.push({
      id: harness.id,
      family: harness.family,
      label: `${HARNESS_FAMILIES[harness.family].name} ${harness.versionLabel}`,
      versionLabel: harness.versionLabel,
      eligible: eligibleIds.has(harness.id),
      observations: observedValues.length,
      coveredTests: new Set(observedValues.map(({taskId}) => taskId)).size,
      sharedTests: sharedTasks.size,
      correctness: averageByTask(values, "correctness"),
      quality: averageByTask(values, "quality"),
      qualityObservations: values.reduce((sum, {qualityTrials}) => sum + qualityTrials, 0),
      efficiencyPolicy: averageByTask(values, "efficiencyPolicy"),
      runtime: averageByTask(values, "runtime"),
      tokens: averageByTask(values, "tokens"),
      cost: averageByTask(values, "cost"),
      deltaFromNothing: pairedDelta(filtered, harness.id, nothingId),
      deltaFromPredecessor: pairedDelta(filtered, harness.id, harness.predecessorId)
    });
  }
  return rows.sort((left, right) => {
    if (left.correctness == null && right.correctness != null) return 1;
    if (left.correctness != null && right.correctness == null) return -1;
    return (right.correctness ?? 0) - (left.correctness ?? 0) ||
      (right.quality ?? -1) - (left.quality ?? -1) ||
      compareText(left.label, right.label);
  });
}

function renderFilterButtons(values, selected, label, onChange) {
  const group = element("div", "results-filter-group");
  group.setAttribute("aria-label", label);
  for (const [value, text] of values) {
    const button = element("button", "results-filter-button", text);
    button.setAttribute("type", "button");
    button.setAttribute("aria-pressed", value === selected ? "true" : "false");
    button.addEventListener("click", () => onChange(value));
    group.append(button);
  }
  return group;
}

function metricCell(value, formatter, className = "") {
  return element("td", className, formatter(value));
}

function renderLeaderboard(rows, testCount) {
  const section = element("section", "results-panel results-leaderboard");
  const heading = element("header", "results-section-heading");
  const rankedHarnesses = rows.filter(({eligible}) => eligible).length;
  const sharedTests = rows.find(({eligible}) => eligible)?.sharedTests ?? 0;
  heading.append(
    element("h2", "", "Harness leaderboard"),
    element("p", "", `${rankedHarnesses} harnesses ranked by correctness, then Quality, on ${sharedTests} shared ${sharedTests === 1 ? "test" : "tests"} in the shared task cohort. Ineligible harnesses remain visible as coverage gaps; correctness deltas require a same-run pair.`)
  );
  const cue = element("p", "results-scroll-cue", "Swipe horizontally to see every metric.");
  const scroll = element("div", "results-table-scroll");
  scroll.setAttribute("tabindex", "0");
  scroll.setAttribute("aria-label", "Harness leaderboard metrics");
  const table = element("table", "results-table");
  const head = element("thead");
  const headerRow = element("tr");
  for (const label of ["Harness", "Coverage", "Correctness", "Quality", "Avg runtime", "Avg tokens", "Avg cost", "Correctness vs Nothing", "Correctness vs previous"]) {
    headerRow.append(element("th", "", label));
  }
  head.append(headerRow);
  const body = element("tbody");
  for (const row of rows) {
    const tr = element("tr");
    tr.setAttribute("data-harness-id", row.id);
    const name = element("td", "results-harness-name");
    name.append(
      element("span", `results-harness-mark results-harness-${row.family}`),
      element("strong", "", row.label),
      element("small", "", `${row.observations} observation${row.observations === 1 ? "" : "s"}`)
    );
    const score = element("td", "results-score-cell");
    score.append(element("strong", "", formatPercent(row.correctness)));
    if (row.correctness != null) {
      const track = element("span", "results-score-track");
      const fill = element("span", "results-score-fill");
      fill.setAttribute("style", `width:${Math.max(2, row.correctness * 100)}%`);
      track.append(fill);
      score.append(track);
    }
    const coverage = element("td", "results-coverage-cell");
    if (row.eligible) {
      coverage.append(
        element("strong", "", `${row.sharedTests} shared`),
        element("small", "", `${row.coveredTests} / ${testCount} observed`)
      );
    } else {
      coverage.append(element("strong", "", "Not tested"), element("small", "", "in this scope"));
    }
    const quality = element("td", "results-quality-cell");
    quality.append(element("strong", "", formatPercent(row.quality)));
    if (row.qualityObservations) quality.append(element("small", "", `${row.qualityObservations} graded`));
    tr.append(
      name,
      coverage,
      score,
      quality,
      metricCell(row.runtime, formatRuntime),
      metricCell(row.tokens, formatTokens),
      metricCell(row.cost, formatCost),
      metricCell(row.deltaFromNothing, formatDelta, row.deltaFromNothing > 0 ? "results-positive" : row.deltaFromNothing < 0 ? "results-negative" : ""),
      metricCell(row.deltaFromPredecessor, formatDelta, row.deltaFromPredecessor > 0 ? "results-positive" : row.deltaFromPredecessor < 0 ? "results-negative" : "")
    );
    body.append(tr);
  }
  table.append(head, body);
  scroll.append(table);
  section.append(heading, cue, scroll);
  return section;
}

function displayHarnesses(harnesses) {
  const studio = readyHarnesses(harnesses)
    .filter(({family}) => family === "studio-moser")
    .sort((left, right) => right.versionOrder - left.versionOrder);
  const baselines = readyHarnesses(harnesses)
    .filter(({family}) => family !== "studio-moser")
    .sort((left, right) => compareText(left.family, right.family));
  return [...studio, ...baselines];
}

function renderMatrix(observations, tests, harnesses, filters) {
  const filtered = filterResults(observations, filters);
  const admitted = admitResults(filtered);
  const admittedSet = new Set(admitted);
  const visibleTests = tests
    .filter((test) => (filters.type === "all" || test.type === filters.type) && (filters.level === "all" || test.level === Number(filters.level)))
    .sort((left, right) => left.level - right.level || compareText(left.title, right.title));
  const versions = displayHarnesses(harnesses);
  const section = element("section", "results-panel results-matrix");
  const heading = element("header", "results-section-heading");
  heading.append(
    element("h2", "", "Test coverage"),
    element("p", "", "Scores include admitted evidence only. Failed, pending, or diagnostic cells remain visible; a blank cell is a coverage gap.")
  );
  const cue = element("p", "results-scroll-cue", "Swipe horizontally to compare every harness version.");
  const scroll = element("div", "results-table-scroll");
  scroll.setAttribute("tabindex", "0");
  scroll.setAttribute("aria-label", "Test coverage by harness version");
  const table = element("table", "results-table results-matrix-table");
  const head = element("thead");
  const headerRow = element("tr");
  headerRow.append(element("th", "", "Test"));
  for (const version of versions) headerRow.append(element("th", "", `${HARNESS_FAMILIES[version.family].name} ${version.versionLabel}`));
  head.append(headerRow);
  const body = element("tbody");
  for (const test of visibleTests) {
    const row = element("tr");
    const name = element("td", "results-test-name");
    name.append(element("strong", "", test.title), element("small", "", `L${test.level} · ${TYPE_LABELS.get(test.type)}`));
    row.append(name);
    for (const version of versions) {
      const rawValues = filtered.filter(({taskId, harnessId}) => taskId === test.id && harnessId === version.id);
      const values = admitted.filter(({taskId, harnessId}) => taskId === test.id && harnessId === version.id);
      const excluded = rawValues.filter((value) => !admittedSet.has(value));
      const score = mean(values.map(({correctness}) => correctness));
      let unavailable = "—";
      if (rawValues.some(({status}) => status === "failed")) unavailable = "Failed";
      else if (rawValues.some(({status}) => status === "pending" || status === "running")) unavailable = "Pending";
      else if (rawValues.some(({comparability}) => comparability !== "comparable")) unavailable = "Diagnostic";
      else if (rawValues.some(({limitations}) => limitations.length)) unavailable = "Limited";
      const cell = element("td", score == null ? "results-matrix-empty" : "results-matrix-score");
      cell.append(element("strong", "", score == null ? unavailable : formatPercent(score)));
      if (excluded.length) {
        const counts = [
          ["failed", excluded.filter(({status}) => status === "failed").length],
          ["pending", excluded.filter(({status}) => status === "pending" || status === "running").length],
          ["limited", excluded.filter(({limitations}) => limitations.length).length],
          ["diagnostic", excluded.filter(({comparability}) => comparability !== "comparable").length]
        ].filter(([, count]) => count > 0);
        cell.append(element("small", "results-cell-evidence", counts.map(([label, count]) => `${count} ${label}`).join(" · ")));
      }
      if (score != null) cell.setAttribute("style", `--score:${score}`);
      row.append(cell);
    }
    body.append(row);
  }
  table.append(head, body);
  scroll.append(table);
  section.append(heading, cue, scroll);
  return section;
}

function renderTradeoffChart(rows, {field, title, formatter, ariaLabel}) {
  const panel = element("article", "results-tradeoff-chart");
  panel.append(element("h3", "", title));
  const points = rows.filter((row) => row.quality != null && row[field] != null);
  if (points.length === 0) {
    panel.append(element("p", "results-empty", `No graded Quality and ${title.split(" vs ")[1].toLowerCase()} observations match this scope.`));
    return panel;
  }

  const width = 520;
  const height = 300;
  const margin = {top: 20, right: 24, bottom: 42, left: 48};
  const observedMaximum = Math.max(...points.map((row) => row[field]));
  const maxValue = observedMaximum > 0 ? observedMaximum : 1;
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const svg = svgElement("svg", {viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": ariaLabel});
  for (const score of [0, 0.25, 0.5, 0.75, 1]) {
    const y = margin.top + (1 - score) * plotHeight;
    svg.append(
      svgElement("line", {x1: margin.left, x2: margin.left + plotWidth, y1: y, y2: y, class: "results-chart-grid"}),
      svgElement("text", {x: margin.left - 9, y: y + 4, class: "results-chart-axis", "text-anchor": "end"}, formatPercent(score))
    );
  }
  for (const ratio of [0, 0.5, 1]) {
    const x = margin.left + ratio * plotWidth;
    svg.append(svgElement("text", {x, y: height - 14, class: "results-chart-axis", "text-anchor": "middle"}, formatter(maxValue * ratio)));
  }
  points.forEach((row) => {
    const x = margin.left + (row[field] / maxValue) * plotWidth;
    const y = margin.top + (1 - row.quality) * plotHeight;
    const point = svgElement("circle", {
      cx: x,
      cy: y,
      r: 7,
      class: `results-chart-point results-chart-${row.family}`,
      role: "img",
      "aria-label": `${row.label}: ${formatPercent(row.quality)} Quality, ${formatter(row[field])}`
    });
    svg.append(point);
  });
  const scroll = element("div", "results-chart-scroll");
  scroll.setAttribute("tabindex", "0");
  scroll.setAttribute("aria-label", ariaLabel);
  scroll.append(svg);
  panel.append(element("p", "results-scroll-cue", "Swipe horizontally to inspect every harness point."), scroll);
  return panel;
}

function renderTradeoffs(rows) {
  const section = element("section", "results-panel results-tradeoffs");
  const heading = element("header", "results-section-heading");
  const graded = rows.reduce((sum, row) => sum + row.qualityObservations, 0);
  heading.append(
    element("h2", "", "Quality trade-offs"),
    element("p", "", "Upper left is stronger: a less annoying collaborator using less time, context, or money. Missing telemetry is omitted.")
  );
  const qualityNote = element("div", "results-quality-note");
  qualityNote.append(
    element("strong", "", `Quality has ${graded} blinded collaboration ${graded === 1 ? "grade" : "grades"} in this scope.`),
    element("span", "", "It averages directness, proportionality, useful progress, autonomy, candor, warmth, restraint, and completion clarity. Test strategy, self-verification depth, requirement fit, and research depth are not yet included in Quality.")
  );
  const qualityRows = rows.filter(({quality}) => quality != null);
  const legend = element("div", "results-chart-legend");
  legend.setAttribute("aria-label", "Harness color key");
  for (const row of qualityRows) {
    const item = element("span", "results-chart-legend-item");
    item.append(
      element("span", `results-chart-legend-dot results-harness-${row.family}`),
      element("span", "", row.label)
    );
    legend.append(item);
  }
  const mobileSummary = element("div", "results-mobile-efficiency");
  for (const row of qualityRows) {
    const item = element("div", "results-mobile-efficiency-row");
    item.append(
      element("span", `results-harness-mark results-harness-${row.family}`),
      element("strong", "", row.label),
      element("span", "", formatPercent(row.quality)),
      element("span", "", `${formatRuntime(row.runtime)} · ${formatTokens(row.tokens)} · ${formatCost(row.cost)}`)
    );
    mobileSummary.append(item);
  }
  const charts = element("div", "results-tradeoff-grid");
  charts.append(
    renderTradeoffChart(rows, {field: "runtime", title: "Quality vs runtime", formatter: formatRuntime, ariaLabel: "Quality versus average runtime by harness"}),
    renderTradeoffChart(rows, {field: "tokens", title: "Quality vs tokens", formatter: formatTokens, ariaLabel: "Quality versus average tokens by harness"}),
    renderTradeoffChart(rows, {field: "cost", title: "Quality vs cost", formatter: formatCost, ariaLabel: "Quality versus average cost by harness"})
  );
  section.append(heading, qualityNote, legend, mobileSummary, charts);
  return section;
}

function selectedTestCount(tests, filters) {
  return tests.filter((test) =>
    (filters.type === "all" || test.type === filters.type) &&
    (filters.level === "all" || test.level === Number(filters.level))
  ).length;
}

export function renderResults({tests, harnesses, reports}) {
  const observations = normalizeResults(reports, tests, harnesses);
  const admitted = admitResults(observations);
  const modelOptions = [...new Map(admitted.map(({modelKey, model, effort}) => [modelKey, `${model} · ${effort}`]))]
    .sort((left, right) => compareText(left[1], right[1]));
  const state = {type: "all", level: "all", model: defaultModel(admitted)};
  const root = element("section", "results-page");
  root.setAttribute("aria-label", "Harness results");

  const intro = element("header", "results-intro");
  intro.append(
    element("h1", "", "Results"),
    element("p", "", "Compare what each harness version accomplishes across the Toolbox, then read quality beside the time and token cost required to get there."),
    element("p", "results-evidence-line", `${admitted.length} admitted comparable observations · ${observations.length - admitted.length} excluded pending, failed, limited, or diagnostic observations · ${new Set(admitted.map(({taskId}) => taskId)).size} of ${tests.length} Toolbox tests represented`)
  );

  const filters = element("nav", "results-filters");
  filters.setAttribute("aria-label", "Results scope");
  const body = element("div", "results-body");

  function update() {
    filters.replaceChildren(
      renderFilterButtons([...TYPE_LABELS], state.type, "Test type", (value) => { state.type = value; update(); }),
      renderFilterButtons([["all", "All levels"], ...[1, 2, 3, 4].map((level) => [`${level}`, `L${level}`])], state.level, "Test level", (value) => { state.level = value; update(); })
    );
    const modelControl = element("label", "results-model-filter");
    modelControl.append(element("span", "", "Model and effort"));
    const select = element("select", "form-select results-model-select");
    select.value = state.model;
    for (const [value, label] of modelOptions) {
      const option = element("option", "", label);
      option.setAttribute("value", value);
      if (value === state.model) option.setAttribute("selected", "");
      select.append(option);
    }
    select.addEventListener("change", () => { state.model = select.value; update(); });
    modelControl.append(select);
    filters.append(modelControl, element("p", "results-scope-note", "Current methodology only · completed comparable jobs · unreviewed development evidence"));

    const rows = aggregateHarnesses(observations, harnesses, state);
    const testCount = selectedTestCount(tests, state);
    body.replaceChildren(
      renderLeaderboard(rows, testCount),
      renderTradeoffs(rows),
      renderMatrix(observations, tests, harnesses, state)
    );
  }

  update();
  root.append(intro, filters, body);
  return root;
}
