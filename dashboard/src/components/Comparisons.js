import {TASK_TYPES, taskType, summarizeTaskTypes} from "./Task_Types.js";
import {renderCollaboration, renderCollaborationEvidence} from "./Collaboration.js";

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
  quality_ineligible: "A contender failed a required test or has a confirmed remaining defect.",
  usage_incomplete: "Some model usage is missing, so a complete cost comparison is unavailable.",
  pricing_unavailable: "Comparable pricing is unavailable for some attempted work.",
  incomplete_coverage: "The selected evidence does not cover every scheduled, graded trial.",
  cost_time_tradeoff: "Cost and speed favor different harnesses.",
  missing_or_ambiguous_evidence: "Selected comparison evidence is missing or ambiguous.",
  practical_advantage_supported: "The advantage clears the recorded practical-difference and uncertainty thresholds.",
  diagnostic_only: "This is a diagnostic run, not evidence for an overall recommendation.",
  diagnostic_reference: "A diagnostic result cannot serve as comparison or history evidence.",
  code_review_incomplete: "Final-patch code review is missing or incomplete for some scheduled trials.",
  code_review_protocol_mismatch: "Final-patch reviews did not use one matching protocol.",
  code_review_unconfirmed: "Reviewer claims remain unconfirmed.",
  code_review_defects: "Confirmed defects remain in at least one final patch.",
  sole_quality_eligible: "One contender passed every required test and has no confirmed remaining defects."
};
const money = v => v == null ? "Unavailable" : new Intl.NumberFormat("en-US", {style: "currency", currency: "USD", maximumFractionDigits: 4}).format(v);
const tokens = v => v == null ? "Unavailable" : new Intl.NumberFormat("en-US", {notation: "compact", maximumFractionDigits: 1}).format(v);
const seconds = v => v == null ? "Unavailable" : v < 60 ? `${v.toFixed(1)}s` : `${Math.floor(v / 60)}m ${Math.round(v % 60)}s`;
const date = v => v ? new Intl.DateTimeFormat("en-US", {month: "short", day: "numeric", year: "numeric"}).format(new Date(v)) : "Not finished";
const severities = ["P0", "P1", "P2", "P3"];

function reviewTrialsFor(contenderId, trials) {
  return trials.filter(trial => trial.contender_id === contenderId);
}

export function summarizeTests(contender, trials = []) {
  const selected = reviewTrialsFor(contender.id, trials);
  const scheduled = contender.scheduled ?? selected.length;
  return {
    passed: selected.filter(trial => trial.status === "completed" && trial.correctness === true).length,
    scheduled,
    protected_unknown: selected.filter(trial => trial.status === "completed" && trial.correctness === true && trial.protected_state == null).length,
    evidence_complete: selected.length >= scheduled
  };
}

export function summarizeCodeReview(contender, trials = []) {
  const selected = reviewTrialsFor(contender.id, trials);
  const aggregate = contender.code_review;
  const scheduled = aggregate?.scheduled ?? contender.scheduled ?? selected.length;
  const breakdown = {completed: 0, blocked: 0, incomplete: 0, missing: Math.max(0, scheduled - selected.length)};
  for (const trial of selected) {
    const status = trial.code_review?.status;
    if (status === "completed" || status === "blocked" || status === "incomplete") breakdown[status] += 1;
    else breakdown.missing += 1;
  }
  if (aggregate) {
    const breakdownExact = selected.length === scheduled;
    return {
      status: aggregate.status,
      completed: aggregate.completed,
      scheduled,
      protocol_id: aggregate.protocol_id,
      confirmed: Object.fromEntries(severities.map(name => [name, aggregate.confirmed?.[name] ?? 0])),
      unconfirmed: aggregate.unconfirmed ?? 0,
      evaluation_cost_usd: aggregate.evaluation_cost_usd ?? null,
      breakdown: breakdownExact ? breakdown : {completed: aggregate.completed, blocked: 0, incomplete: 0, missing: 0},
      breakdown_exact: breakdownExact
    };
  }
  const reviews = selected.map(trial => trial.code_review).filter(Boolean);
  if (!reviews.length) {
    return {status: "not_reviewed", completed: 0, scheduled, protocol_id: null, confirmed: Object.fromEntries(severities.map(name => [name, 0])), unconfirmed: 0, evaluation_cost_usd: null, breakdown, breakdown_exact: true};
  }
  const protocols = new Set(reviews.map(review => review.protocol_id).filter(Boolean));
  const confirmed = Object.fromEntries(severities.map(name => [name, 0]));
  let unconfirmed = 0;
  for (const review of reviews) {
    for (const finding of review.findings ?? []) {
      if (finding.status === "confirmed" && severities.includes(finding.severity)) confirmed[finding.severity] += 1;
      if (finding.status === "unconfirmed") unconfirmed += 1;
    }
  }
  const costs = reviews.map(review => review.usage_complete ? review.cost_usd : null);
  const evaluationCost = reviews.length === scheduled && costs.length && costs.every(Number.isFinite) ? costs.reduce((sum, cost) => sum + cost, 0) : null;
  const completed = breakdown.completed;
  const status = protocols.size > 1 ? "incompatible" : completed === scheduled && breakdown.blocked === 0 && breakdown.incomplete === 0 && breakdown.missing === 0 ? "completed" : "incomplete";
  return {status, completed, scheduled, protocol_id: protocols.size === 1 ? [...protocols][0] : null, confirmed, unconfirmed, evaluation_cost_usd: evaluationCost, breakdown, breakdown_exact: true};
}

export function codeReviewCoverageLabel(summary) {
  if (summary.status === "not_reviewed") return "Not reviewed";
  if (!summary.breakdown_exact) {
    const unresolved = Math.max(0, summary.scheduled - summary.completed);
    const coverage = unresolved ? `${summary.completed} / ${summary.scheduled} completed · ${unresolved} unresolved` : `${summary.completed} completed of ${summary.scheduled}`;
    return summary.status === "incompatible" ? `Incompatible protocols · ${coverage}` : coverage;
  }
  const coverage = [`${summary.completed} completed`];
  for (const status of ["blocked", "incomplete", "missing"]) {
    if (summary.breakdown[status]) coverage.push(`${summary.breakdown[status]} ${status}`);
  }
  const suffix = `${coverage.join(" · ")} of ${summary.scheduled}`;
  return summary.status === "incompatible" ? `Incompatible protocols · ${suffix}` : suffix;
}

export function codeReviewCountLabel(summary, value) {
  if (summary.status === "not_reviewed") return "Unknown";
  return summary.status === "completed" ? String(value) : `${value} recorded`;
}

export function summarizeInternalReview(contender, trials = []) {
  const aggregate = contender.code_review?.internal_review;
  if (aggregate) {
    const known = aggregate.scheduled > 0 && aggregate.recorded === aggregate.scheduled && [aggregate.found, aggregate.fixed, aggregate.unresolved].every(Number.isFinite);
    return {...aggregate, known};
  }
  const selected = reviewTrialsFor(contender.id, trials);
  const scheduled = contender.code_review?.scheduled ?? contender.scheduled ?? selected.length;
  const recorded = selected.map(trial => trial.code_review?.internal_review).filter(internal => internal?.status === "recorded");
  const known = scheduled > 0 && selected.length >= scheduled && recorded.length === scheduled && recorded.every(internal => [internal.found, internal.fixed, internal.unresolved].every(Number.isFinite));
  const total = field => known ? recorded.reduce((sum, internal) => sum + internal[field], 0) : null;
  return {recorded: recorded.length, scheduled, found: total("found"), fixed: total("fixed"), unresolved: total("unresolved"), known};
}

export function internalReviewCoverageLabel(summary) {
  return summary.known ? `Recorded for ${summary.recorded} / ${summary.scheduled} trials` : `Unknown (${summary.recorded} / ${summary.scheduled} trials documented)`;
}

function codeReviewState(rows, trials, winnerId) {
  const summaries = rows.map(row => summarizeCodeReview(row, trials));
  if (summaries.every(summary => summary.status === "not_reviewed")) return {kind: "absent", summaries};
  const protocols = new Set(summaries.map(summary => summary.protocol_id).filter(Boolean));
  if (summaries.some(summary => summary.status === "incompatible") || protocols.size > 1) return {kind: "incompatible", summaries};
  if (summaries.some(summary => summary.status !== "completed")) return {kind: "incomplete", summaries};
  if (protocols.size !== 1) return {kind: "incompatible", summaries};
  if (summaries.some(summary => summary.unconfirmed > 0)) return {kind: "unconfirmed", summaries};
  const winner = rows.findIndex(row => row.id === winnerId);
  if (winner >= 0 && severities.some(name => summaries[winner].confirmed[name] > 0)) return {kind: "winner_findings", summaries};
  return {kind: "complete", summaries};
}

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
  const reviewState = report.evidence?.review_state ?? (report.experiment.comparison?.provisional !== false ? "unreviewed" : "reviewed");
  const stateLabel = {reviewed: "independently checked", unreviewed: "unreviewed", quarantined: "quarantined"}[reviewState] ?? reviewState.replaceAll("_", " ");
  const comparisonLabel = report.experiment.comparison?.provisional === false ? "comparison evidence finalized" : "comparison evidence provisional";
  return el("p", `Report provenance · ${stateLabel}; ${comparisonLabel}. This is separate from final-patch code review.`, "comparison-meta");
}

function referencedTrials(reports, current) {
  const referenced = new Set([current.report_id, ...(current.experiment.baseline_result_ids ?? [])]);
  return reports.filter(report => referenced.has(report.report_id)).flatMap(report => report.experiment?.trials ?? []);
}

export function comparisonVerdict(report, trials = report.experiment.trials ?? []) {
  const comparison = report.experiment.comparison;
  const rows = comparison?.contenders ?? [];
  const winner = rows.find(row => row.id === comparison?.winner_id);
  const testHeading = winner ? `${winner.label} led the tests` : labels[comparison?.status] ?? "Results are still arriving";
  const testSummary = comparison?.summary ?? "Every scheduled trial must finish and be graded before the test comparison can support a conclusion.";
  if (report.experiment.purpose === "diagnostic") {
    return {heading: `Diagnostic result · ${testHeading}`, summary: `${testSummary} This diagnostic run covers a limited task sample and cannot establish an overall harness winner.`, reviewKind: "diagnostic"};
  }
  const review = codeReviewState(rows, trials, comparison?.winner_id);
  if (review.kind === "absent") return {heading: `Tests only · ${testHeading}`, summary: `${testSummary} No final-patch code review is recorded, so this report does not establish remaining code quality.`, reviewKind: review.kind};
  if (review.kind === "incompatible") return {heading: "Code review protocols do not match", summary: `Test verdict: ${testSummary} Final-patch review results from different protocols cannot support a code quality comparison.`, reviewKind: review.kind};
  if (review.kind === "incomplete") return {heading: "Code review coverage is incomplete", summary: `Test verdict: ${testSummary} Every scheduled final patch needs a completed review under the same protocol before this report can support a code quality conclusion.`, reviewKind: review.kind};
  if (review.kind === "unconfirmed") return {heading: "Reviewer claims remain unresolved", summary: `Test verdict: ${testSummary} Unconfirmed findings prevent a supported overall winner.`, reviewKind: review.kind};
  if (review.kind === "winner_findings") return {heading: "The selected harness has confirmed defects", summary: `Test verdict: ${testSummary} A harness with confirmed remaining defects cannot be the supported overall winner.`, reviewKind: review.kind};
  return {heading: winner ? `${winner.label} is the supported choice` : labels[comparison?.status] ?? "No clear winner", summary: testSummary, reviewKind: review.kind};
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
  const trials = referencedTrials(reports, current);
  const verdictContent = comparisonVerdict(current, trials);
  verdict.append(el("h2", verdictContent.heading));
  verdict.append(el("p", verdictContent.summary));
  verdict.append(evidenceBadge(current));
  root.append(verdict);
  root.append(renderCollaboration(current, comparison?.contenders ?? experiment.contenders, trials));
  root.append(renderTaskTypes(current, trials));
  if (comparison?.contenders.length) {
    root.append(contenderTable(comparison.contenders, trials, current.report_id));
    root.append(el("p", "Tests passed counts completed trials whose task tests passed; protected-file verification is reported separately. Execution cost includes failed attempts and all recorded model calls; figures use shared standard token rates, excluding pricing premiums and tool charges. Time is end-to-end agent work per trial.", "comparison-meta"));
    root.append(el("h2", "Final-patch code review"));
    root.append(el("p", "Confirmed remaining defects and unresolved reviewer claims are shown separately from test outcomes. Evaluation cost covers the review work only.", "comparison-meta"));
    root.append(codeReviewTable(comparison.contenders, trials, current.report_id));
    if (experiment.code_review) root.append(el("p", `Review campaign · protocol ${experiment.code_review.protocol_id} · total evaluation cost ${experiment.code_review.evaluation_cost_usd == null ? "unknown" : money(experiment.code_review.evaluation_cost_usd)}.`, "comparison-meta"));
    root.append(el("h3", "Internal repair evidence"));
    root.append(el("p", "Counts describe review findings and fixes recorded during the original implementation. They do not affect the final-patch review verdict.", "comparison-meta"));
    root.append(internalReviewTable(comparison.contenders, trials, current.report_id));
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
    root.append(detail("Coverage and failures", list(comparison.contenders.map(row => `${row.label}: ${row.successes} quality-qualified of ${row.scheduled} scheduled trials; ${Object.entries(row.counts).filter(([, count]) => count > 0).map(([name, count]) => `${count} ${name.replaceAll("_", " ")}`).join(", ")}.`))));
  }
  root.append(detail("Limits of this comparison", list(comparison?.limitations ?? ["Evidence has not been evaluated yet."])));
  const provenance = list([`Runtime: ${kickoff.provider} ${kickoff.runtime_version}`, `Decision policy: ${comparison?.policy_id ?? experiment.conditions.decision_policy}`, `Evidence: ${current.report_id}`, `Verified change record: ${experiment.change.diff_digest}`]);
  root.append(detail("Sources and configuration", provenance));
  return root;
}

function taskTypeObservation(group, report) {
  const rows = group.rows;
  if (!rows.length || rows.some(row => !row.complete)) return "Trial evidence is incomplete or ambiguous. Complete the scheduled trials before comparing this type.";
  const reviews = rows.map(row => summarizeCodeReview({id: row.id, scheduled: row.scheduled}, row.trials));
  const observations = [rows.every(row => row.passed === row.scheduled)
    ? "All harnesses passed the task tests."
    : rows.map(row => `${row.label}: ${row.passed} / ${row.scheduled} task tests passed`).join("; ") + "."];
  const protocols = new Set(reviews.map(review => review.protocol_id).filter(Boolean));
  if (reviews.some(review => review.status === "incompatible") || protocols.size > 1) observations.push("Review protocols differ; code quality cannot be compared.");
  else if (reviews.some(review => review.status !== "completed") || protocols.size !== 1) observations.push("Final-patch review is missing or incomplete; remaining code quality is unknown.");
  else {
    observations.push(rows.map((row, index) => `${row.label}: ${Object.values(reviews[index].confirmed).reduce((sum, count) => sum + count, 0)} confirmed remaining defects`).join("; ") + ".");
    if (reviews.some(review => review.unconfirmed)) observations.push("Unconfirmed reviewer claims remain unresolved.");
  }
  if (rows.some(row => row.trials.some(trial => trial.protected_state == null))) observations.push("Protected-file verification is unknown for some trials.");
  if (rows.some(row => row.trials.some(trial => trial.protected_state === false))) observations.push("Protected-state checks failed in some trials.");
  if (report.experiment.comparison?.status === "incompatible_conditions") observations.push("The recorded conditions are incompatible; efficiency cannot be compared.");
  else if (rows.length > 1) {
    const samePricing = rows.every(row => row.pricing_digest) && new Set(rows.map(row => row.pricing_digest)).size === 1;
    if (!samePricing) observations.push("Recorded costs lack one matching pricing schedule; cost cannot be compared.");
    for (const [field, label] of [["total_cost_usd", "lowest recorded execution cost"], ["mean_duration_seconds", "shortest recorded time per trial"]]) {
      if ((field === "total_cost_usd" && !samePricing) || !rows.every(row => Number.isFinite(row[field]))) continue;
      const minimum = Math.min(...rows.map(row => row[field]));
      const leaders = rows.filter(row => row[field] === minimum);
      if (leaders.length === 1) observations.push(`${leaders[0].label} had the ${label}.`);
      else observations.push(`${leaders.length === rows.length ? "All harnesses" : leaders.map(row => row.label).join(" and ")} tied for the ${label}.`);
    }
  }
  return observations.join(" ");
}

export function renderTaskTypes(report, trials) {
  const section = el("section", null, "task-types");
  section.append(el("h2", "By task type"), el("p", "Results within this comparison, including its selected baselines. These observations do not establish a winner for a whole task type.", "comparison-meta"));
  const groups = summarizeTaskTypes(report, trials);
  for (const group of [...groups.filter(group => group.task_ids.length), ...groups.filter(group => !group.task_ids.length)]) {
    const entry = el("section", null, "task-type");
    entry.append(el("h3", group.label));
    if (!group.task_ids.length) {
      entry.append(el("p", `Not tested in this comparison. ${group.description}`, "comparison-meta"));
      section.append(entry);
      continue;
    }
    entry.append(el("p", `${group.task_ids.length} ${group.task_ids.length === 1 ? "task" : "tasks"} × ${report.experiment.conditions.attempts} ${report.experiment.conditions.attempts === 1 ? "repetition" : "repetitions"} per harness. ${group.description}`, "comparison-meta"));
    entry.append(el("p", taskTypeObservation(group, report)));
    const region = el("div", null, "comparison-table-region");
    region.setAttribute("role", "region");
    region.setAttribute("aria-label", `${group.label} harness results`);
    region.setAttribute("tabindex", "0");
    const table = el("table", null, "comparison-table task-type-table");
    const head = el("thead");
    const heading = el("tr");
    for (const title of ["Harness", "Tests & review", "Recorded cost", "Time / trial", "Tokens"]) {
      const cell = el("th", title);
      cell.scope = "col";
      heading.append(cell);
    }
    head.append(heading);
    const body = el("tbody");
    for (const row of group.rows) {
      const item = el("tr");
      const name = el("th");
      name.scope = "row";
      name.append(link(row.label, "/Run_Detail", {comparison: report.report_id, type: group.id, version: row.id}));
      const quality = el("td", `${row.passed} / ${row.scheduled} tests passed`);
      if (!row.complete) quality.append(el("span", "Incomplete or ambiguous evidence", "comparison-note"));
      const review = summarizeCodeReview({id: row.id, scheduled: row.scheduled}, row.trials);
      quality.append(el("span", codeReviewCoverageLabel(review), "comparison-note"));
      if (review.status !== "not_reviewed") {
        quality.append(el("span", `${severities.map(severity => `${severity}: ${codeReviewCountLabel(review, review.confirmed[severity])}`).join(" · ")}; unconfirmed: ${codeReviewCountLabel(review, review.unconfirmed)}`, "comparison-note"));
      }
      item.append(name, quality, el("td", money(row.total_cost_usd)), el("td", seconds(row.mean_duration_seconds)), el("td", tokens(row.total_tokens)));
      body.append(item);
    }
    table.append(head, body);
    region.append(table);
    const measurements = el("div");
    measurements.append(region, el("p", "Recorded execution cost uses each trial’s original pricing schedule and includes failed attempts and all recorded model calls. Review evaluation cost is separate. Missing or incomplete measurements remain unavailable.", "comparison-meta"), link(`Inspect ${group.label.toLowerCase()} evidence`, "/Run_Detail", {comparison: report.report_id, type: group.id}));
    entry.append(detail("Compare harness measurements", measurements));
    section.append(entry);
  }
  return section;
}

function contenderTable(rows, trials, reportId) {
  const table = el("table", null, "comparison-table");
  const head = el("thead");
  const tr = el("tr");
  const body = el("tbody");
  const values = rows.map(row => {
    const testSummary = summarizeTests(row, trials);
    return {...row, test_summary: testSummary, tests_passed: testSummary.passed};
  });
  const columns = [["Harness", null], ["Tests passed", "tests_passed"], ["Execution cost", "total_cost_usd"], ["Time / trial", "mean_duration_seconds"], ["Tokens", "total_tokens"]];
  function draw(values) {
    body.replaceChildren();
    for (const row of values) {
      const node = el("tr");
      const name = el("th");
      name.scope = "row";
      name.append(link(row.label, "/Run_Detail", {comparison: reportId, version: row.id}));
      if (row.test_summary.protected_unknown) name.append(el("span", "Protected state unknown", "comparison-note"));
      else if (!row.eligible) {
        const review = summarizeCodeReview(row, trials);
        const note = !row.coverage_complete ? "Incomplete task evidence"
          : row.successes < row.scheduled ? "Failed task checks"
          : review.status === "not_reviewed" ? "Code review not recorded"
          : review.status !== "completed" ? "Code review incomplete"
          : review.unconfirmed > 0 ? "Unresolved review claims"
          : severities.some(severity => review.confirmed[severity] > 0) ? "Confirmed remaining defects"
          : "Quality qualification unresolved";
        name.append(el("span", note, "comparison-note"));
      }
      const testCell = el("td", `${row.test_summary.passed} / ${row.test_summary.scheduled}`);
      if (!row.test_summary.evidence_complete) testCell.append(el("span", "Raw test evidence incomplete", "comparison-note"));
      node.append(name, testCell, el("td", row.total_cost_usd == null ? "Unknown" : money(row.total_cost_usd), row.total_cost_usd == null ? "comparison-missing" : null), el("td", row.mean_duration_seconds == null ? "Unknown" : seconds(row.mean_duration_seconds), row.mean_duration_seconds == null ? "comparison-missing" : null), el("td", row.total_tokens == null ? "Unknown" : tokens(row.total_tokens), row.total_tokens == null ? "comparison-missing" : null));
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
        draw(sortNumericRows(values, field, ascending));
        ascending = !ascending;
      });
      cell.append(button);
    } else cell.textContent = title;
    tr.append(cell);
  }
  head.append(tr);
  table.append(head, body);
  draw(values);
  return table;
}

function codeReviewTable(rows, trials, reportId) {
  const region = el("div", null, "comparison-table-region");
  region.setAttribute("role", "region");
  region.setAttribute("aria-label", "Final-patch code review comparison");
  region.setAttribute("tabindex", "0");
  const table = el("table", null, "comparison-table review-table");
  const head = el("thead");
  const heading = el("tr");
  for (const name of ["Harness", "Review coverage", ...severities, "Unconfirmed", "Evaluation cost"]) {
    const cell = el("th", name);
    cell.scope = "col";
    heading.append(cell);
  }
  head.append(heading);
  const body = el("tbody");
  for (const row of rows) {
    const summary = summarizeCodeReview(row, trials);
    const item = el("tr");
    const name = el("th");
    name.scope = "row";
    name.append(link(row.label, "/Run_Detail", {comparison: reportId, version: row.id}));
    const coverage = el("td", codeReviewCoverageLabel(summary));
    if (summary.protocol_id) coverage.append(el("span", `Protocol ${summary.protocol_id}`, "comparison-note"));
    item.append(name, coverage);
    for (const severity of severities) item.append(el("td", codeReviewCountLabel(summary, summary.confirmed[severity]), summary.status === "not_reviewed" ? "comparison-missing" : null));
    item.append(el("td", codeReviewCountLabel(summary, summary.unconfirmed), summary.status === "not_reviewed" ? "comparison-missing" : null));
    item.append(el("td", summary.evaluation_cost_usd == null ? "Unknown" : money(summary.evaluation_cost_usd), summary.evaluation_cost_usd == null ? "comparison-missing" : null));
    body.append(item);
  }
  table.append(head, body);
  region.append(table);
  return region;
}

function internalReviewTable(rows, trials, reportId) {
  const table = el("table", null, "comparison-table internal-review-table");
  const head = el("thead");
  const heading = el("tr");
  for (const name of ["Harness", "Documentation", "Found", "Fixed", "Unresolved"]) {
    const cell = el("th", name);
    cell.scope = "col";
    heading.append(cell);
  }
  head.append(heading);
  const body = el("tbody");
  for (const row of rows) {
    const summary = summarizeInternalReview(row, trials);
    const item = el("tr");
    const name = el("th");
    name.scope = "row";
    name.append(link(row.label, "/Run_Detail", {comparison: reportId, version: row.id}));
    item.append(name, el("td", internalReviewCoverageLabel(summary), summary.known ? null : "comparison-missing"));
    for (const field of ["found", "fixed", "unresolved"]) item.append(el("td", summary.known ? String(summary[field]) : "Unknown", summary.known ? null : "comparison-missing"));
    body.append(item);
  }
  table.append(head, body);
  return table;
}

function internalReviewHistoryText(summary) {
  if (!summary.known) return `Internal repair evidence: ${internalReviewCoverageLabel(summary).toLowerCase()}.`;
  return `Internal repair evidence: ${summary.found} found · ${summary.fixed} fixed · ${summary.unresolved} unresolved (${summary.recorded} / ${summary.scheduled} trials documented).`;
}

function reviewHistoryText(summary) {
  if (summary.status === "not_reviewed") return "Code review: not reviewed; evaluation cost unknown.";
  const confirmed = severities.map(name => `${name} ${codeReviewCountLabel(summary, summary.confirmed[name])}`).join(" · ");
  return `Code review: ${codeReviewCoverageLabel(summary)}; confirmed ${confirmed}; ${codeReviewCountLabel(summary, summary.unconfirmed)} unconfirmed; evaluation cost ${summary.evaluation_cost_usd == null ? "unknown" : money(summary.evaluation_cost_usd)}.`;
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
      const trials = referencedTrials(reports, report);
      const contender = experiment.comparison?.contenders.find(row => row.id === version.id) ?? {id: version.id, scheduled: trials.filter(trial => trial.contender_id === version.id).length};
      const entry = el("section");
      const title = el("h3");
      title.append(link(`Tests: ${labels[history?.status] ?? "Pending"} · ${date(report.finished_at ?? report.updated_at)}`, "/", {comparison: report.report_id}));
      entry.append(title, el("p", experiment.change.summary), el("p", `Hypothesis: ${experiment.change.hypothesis}`));
      if (history) entry.append(el("p", `Test history: ${history.summary}`));
      entry.append(el("p", `${reviewHistoryText(summarizeCodeReview(contender, trials))} ${internalReviewHistoryText(summarizeInternalReview(contender, trials))}`, "review-history"));
      for (const predecessor of history?.predecessor_contenders ?? []) entry.append(el("p", `${predecessor.label} predecessor · ${reviewHistoryText(summarizeCodeReview(predecessor))} ${internalReviewHistoryText(summarizeInternalReview(predecessor))}`, "review-history"));
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
  if (trial.status === "infrastructure_failure" && trial.incomplete_reasons?.includes("provider_transport_interrupted")) return "Provider connection interrupted";
  if (trial.status !== "completed") return trial.status.replaceAll("_", " ");
  if (trial.protected_state === false) return "Protected-state check failed";
  if (trial.correctness === false) return "Failed tests";
  if (trial.status === "completed" && trial.correctness === true && trial.protected_state === true) return "Passed";
  if (trial.status === "completed" && trial.correctness === true && trial.protected_state == null) return "Tests passed · protected state unknown";
  return trial.status === "completed" ? "Ungraded" : trial.status.replaceAll("_", " ");
}

function findingText(finding) {
  const location = finding.file ? `${finding.file}${finding.line == null ? "" : `:${finding.line}`}` : "Location unavailable";
  const category = finding.category ? ` · ${finding.category.replaceAll("_", " ")}` : "";
  return `${finding.severity} · ${finding.status} · ${finding.title} · ${location}${category}`;
}

function internalReviewText(internal) {
  if (!internal || internal.status === "unknown") return "Internal repair evidence: unknown.";
  const value = count => count == null ? "unknown" : count;
  return `Internal repair evidence: ${value(internal.found)} found · ${value(internal.fixed)} fixed · ${value(internal.unresolved)} unresolved.`;
}

function trialReview(review) {
  const section = el("section", null, "trial-review");
  section.append(el("h4", "Final-patch code review"));
  if (!review) {
    section.append(el("p", "Review status: not reviewed."), el("p", "Evaluation cost: unknown."), el("p", "Internal repair evidence: unknown."));
    return section;
  }
  section.append(el("p", `Review status: ${review.status.replaceAll("_", " ")} · protocol ${review.protocol_id ?? "unknown"}.`));
  const reviewCost = review.usage_complete ? review.cost_usd : null;
  section.append(el("p", `Evaluation: ${seconds(review.duration_seconds)} · ${reviewCost == null ? "cost unknown" : money(reviewCost)} · ${review.usage_complete ? "usage complete" : "usage incomplete"}.`));
  const findings = review.findings ?? [];
  if (findings.length) section.append(el("h5", "Recorded findings"), list(findings.map(findingText)));
  else section.append(el("p", "No findings are recorded in this review."));
  section.append(el("p", internalReviewText(review.internal_review)));
  if (review.model_usage?.length) section.append(detail("Review model usage", list(review.model_usage.map(row => `${row.model}: ${row.input_tokens ?? "unknown"} input + ${row.cache_read_tokens ?? "unknown"} cache read + ${row.cache_write_tokens ?? "unknown"} cache write + ${row.output_tokens ?? "unknown"} output tokens`))));
  return section;
}

export function renderEvidence(reports, state = {}) {
  const current = selectComparison(reports, state.comparison);
  if (!current) return empty("That comparison evidence is unavailable", reports);
  const root = el("div", null, "harness-comparison");
  root.append(link("Back to the comparison", "/", {comparison: current.report_id}));
  root.append(el("h2", current.experiment.label), evidenceBadge(current));
  const trials = referencedTrials(reports, current);
  const names = new Map(reports.flatMap(r => r.experiment?.contenders ?? []).map(c => [c.id, c.label]));
  const types = [...TASK_TYPES, {id: "unclassified", label: "Unclassified"}];
  const typeLabel = el("label", "Task type ", "evidence-filter");
  const typeSelect = el("select");
  typeSelect.setAttribute("aria-label", "Filter task type");
  for (const type of [{id: "", label: "All types"}, ...types]) {
    const option = el("option", type.label);
    option.value = type.id;
    option.selected = type.id === (state.type ?? "");
    typeSelect.append(option);
  }
  typeSelect.addEventListener("change", () => { location.href = comparisonUrl("/Run_Detail", {...state, comparison: current.report_id, type: typeSelect.value, task: ""}); });
  typeLabel.append(typeSelect);
  root.append(typeLabel);
  if (state.type && !types.some(type => type.id === state.type)) {
    root.append(el("p", "That task type is unavailable. Select an available type."));
    return root;
  }
  const tasks = current.experiment.conditions.task_ids.filter(task => !state.type || taskType(task) === state.type);
  const selectLabel = el("label", "Task ", "evidence-filter");
  const select = el("select");
  select.setAttribute("aria-label", "Filter task evidence");
  for (const task of ["", ...tasks]) {
    const option = el("option", task || "All tasks");
    option.value = task;
    option.selected = task === (state.task ?? "");
    select.append(option);
  }
  select.addEventListener("change", () => { location.href = comparisonUrl("/Run_Detail", {...state, comparison: current.report_id, task: select.value}); });
  selectLabel.append(select);
  root.append(selectLabel);
  if (state.task && !current.experiment.conditions.task_ids.includes(state.task)) root.append(el("p", "That task is not part of this comparison."));
  if (state.task && current.experiment.conditions.task_ids.includes(state.task) && !tasks.includes(state.task)) root.append(el("p", "That task is not part of this task type. Select another task or type."));
  if (!tasks.length) root.append(el("p", "No tasks of this type were scheduled in this comparison."));
  for (const task of tasks.filter(t => !state.task || state.task === t)) {
    const section = el("section");
    section.append(el("h3", task.replaceAll("-", " ")));
    const selected = trials.filter(t => t.task_id === task && (!state.version || state.version === t.contender_id));
    if (!selected.length) section.append(el("p", "No recorded trials for this selection."));
    for (const trial of selected) {
      const title = `${names.get(trial.contender_id) ?? "Harness"} · trial ${trial.attempt} · ${trialLabel(trial)}`;
      const content = el("div");
      content.append(el("p", `Whole-tree execution: ${trial.status.replaceAll("_", " ")} · ${seconds(trial.duration_seconds)} · ${money(trial.cost_usd)}`));
      content.append(el("p", `${trial.usage_complete ? "Complete recorded usage" : "Usage incomplete"} · ${trial.child_count ?? "Unknown"} child agents · ${trial.interaction_count} user replies`));
      if (trial.provider_recovery) {
        const recovery = trial.provider_recovery;
        content.append(el("p", `${recovery.transport_error_count} transport errors · ${seconds(recovery.allowance_seconds)} recovery allowance ${recovery.extension_applied ? "activated" : "not activated"}. Elapsed time includes connection waits.`));
      }
      if (trial.status === "infrastructure_failure" && trial.incomplete_reasons?.includes("provider_transport_interrupted")) content.append(el("p", "Provider connectivity interrupted this trial; it is excluded from harness quality judgments. Partial work and recorded usage are retained."));
      if (trial.incomplete_reasons?.length) content.append(list(trial.incomplete_reasons.map(value => value.replaceAll("_", " "))));
      if (trial.model_usage?.length) content.append(list(trial.model_usage.map(row => `${row.model}: ${row.input_tokens ?? "unknown"} input + ${row.cache_read_tokens ?? "unknown"} cache read + ${row.cache_write_tokens ?? "unknown"} cache write + ${row.output_tokens ?? "unknown"} output tokens`)));
      if (trial.session_usage?.length) content.append(detail("Orchestrator and child usage", list(trial.session_usage.map(row => `${row.session === "root" ? "Orchestrator" : row.session.replace("child_", "Child ")}: ${row.model} · ${row.effort ?? "unreported"} effort · ${row.input_tokens ?? "unknown"} input + ${row.cache_read_tokens ?? "unknown"} cache read + ${row.cache_write_tokens ?? "unknown"} cache write + ${row.output_tokens ?? "unknown"} output tokens`))));
      content.append(renderCollaborationEvidence(trial));
      content.append(trialReview(trial.code_review));
      section.append(detail(title, content));
    }
    root.append(section);
  }
  return root;
}
