// The runner owns verdicts; this module selects and presents recorded evidence.
export function comparisonReports(reports) {
  return reports.filter(r => r.schema_version === "3" && r.experiment?.purpose !== "diagnostic")
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export function selectComparison(reports, id) {
  return id ? reports.find(r => r.schema_version === "3" && r.report_id === id) ?? null
    : comparisonReports(reports)[0] ?? null;
}

export function comparisonUrl(path, state = {}) {
  const query = new URLSearchParams(Object.entries(state).filter(([, value]) => value != null && value !== ""));
  const target = path !== "/" && !path.endsWith(".html") ? `${path}.html` : path;
  return `${target}${query.size ? `?${query}` : ""}`;
}

export function versionHistory(reports) {
  const groups = new Map();
  for (const report of comparisonReports(reports)) {
    for (const contender of report.experiment.contenders) {
      if (["nothing", "superpowers"].includes(contender.family)) continue;
      if (!groups.has(contender.id)) groups.set(contender.id, {...contender, runs: []});
      groups.get(contender.id).runs.push(report);
    }
  }
  return [...groups.values()];
}

export function sortNumericRows(rows, field, ascending = true) {
  return [...rows].sort((a, b) => {
    const left = Number.isFinite(a[field]) ? a[field] : null;
    const right = Number.isFinite(b[field]) ? b[field] : null;
    if (left === null) return right === null ? 0 : 1;
    if (right === null) return -1;
    return (left - right) * (ascending ? 1 : -1);
  });
}

const labels = {
  recommended: "Recommended on these tests",
  no_clear_winner: "No clear winner",
  no_quality_qualified_winner: "No harness passed the quality bar",
  insufficient_evidence: "Not enough evidence yet",
  incompatible_conditions: "These results cannot be compared",
  first_version: "First comparison", improved: "Improved", regressed: "Regressed",
  mixed: "Mixed results", no_clear_change: "No clear change"
};
const reasons = {
  quality_ineligible: "Not every scheduled trial has a verified successful result.",
  usage_incomplete: "Some model usage is missing, so a complete cost comparison is unavailable.",
  pricing_unavailable: "Comparable pricing is unavailable for some attempted work.",
  incomplete_coverage: "The selected evidence does not cover every scheduled, graded trial.",
  cost_time_tradeoff: "Cost and speed favor different harnesses.",
  missing_or_ambiguous_evidence: "Selected comparison evidence is missing or ambiguous.",
  practical_advantage_supported: "The advantage clears the recorded practical-difference and uncertainty thresholds.",
  diagnostic_only: "This is a diagnostic run, not evidence for an overall recommendation."
};
const money = v => v == null ? "Unavailable" : new Intl.NumberFormat("en-US", {style: "currency", currency: "USD", maximumFractionDigits: 4}).format(v);
const tokens = v => v == null ? "Unavailable" : new Intl.NumberFormat("en-US", {notation: "compact", maximumFractionDigits: 1}).format(v);
const seconds = v => v == null ? "Unavailable" : v < 60 ? `${v.toFixed(1)}s` : `${Math.floor(v / 60)}m ${Math.round(v % 60)}s`;
const date = v => v ? new Intl.DateTimeFormat("en-US", {month: "short", day: "numeric", year: "numeric"}).format(new Date(v)) : "Not finished";

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function link(text, path, state) {
  const node = el("a", text);
  node.href = comparisonUrl(path, state);
  return node;
}

function detail(title, content) {
  const node = el("details");
  node.append(el("summary", title), content);
  return node;
}

function list(items) {
  const node = el("ul");
  for (const item of items) node.append(el("li", item));
  return node;
}

function empty(message, reports) {
  const node = el("section", null, "comparison-empty");
  node.append(el("h2", message), el("p", "The first full comparison will test Nothing, Superpowers, and Studio Moser with the same kickoff model and development tasks."));
  if (reports.some(r => r.schema_version !== "3")) {
    node.append(el("p", "Earlier runs tested different configurations. They remain useful diagnostics, but do not establish a winner for this comparison."));
  }
  node.append(link("Inspect earlier run evidence", "/Legacy_Run_Detail.html"));
  return node;
}

function evidenceBadge(report) {
  const provisional = report.experiment.comparison?.provisional !== false;
  return el("p", provisional ? "Provisional · independent review is still required" : "Reviewed comparison evidence", "comparison-meta");
}

export function renderComparison(reports, state = {}) {
  const root = el("div", null, "harness-comparison");
  const choices = comparisonReports(reports);
  const current = selectComparison(reports, state.comparison);
  if (!current) return empty(state.comparison ? "That comparison is unavailable" : "No full harness comparison yet", reports);
  const experiment = current.experiment;
  const comparison = experiment.comparison;
  const choiceLabel = el("label", "Comparison ");
  const select = el("select");
  select.setAttribute("aria-label", "Select comparison");
  for (const report of choices.some(r => r.report_id === current.report_id) ? choices : [current, ...choices]) {
    const option = el("option", `${report.experiment.label} · ${date(report.finished_at ?? report.updated_at)}`);
    option.value = report.report_id;
    option.selected = report.report_id === current.report_id;
    select.append(option);
  }
  select.addEventListener("change", () => { location.href = comparisonUrl("/", {...state, comparison: select.value}); });
  choiceLabel.append(select);
  root.append(choiceLabel);
  const kickoff = experiment.conditions.kickoff;
  root.append(el("p", `${kickoff.model} · ${kickoff.effort} effort · ${experiment.conditions.task_ids.length} tasks × ${experiment.conditions.attempts} repetitions`, "comparison-meta"));
  const verdict = el("section", null, "comparison-verdict");
  const winner = comparison?.contenders.find(c => c.id === comparison.winner_id);
  verdict.append(el("h2", winner ? `${winner.label} is the supported choice` : labels[comparison?.status] ?? "Results are still arriving"));
  verdict.append(el("p", comparison?.summary ?? "Every scheduled trial must finish and be graded before this comparison can support a conclusion."));
  verdict.append(evidenceBadge(current));
  root.append(verdict);
  if (comparison?.contenders.length) {
    root.append(contenderTable(comparison.contenders, current.report_id));
    root.append(el("p", "Tested correctness comes first. Cost includes failed attempts and all recorded model calls; figures use shared standard token rates, excluding pricing premiums and tool charges. Time is end-to-end agent work per trial.", "comparison-meta"));
  }
  const baselineDates = experiment.baseline_result_ids.map(id => reports.find(r => r.report_id === id)).filter(Boolean);
  root.append(el("p", baselineDates.length ? `Baselines reused from ${[...new Set(baselineDates.map(r => date(r.finished_at)))].join(" and ")}.` : experiment.purpose === "baseline" ? "Baselines were measured in this experiment." : "No reusable baseline evidence is attached.", "comparison-meta"));
  const change = el("section", null, "comparison-change");
  change.append(el("h2", "What changed"), el("p", experiment.change.summary));
  change.append(el("p", `Expected benefit: ${experiment.change.hypothesis}`));
  if (comparison?.history) change.append(el("p", `${labels[comparison.history.status] ?? comparison.history.status}: ${comparison.history.summary}`, "history-verdict"));
  if (experiment.change.rerun_reason) change.append(el("p", `Unchanged-version rerun: ${experiment.change.rerun_reason}`));
  const nav = el("p", null, "comparison-links");
  nav.append(link("View version history", "/Version_History", {comparison: current.report_id}), link("Inspect task evidence", "/Run_Detail", {comparison: current.report_id}));
  change.append(nav);
  root.append(change);
  if (comparison) {
    const why = el("div");
    why.append(list(comparison.reasons.map(reason => reasons[reason] ?? reason.replaceAll("_", " "))));
    const names = new Map([...comparison.contenders, ...(comparison.history?.predecessor_contenders ?? [])].map(row => [row.id, row.label]));
    const ratio = value => value == null ? "unavailable" : `${value.estimate.toFixed(2)}× (interval ${value.lower.toFixed(2)}–${value.upper.toFixed(2)}×)`;
    for (const pair of comparison.pairs) {
      why.append(el("p", `${names.get(pair.left_id) ?? "Selected harness"} versus ${names.get(pair.right_id) ?? "Reference harness"}: cost ${ratio(pair.cost_ratio)}; time ${ratio(pair.time_ratio)}. A ratio below 1 favors the first harness.`));
    }
    why.append(el("p", "Efficiency recommendations require a supported advantage of at least 10% on one measure, with no more than 10% worse performance on the other. Intervals describe repeated trials on these tasks only."));
    root.append(detail("Why this conclusion", why));
    root.append(detail("Coverage and failures", list(comparison.contenders.map(row => `${row.label}: ${row.successes} successful of ${row.scheduled} scheduled trials; ${Object.entries(row.counts).filter(([, count]) => count > 0).map(([name, count]) => `${count} ${name.replaceAll("_", " ")}`).join(", ")}.`))));
  }
  root.append(detail("Limits of this comparison", list(comparison?.limitations ?? ["Evidence has not been evaluated yet."])));
  const provenance = list([`Runtime: ${kickoff.provider} ${kickoff.runtime_version}`, `Decision policy: ${comparison?.policy_id ?? experiment.conditions.decision_policy}`, `Evidence: ${current.report_id}`, `Verified change record: ${experiment.change.diff_digest}`]);
  root.append(detail("Sources and configuration", provenance));
  return root;
}

function contenderTable(rows, reportId) {
  const table = el("table", null, "comparison-table");
  const head = el("thead");
  const tr = el("tr");
  const body = el("tbody");
  const columns = [["Harness", null], ["Trials passed", "successes"], ["Cost / success", "cost_per_success_usd"], ["Time / trial", "mean_duration_seconds"], ["Tokens", "total_tokens"]];
  function draw(values) {
    body.replaceChildren();
    for (const row of values) {
      const node = el("tr");
      const name = el("th");
      name.scope = "row";
      name.append(link(row.label, "/Run_Detail", {comparison: reportId, version: row.id}));
      if (!row.eligible) name.append(el("span", row.coverage_complete ? "Failed required checks" : "Incomplete evidence", "comparison-note"));
      node.append(name, el("td", `${row.successes} / ${row.scheduled}`), el("td", row.cost_per_success_usd == null ? "Unknown" : money(row.cost_per_success_usd), row.cost_per_success_usd == null ? "comparison-missing" : null), el("td", row.mean_duration_seconds == null ? "Unknown" : seconds(row.mean_duration_seconds), row.mean_duration_seconds == null ? "comparison-missing" : null), el("td", row.total_tokens == null ? "Unknown" : tokens(row.total_tokens), row.total_tokens == null ? "comparison-missing" : null));
      body.append(node);
    }
  }
  for (const [title, field] of columns) {
    const cell = el("th");
    cell.scope = "col";
    if (field) {
      const button = el("button", title);
      let ascending = true;
      button.addEventListener("click", () => {
        for (const th of tr.children) th.removeAttribute("aria-sort");
        cell.setAttribute("aria-sort", ascending ? "ascending" : "descending");
        draw(sortNumericRows(rows, field, ascending));
        ascending = !ascending;
      });
      cell.append(button);
    } else cell.textContent = title;
    tr.append(cell);
  }
  head.append(tr);
  table.append(head, body);
  draw(rows);
  return table;
}

export function renderHistory(reports, state = {}) {
  const root = el("div", null, "harness-comparison");
  const versions = versionHistory(reports);
  if (!versions.length) return empty("No tested versions yet", reports);
  for (const version of versions.filter(v => !state.version || v.id === state.version)) {
    const article = el("article", null, "version-entry");
    article.append(el("h2", version.label));
    for (const report of version.runs) {
      const experiment = report.experiment;
      const history = experiment.comparison?.history;
      const entry = el("section");
      const title = el("h3");
      title.append(link(`${labels[history?.status] ?? "Pending"} · ${date(report.finished_at ?? report.updated_at)}`, "/", {comparison: report.report_id}));
      entry.append(title, el("p", experiment.change.summary), el("p", `Hypothesis: ${experiment.change.hypothesis}`));
      if (history) entry.append(el("p", history.summary));
      if (experiment.change.rerun_reason) entry.append(el("p", `Rerun: ${experiment.change.rerun_reason}`));
      for (const id of experiment.predecessor_result_ids) entry.append(link("Compared with this predecessor", "/", {comparison: id}));
      if (experiment.supersedes_report_id) entry.append(el("p", "Corrected evidence revision; the original result remains available."), link("Original evidence", "/Run_Detail", {comparison: experiment.supersedes_report_id}));
      article.append(entry);
    }
    root.append(article);
  }
  if (!root.children.length) return empty("That version is unavailable", reports);
  return root;
}

export function trialLabel(trial) {
  if (trial.protected_state === false) return "Protected files changed";
  if (trial.correctness === false) return "Failed tests";
  if (trial.status === "completed" && trial.correctness === true && trial.protected_state === true) return "Passed";
  return trial.status === "completed" ? "Ungraded" : trial.status.replaceAll("_", " ");
}

export function renderEvidence(reports, state = {}) {
  const current = selectComparison(reports, state.comparison);
  if (!current) return empty("That comparison evidence is unavailable", reports);
  const root = el("div", null, "harness-comparison");
  root.append(link("Back to the comparison", "/", {comparison: current.report_id}));
  root.append(el("h2", current.experiment.label), evidenceBadge(current));
  const referenced = new Set([current.report_id, ...current.experiment.baseline_result_ids]);
  const trials = reports.filter(r => referenced.has(r.report_id)).flatMap(r => r.experiment?.trials ?? []);
  const names = new Map(reports.flatMap(r => r.experiment?.contenders ?? []).map(c => [c.id, c.label]));
  const selectLabel = el("label", "Task ");
  const select = el("select");
  select.setAttribute("aria-label", "Filter task evidence");
  for (const task of ["", ...current.experiment.conditions.task_ids]) {
    const option = el("option", task || "All tasks");
    option.value = task;
    option.selected = task === (state.task ?? "");
    select.append(option);
  }
  select.addEventListener("change", () => { location.href = comparisonUrl("/Run_Detail", {...state, comparison: current.report_id, task: select.value}); });
  selectLabel.append(select);
  root.append(selectLabel);
  if (state.task && !current.experiment.conditions.task_ids.includes(state.task)) root.append(el("p", "That task is not part of this comparison."));
  for (const task of current.experiment.conditions.task_ids.filter(t => !state.task || state.task === t)) {
    const section = el("section");
    section.append(el("h3", task.replaceAll("-", " ")));
    const selected = trials.filter(t => t.task_id === task && (!state.version || state.version === t.contender_id));
    if (!selected.length) section.append(el("p", "No recorded trials for this selection."));
    for (const trial of selected) {
      const title = `${names.get(trial.contender_id) ?? "Harness"} · trial ${trial.attempt} · ${trialLabel(trial)}`;
      const content = el("div");
      content.append(el("p", `Execution: ${trial.status.replaceAll("_", " ")} · ${seconds(trial.duration_seconds)} · ${money(trial.cost_usd)}`));
      content.append(el("p", `${trial.usage_complete ? "Complete recorded usage" : "Usage incomplete"} · ${trial.child_count ?? "Unknown"} child agents · ${trial.interaction_count} user replies`));
      if (trial.incomplete_reasons?.length) content.append(list(trial.incomplete_reasons.map(value => value.replaceAll("_", " "))));
      if (trial.model_usage.length) content.append(list(trial.model_usage.map(row => `${row.model}: ${row.input_tokens ?? "unknown"} input + ${row.cache_read_tokens ?? "unknown"} cache read + ${row.cache_write_tokens ?? "unknown"} cache write + ${row.output_tokens ?? "unknown"} output tokens`)));
      if (trial.session_usage?.length) content.append(detail("Agent model and effort breakdown", list(trial.session_usage.map(row => `${row.session === "root" ? "Orchestrator" : row.session.replace("child_", "Child ")}: ${row.model} · ${row.effort ?? "unreported"} effort · ${row.input_tokens ?? "unknown"} input / ${row.output_tokens ?? "unknown"} output tokens`))));
      section.append(detail(title, content));
    }
    root.append(section);
  }
  return root;
}
