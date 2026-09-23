import {HARNESS_FAMILIES} from "../data/Harness Catalog.js";
import {selectCohort} from "../data/Selected Cohort.js";

const DECISION_POLICY = "benchmark-readiness-v2";
const CORE_VERDICTS = new Set(["recommended", "no_clear_winner", "no_quality_qualified_winner"]);
const ATTEMPT_STATUSES = new Set(["completed", "agent_failed", "timeout"]);
const INCOMPLETE_STATUSES = new Set(["infrastructure_failure", "task_definition_gap", "cancelled", "pending"]);
const QUALITY_RUBRIC = "tim-work-quality-v2";
const QUALITY_DIMENSIONS = new Set([
  "plain_language",
  "appropriate_autonomy",
  "self_verification",
  "regression_coverage",
  "requirements_fit",
  "research_depth"
]);
const COMMUNICATION_RUBRIC = "tim-collaboration-v1";
const COMMUNICATION_DIMENSIONS = new Set([
  "directness",
  "proportionality",
  "progress_usefulness",
  "autonomy",
  "candor",
  "warmth",
  "restraint",
  "completion_clarity"
]);
const TOKEN_FIELDS = ["input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens"];
// Behavior metrics: how the agent talked and worked, per completed trial. "better" is the
// direction Tim prefers; it is a reading aid, never a score.
const TRANSCRIPT_METRICS = [
  {key: "assistant_words", label: "Assistant words", better: "lower", format: "count"},
  {key: "final_answer_words", label: "Final answer words", better: "lower", format: "count"},
  {key: "assistant_message_count", label: "Messages", better: "lower", format: "count"},
  {key: "slop_phrase_count", label: "Slop phrases", better: "lower", format: "count"},
  {key: "repeated_sentence_count", label: "Repeated sentences", better: "lower", format: "count"},
  {key: "prompt_restatement", label: "Restates the prompt", better: "lower", format: "rate"},
  {key: "unnecessary_question_count", label: "Unneeded questions", better: "lower", format: "count"},
  {key: "unnecessary_approval_request_count", label: "Unneeded approvals", better: "lower", format: "count"},
  {key: "useful_progress_update_rate", label: "Useful progress updates", better: "higher", format: "rate"},
  {key: "formatting_density", label: "Formatting density", better: "lower", format: "rate"},
  {key: "bullet_count", label: "Bullets", better: "lower", format: "count"},
  {key: "heading_count", label: "Headings", better: "lower", format: "count"},
  {key: "violation_count", label: "Contract violations", better: "lower", format: "count"}
];
const BEHAVIOR_GROUPS = [
  {id: "transcript", title: "Transcript metrics", note: "Deterministic counts over the user-visible root conversation.", metrics: TRANSCRIPT_METRICS},
  {id: "quality", title: `Work-quality grader (${QUALITY_RUBRIC})`, note: "Blinded automated grades, 1 to 5. Descriptive only; they never decide the ranking.", metrics: [...QUALITY_DIMENSIONS].map((key) => ({key, label: titleCase(key.replaceAll("_", " ")), better: "higher", format: "grade"}))},
  {id: "communication", title: `Communication grader (${COMMUNICATION_RUBRIC})`, note: "Older blinded automated grades, 1 to 5, where a run carried them.", metrics: [...COMMUNICATION_DIMENSIONS].map((key) => ({key, label: titleCase(key.replaceAll("_", " ")), better: "higher", format: "grade"}))}
];
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

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort(compareText).map((key) => [key, canonical(value[key])]));
  }
  return value;
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

function plural(count, singular, pluralForm = `${singular}s`) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function titleCase(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function harnessArm(version) {
  return version.identity == null ? null : `V${version.identity.slice("sha256:".length, "sha256:".length + 16)}`;
}

function completeDimensionMean(grade, rubric, requiredDimensions) {
  if (grade?.status !== "completed" || grade.rubric_version !== rubric) return null;
  const byName = new Map((grade.dimensions ?? []).map((dimension) => [dimension.name, dimension.score]));
  if (byName.size !== requiredDimensions.size) return null;
  for (const name of requiredDimensions) if (!Number.isFinite(byName.get(name))) return null;
  return mean([...requiredDimensions].map((name) => byName.get(name) / 5));
}

export function qualityFromGrade(grade) {
  return completeDimensionMean(grade, QUALITY_RUBRIC, QUALITY_DIMENSIONS);
}

function communicationFromGrade(grade) {
  return completeDimensionMean(grade, COMMUNICATION_RUBRIC, COMMUNICATION_DIMENSIONS);
}

function readyHarnesses(harnesses) {
  return harnesses.filter(({identity, state}) => identity != null && state === "ready");
}

function evidenceFlags(report) {
  const flags = [];
  const experiment = report.experiment ?? {};
  if (report.evidence?.review_state === "quarantined") flags.push("quarantined");
  if (experiment.purpose === "diagnostic") flags.push("diagnostic");
  if (experiment.conditions?.decision_policy !== DECISION_POLICY) flags.push("old policy");
  if (!CORE_VERDICTS.has(experiment.comparison?.status)) flags.push("no core verdict");
  if ((report.evidence?.limitations ?? []).includes("obsolete-methodology")) flags.push("obsolete methodology");
  return flags;
}

function primaryEvidenceState(flags) {
  for (const state of ["quarantined", "diagnostic", "old policy", "no core verdict", "obsolete methodology"]) {
    if (flags.includes(state)) return state.replace(" ", "-");
  }
  return "decision-grade";
}

function completeTokens(trial) {
  if (trial.usage_complete !== true || !Array.isArray(trial.model_usage) || !trial.model_usage.length) return null;
  let total = 0;
  for (const usage of trial.model_usage) {
    for (const field of TOKEN_FIELDS) {
      if (!Number.isFinite(usage?.[field])) return null;
      total += usage[field];
    }
  }
  return total;
}

function trialCorrectness(trial) {
  if (trial.status === "agent_failed" || trial.status === "timeout") return 0;
  if (trial.status !== "completed" || typeof trial.correctness !== "boolean") return null;
  return trial.correctness ? 1 : 0;
}

function metricValue(value) {
  if (typeof value === "boolean") return value ? 1 : 0;
  return Number.isFinite(value) ? value : null;
}

function dimensionScores(grade, rubric, requiredDimensions) {
  if (grade?.status !== "completed" || grade.rubric_version !== rubric) return {};
  const scores = {};
  for (const row of grade.dimensions ?? []) {
    if (requiredDimensions.has(row?.name) && Number.isInteger(row.score)) scores[row.name] = row.score;
  }
  return scores;
}

export function behaviorFromTrial(trial) {
  const metrics = trial.collaboration?.metrics;
  const grade = trial.collaboration?.grade;
  const transcript = {};
  if (metrics && typeof metrics === "object") {
    for (const {key} of TRANSCRIPT_METRICS) {
      const value = key === "violation_count"
        ? (Array.isArray(metrics.violations) ? metrics.violations.length : null)
        : metricValue(metrics[key]);
      if (value != null) transcript[key] = value;
    }
  }
  return {
    transcript,
    quality: dimensionScores(grade, QUALITY_RUBRIC, QUALITY_DIMENSIONS),
    communication: dimensionScores(grade, COMMUNICATION_RUBRIC, COMMUNICATION_DIMENSIONS)
  };
}

export function normalizeResults(reports, tests, harnesses) {
  const testById = new Map(tests.map((entry) => [entry.id, entry]));
  const harnessByIdentity = new Map(readyHarnesses(harnesses).map((version) => [version.identity, version]));
  const observations = new Map();

  for (const report of reports) {
    if (report.schema_version !== "3" || report.source?.kind !== "current") continue;
    const experiment = report.experiment;
    if (experiment?.conditions == null || !Array.isArray(experiment.trials)) continue;
    const reportId = report.report_id ?? report.run_id;
    const flags = evidenceFlags(report);
    const decisionEligible = flags.length === 0;
    const conditionKey = JSON.stringify(canonical(experiment.conditions));
    const kickoff = experiment.conditions.kickoff ?? {};
    const model = kickoff.model ?? "unknown";
    const effort = kickoff.effort ?? "unknown";
    const provisional = decisionEligible && (
      experiment.comparison?.provisional === true || report.evidence?.review_state !== "reviewed"
    );
    const selectedIds = experiment.evaluation_binding?.trial_ids;
    const selectedTrials = selectedIds == null ? null : new Set(selectedIds);

    for (const trial of experiment.trials) {
      if (selectedTrials != null && !selectedTrials.has(trial.trial_id)) continue;
      const test = testById.get(trial.task_id);
      const harness = harnessByIdentity.get(trial.contender_id);
      if (test == null || harness == null || trial.trial_id == null) continue;
      const grade = trial.collaboration?.grade;
      const cost = trial.usage_complete === true && Number.isFinite(trial.cost_usd) && trial.pricing_digest != null
        ? trial.cost_usd
        : null;
      const observation = {
        observationId: `${reportId}\0${trial.trial_id}`,
        trialId: trial.trial_id,
        attempt: trial.attempt,
        runId: report.run_id,
        reportId,
        reportLabel: experiment.label ?? report.run_id,
        updatedAt: report.finished_at ?? report.updated_at,
        harnessId: harness.id,
        harnessFamily: harness.family,
        harnessLabel: `${HARNESS_FAMILIES[harness.family].name} ${harness.versionLabel}`,
        predecessorId: harness.predecessorId,
        taskId: test.id,
        taskTitle: test.title,
        type: test.type,
        level: test.level,
        model,
        effort,
        modelKey: `${model}\0${effort}`,
        conditionKey,
        purpose: experiment.purpose,
        decisionPolicy: experiment.conditions.decision_policy,
        comparisonStatus: experiment.comparison?.status ?? null,
        provisional,
        reviewState: report.evidence?.review_state ?? "unreviewed",
        limitations: report.evidence?.limitations ?? [],
        evidenceFlags: flags,
        evidenceState: primaryEvidenceState(flags),
        decisionEligible,
        baselineReportIds: experiment.baseline_result_ids ?? [],
        predecessorReportIds: experiment.predecessor_result_ids ?? [],
        status: trial.status,
        correctness: trialCorrectness(trial),
        protectedState: trial.protected_state ?? null,
        codeReview: trial.code_review ?? null,
        incompleteReasons: trial.incomplete_reasons ?? [],
        quality: qualityFromGrade(grade),
        qualityProtocol: grade?.rubric_version === QUALITY_RUBRIC ? grade.protocol_id ?? null : null,
        communicationQuality: communicationFromGrade(grade),
        behavior: behaviorFromTrial(trial),
        runtime: Number.isFinite(trial.duration_seconds) ? trial.duration_seconds : null,
        tokens: completeTokens(trial),
        cost,
        pricingDigest: cost == null ? null : trial.pricing_digest,
        usageComplete: trial.usage_complete === true
      };
      observations.set(observation.observationId, observation);
    }
  }

  return [...observations.values()].sort((left, right) => compareText(
    `${left.updatedAt}\0${left.observationId}`,
    `${right.updatedAt}\0${right.observationId}`
  ));
}

export function defaultModel(observations) {
  const decisionPool = observations.filter(({decisionEligible}) => decisionEligible);
  const pool = decisionPool.length ? decisionPool : observations;
  const counts = new Map();
  for (const observation of pool) {
    const count = counts.get(observation.modelKey) ?? {quality: 0, observations: 0};
    count.observations += 1;
    if (observation.quality != null) count.quality += 1;
    counts.set(observation.modelKey, count);
  }
  return [...counts].sort((left, right) =>
    right[1].quality - left[1].quality ||
    right[1].observations - left[1].observations ||
    compareText(left[0], right[0])
  )[0]?.[0] ?? null;
}

function reportGroups(observations, model = null) {
  const groups = new Map();
  for (const observation of observations) {
    if (model != null && observation.modelKey !== model) continue;
    const group = groups.get(observation.reportId) ?? {
      id: observation.reportId,
      label: observation.reportLabel,
      updatedAt: observation.updatedAt,
      modelKey: observation.modelKey,
      conditionKey: observation.conditionKey,
      decisionEligible: observation.decisionEligible,
      provisional: observation.provisional,
      evidenceFlags: observation.evidenceFlags,
      baselineReportIds: observation.baselineReportIds,
      predecessorReportIds: observation.predecessorReportIds,
      observations: 0
    };
    group.observations += 1;
    groups.set(observation.reportId, group);
  }
  const selected = observations.filter(row => row.observationalCohort && (model == null || row.modelKey === model));
  if (selected.length) {
    groups.set(selected[0].observationalCohort.id, {
      id: selected[0].observationalCohort.id, label: selected[0].observationalCohort.label,
      observational: true, decisionEligible: false, observations: selected.length,
      updatedAt: selected[0].updatedAt
    });
  }
  return [...groups.values()];
}

export function defaultCohort(observations, model = null) {
  return reportGroups(observations, model).sort((left, right) =>
    Number(Boolean(right.observational)) - Number(Boolean(left.observational)) ||
    Number(right.decisionEligible) - Number(left.decisionEligible) ||
    compareText(right.updatedAt ?? "", left.updatedAt ?? "") ||
    right.observations - left.observations ||
    compareText(left.id, right.id)
  )[0]?.id ?? null;
}

function cohortObservations(observations, cohort) {
  if (cohort == null) return [];
  const selected = observations.filter(row => row.observationalCohort?.id === cohort);
  if (selected.length) return selected;
  const primary = observations.find(({reportId}) => reportId === cohort);
  if (primary == null) return [];
  const referenced = new Set([...primary.baselineReportIds, ...primary.predecessorReportIds]);
  const primaryHarnesses = new Set(
    observations.filter(({reportId}) => reportId === cohort).map(({harnessId}) => harnessId)
  );
  return observations.filter((observation) =>
    observation.reportId === cohort ||
    (
      referenced.has(observation.reportId) &&
      observation.conditionKey === primary.conditionKey &&
      !primaryHarnesses.has(observation.harnessId)
    )
  );
}

export function filterResults(observations, filters = {}) {
  const model = filters.model === "all" ? null : (filters.model ?? null);
  const scoped = filters.cohort == null ? observations : cohortObservations(observations, filters.cohort);
  return scoped.filter((observation) =>
    (filters.type == null || filters.type === "all" || observation.type === filters.type) &&
    (filters.level == null || filters.level === "all" || observation.level === Number(filters.level)) &&
    (model == null || observation.modelKey === model)
  );
}

export function admitResults(observations) {
  return observations.filter((observation) =>
    observation.decisionEligible &&
    ATTEMPT_STATUSES.has(observation.status) &&
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

function matchedTradeoff(observations, field, pricingCompatible = true) {
  if (field === "cost" && !pricingCompatible) return {quality: null, value: null, observations: 0, tasks: 0};
  const matched = observations.filter((observation) =>
    Number.isFinite(observation.quality) && Number.isFinite(observation[field])
  );
  return {
    quality: averageByTask(matched, "quality"),
    value: averageByTask(matched, field),
    observations: matched.length,
    tasks: new Set(matched.map(({taskId}) => taskId)).size
  };
}

function exactPairedDelta(observations, candidateId, referenceId, referenceField) {
  if (referenceId == null || candidateId === referenceId) return null;
  const candidates = observations.filter(({harnessId}) => harnessId === candidateId);
  const deltas = [];
  for (const candidate of candidates) {
    const selectedReports = new Set(candidate[referenceField]);
    const references = observations.filter((reference) =>
      reference.harnessId === referenceId &&
      reference.taskId === candidate.taskId &&
      reference.attempt === candidate.attempt &&
      reference.modelKey === candidate.modelKey &&
      reference.conditionKey === candidate.conditionKey &&
      (reference.reportId === candidate.reportId || selectedReports.has(reference.reportId))
    );
    const referenceScore = mean(references.map(({correctness}) => correctness));
    if (Number.isFinite(candidate.correctness) && Number.isFinite(referenceScore)) {
      deltas.push(candidate.correctness - referenceScore);
    }
  }
  return mean(deltas);
}

function evidenceGaps(observations) {
  const findings = observations.flatMap(({codeReview}) => codeReview?.findings ?? []);
  return {
    agentFailures: observations.filter(({status}) => status === "agent_failed" || status === "timeout").length,
    infrastructure: observations.filter(({status}) => INCOMPLETE_STATUSES.has(status)).length,
    protectedUnknown: observations.filter(({protectedState}) => protectedState == null).length,
    protectedFailed: observations.filter(({protectedState}) => protectedState === false).length,
    unreviewed: observations.filter(({codeReview}) => codeReview?.status !== "completed").length,
    confirmedFindings: findings.filter(({status}) => status === "confirmed").length,
    unconfirmedFindings: findings.filter(({status}) => status === "unconfirmed").length,
    internalUnresolved: observations.reduce((sum, {codeReview}) =>
      sum + (codeReview?.internal_review?.unresolved ?? 0), 0),
    incompleteReasons: observations.reduce((sum, {incompleteReasons}) => sum + incompleteReasons.length, 0),
    missingUsage: observations.filter(({usageComplete}) => !usageComplete).length
  };
}

export function aggregateHarnesses(observations, harnesses, filters = {}) {
  const model = filters.model === "all" || filters.model == null ? defaultModel(observations) : filters.model;
  const cohort = filters.cohort ?? defaultCohort(observations, model);
  const scoped = filterResults(observations, {...filters, model, cohort});
  const observational = observations.some(row => row.observationalCohort?.id === cohort);
  const admitted = observational
    ? scoped.filter(row => ATTEMPT_STATUSES.has(row.status) && Number.isFinite(row.correctness))
    : admitResults(scoped);
  const versions = readyHarnesses(harnesses);
  const eligibleVersions = versions.filter(({id}) => admitted.some(({harnessId}) => harnessId === id));
  const eligibleIds = new Set(eligibleVersions.map(({id}) => id));
  const taskSets = eligibleVersions.map(({id}) => new Set(
    admitted.filter(({harnessId}) => harnessId === id).map(({taskId}) => taskId)
  ));
  const sharedTasks = new Set(taskSets[0] ?? []);
  for (const tasks of taskSets.slice(1)) {
    for (const task of sharedTasks) if (!tasks.has(task)) sharedTasks.delete(task);
  }
  const decisionCohort = admitted.filter(({taskId}) => sharedTasks.has(taskId));
  const pricingDigests = new Set(decisionCohort.flatMap(({cost, pricingDigest}) =>
    Number.isFinite(cost) && pricingDigest != null ? [pricingDigest] : []
  ));
  const pricingCompatible = pricingDigests.size <= 1;
  const qualityProtocols = new Set(decisionCohort.filter(({quality}) => quality != null).map(({qualityProtocol}) => qualityProtocol));
  const qualityCompatible = qualityProtocols.size <= 1 && !qualityProtocols.has(null);
  const nothingId = versions.find(({family}) => family === "nothing")?.id ?? null;
  const rows = [];

  for (const harness of versions) {
    const rawValues = scoped.filter(({harnessId}) => harnessId === harness.id);
    const decisionValues = admitted.filter(({harnessId}) => harnessId === harness.id);
    const values = decisionCohort.filter(({harnessId}) => harnessId === harness.id);
    const gradeQuality = qualityCompatible && values.every(({quality}) => quality != null)
      ? averageByTask(values, "quality") : null;
    const chartValues = qualityCompatible ? values : [];
    const cost = pricingCompatible ? averageByTask(values, "cost") : null;
    const gaps = evidenceGaps(rawValues);
    const limitations = [...new Set(rawValues.flatMap(({limitations}) => limitations))];
    rows.push({
      id: harness.id,
      family: harness.family,
      label: `${HARNESS_FAMILIES[harness.family].name} ${harness.versionLabel}`,
      versionLabel: harness.versionLabel,
      eligible: !observational && eligibleIds.has(harness.id),
      observational,
      provisional: decisionValues.some(({provisional}) => provisional),
      cohort,
      cohortComplete: gaps.infrastructure === 0 && !limitations.some((limitation) =>
        limitation === "partial-run" || limitation === "infrastructure-failure"
      ),
      observations: decisionValues.length,
      exploratoryObservations: rawValues.filter(({decisionEligible}) => !decisionEligible).length,
      attempts: values.length,
      coveredTests: new Set(rawValues.map(({taskId}) => taskId)).size,
      sharedTests: sharedTasks.size,
      correctness: averageByTask(values, "correctness"),
      quality: gradeQuality,
      qualitySource: gradeQuality == null ? null : "trial-grades",
      qualityObservations: values.filter(({quality}) => quality != null).length,
      qualityScheduled: values.length,
      communicationQuality: averageByTask(rawValues, "communicationQuality"),
      communicationObservations: rawValues.filter(({communicationQuality}) => communicationQuality != null).length,
      runtime: averageByTask(values, "runtime"),
      tokens: averageByTask(values, "tokens"),
      cost,
      pricingCompatible,
      qualityCompatible,
      telemetryCoverage: {
        runtime: values.filter(({runtime}) => runtime != null).length,
        tokens: values.filter(({tokens}) => tokens != null).length,
        cost: pricingCompatible ? values.filter(({cost}) => cost != null).length : 0
      },
      tradeoffs: {
        runtime: matchedTradeoff(chartValues, "runtime"),
        tokens: matchedTradeoff(chartValues, "tokens"),
        cost: matchedTradeoff(chartValues, "cost", pricingCompatible)
      },
      gaps,
      limitations,
      evidenceFlags: [...new Set(rawValues.flatMap(({evidenceFlags}) => evidenceFlags))],
      deltaFromNothing: observational ? null : exactPairedDelta(admitted, harness.id, nothingId, "baselineReportIds"),
      deltaFromPredecessor: observational ? null : exactPairedDelta(admitted, harness.id, harness.predecessorId, "predecessorReportIds")
    });
  }

  return rows.sort((left, right) => {
    if (observational) return compareText(left.label, right.label);
    if (left.correctness == null && right.correctness != null) return 1;
    if (left.correctness != null && right.correctness == null) return -1;
    return (right.correctness ?? 0) - (left.correctness ?? 0) ||
      (right.quality ?? -1) - (left.quality ?? -1) ||
      compareText(left.label, right.label);
  });
}

function renderFilterButtons(values, selected, label, onChange) {
  const group = element("div", "results-filter-group nav nav-pills");
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", label);
  for (const [value, text] of values) {
    const button = element("button", `results-filter-button nav-link${value === selected ? " active" : ""}`, text);
    button.setAttribute("type", "button");
    button.setAttribute("aria-pressed", value === selected ? "true" : "false");
    button.addEventListener("click", () => onChange(value));
    group.append(button);
  }
  return group;
}

function renderSelect(label, className, options, selected, onChange) {
  const control = element("label", "results-model-filter");
  control.append(element("span", "form-label", label));
  const select = element("select", `form-select ${className}`);
  select.value = selected ?? "";
  for (const [value, text] of options) {
    const option = element("option", "", text);
    option.setAttribute("value", value);
    if (value === selected) option.setAttribute("selected", "");
    select.append(option);
  }
  select.addEventListener("change", () => onChange(select.value));
  control.append(select);
  return control;
}

function metricCell(value, formatter, className = "") {
  return element("td", className, formatter(value));
}

function gapText(row) {
  const parts = [];
  if (row.gaps.agentFailures) parts.push(plural(row.gaps.agentFailures, "agent failure"));
  if (row.gaps.infrastructure) parts.push(plural(row.gaps.infrastructure, "incomplete slot"));
  if (row.gaps.protectedUnknown) parts.push(plural(row.gaps.protectedUnknown, "protected state unknown", "protected states unknown"));
  if (row.gaps.protectedFailed) parts.push(plural(row.gaps.protectedFailed, "protected-state failure"));
  if (row.gaps.unreviewed) parts.push(plural(row.gaps.unreviewed, "not code-reviewed", "not code-reviewed"));
  if (row.gaps.confirmedFindings) parts.push(plural(row.gaps.confirmedFindings, "confirmed finding"));
  if (row.gaps.unconfirmedFindings) parts.push(plural(row.gaps.unconfirmedFindings, "unconfirmed finding"));
  if (row.gaps.internalUnresolved) parts.push(plural(row.gaps.internalUnresolved, "unresolved internal-review finding"));
  if (row.gaps.missingUsage) parts.push(plural(row.gaps.missingUsage, "missing usage ledger"));
  for (const limitation of row.limitations) parts.push(`limitation: ${limitation.replaceAll("-", " ")}`);
  return parts.length ? parts.join(" · ") : "No recorded evidence gaps";
}

function renderLeaderboard(rows, testCount) {
  const section = element("section", "results-panel results-leaderboard card");
  const heading = element("header", "results-section-heading card-header");
  const rankedHarnesses = rows.filter(({eligible}) => eligible).length;
  const sharedTests = rows.find(({eligible}) => eligible)?.sharedTests ?? 0;
  const provisional = rows.some(({eligible, provisional}) => eligible && provisional);
  const incomplete = rows.some(({eligible, cohortComplete}) => eligible && !cohortComplete);
  const observational = rows.some(row => row.observational);
  const explanation = observational
    ? "One selected attempt per task and harness. Observed outcomes, not a decision-grade ranking or causal proof. Recovery reports and original evidence warnings are preserved; missing Quality stays unknown."
    : rankedHarnesses === 0
    ? "No decision-grade ranking is available for this cohort. Exploratory coverage remains visible below."
    : `${rankedHarnesses} harnesses ranked by correctness, then Quality, on ${sharedTests} shared ${sharedTests === 1 ? "test" : "tests"}. ${provisional ? "The ranking is provisional. " : ""}${incomplete ? "The cohort has incomplete slots and is not a complete-cohort result. " : ""}Deltas use exact report references.`;
  heading.append(element("h2", "card-title", observational ? "Observed harness comparison" : "Decision-grade ranking"), element("p", "", explanation));
  const cue = element("p", "results-scroll-cue", "Swipe horizontally to see every metric.");
  const scroll = element("div", "results-table-scroll table-responsive");
  scroll.setAttribute("tabindex", "0");
  scroll.setAttribute("aria-label", "Harness leaderboard metrics");
  const table = element("table", "results-table table table-vcenter card-table");
  const head = element("thead");
  const headerRow = element("tr");
  for (const label of ["Harness", "Coverage", "Correctness", "Quality", "Evidence state", "Avg runtime", "Avg tokens", "Est. API cost", "Correctness vs Nothing", "Correctness vs previous"]) {
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
      element("small", "", observational ? plural(row.observations, "selected observation") : `${plural(row.observations, "decision observation")} · ${plural(row.exploratoryObservations, "exploratory observation")}`)
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
    if (row.eligible || row.observational) {
      coverage.append(
        element("strong", "", `${row.sharedTests} shared`),
        element("small", "", `${row.coveredTests} / ${testCount} observed`)
      );
    } else if (row.coveredTests) {
      coverage.append(element("strong", "", "Exploratory only"), element("small", "", `${row.coveredTests} / ${testCount} observed`));
    } else {
      coverage.append(element("strong", "", "Not tested"), element("small", "", "in this scope"));
    }
    const quality = element("td", "results-quality-cell");
    quality.append(element("strong", "", formatPercent(row.quality)));
    if (row.qualityObservations) {
      const compatibility = row.qualityCompatible ? "" : " · incompatible grading protocols";
      quality.append(element("small", "", `${row.qualityObservations}/${row.qualityScheduled} graded · automated${compatibility}`));
    } else if (row.communicationObservations) {
      quality.append(element("small", "", `${formatPercent(row.communicationQuality)} communication · automated`));
    }
    const evidence = element("td", "results-coverage-cell");
    evidence.append(
      element("strong", "", row.evidenceFlags.length ? row.evidenceFlags.map(titleCase).join(" · ") : (row.provisional ? "Provisional" : "Decision-grade")),
      element("small", "", gapText(row))
    );
    tr.append(
      name,
      coverage,
      score,
      quality,
      evidence,
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

function matrixEvidence(rawValues, excluded) {
  const parts = [];
  const count = (predicate) => rawValues.filter(predicate).length;
  const failures = count(({status}) => status === "agent_failed" || status === "timeout");
  const infrastructure = count(({status}) => INCOMPLETE_STATUSES.has(status));
  const protectedUnknown = count(({protectedState}) => protectedState == null);
  const unreviewed = count(({codeReview}) => codeReview?.status !== "completed");
  const confirmed = rawValues.reduce((sum, {codeReview}) => sum + (codeReview?.findings ?? []).filter(({status}) => status === "confirmed").length, 0);
  const internalUnresolved = rawValues.reduce((sum, {codeReview}) => sum + (codeReview?.internal_review?.unresolved ?? 0), 0);
  if (failures) parts.push(plural(failures, "agent failure"));
  if (infrastructure) parts.push(plural(infrastructure, "incomplete slot"));
  for (const flag of [...new Set(excluded.flatMap(({evidenceFlags}) => evidenceFlags))]) parts.push(flag);
  if (protectedUnknown) parts.push(plural(protectedUnknown, "protected state unknown", "protected states unknown"));
  if (unreviewed) parts.push(plural(unreviewed, "not code-reviewed", "not code-reviewed"));
  if (confirmed) parts.push(plural(confirmed, "confirmed finding"));
  if (internalUnresolved) parts.push(plural(internalUnresolved, "unresolved internal-review finding"));
  for (const limitation of [...new Set(rawValues.flatMap(({limitations}) => limitations))]) {
    parts.push(`limitation: ${limitation.replaceAll("-", " ")}`);
  }
  return parts;
}

function renderMatrix(observations, tests, harnesses, filters) {
  const filtered = filterResults(observations, filters);
  const observational = observations.some(row => row.observationalCohort?.id === filters.cohort);
  const admitted = observational ? filtered.filter(row => ATTEMPT_STATUSES.has(row.status) && Number.isFinite(row.correctness)) : admitResults(filtered);
  const admittedSet = new Set(admitted);
  const visibleTests = tests
    .filter((test) => (filters.type === "all" || test.type === filters.type) && (filters.level === "all" || test.level === Number(filters.level)))
    .sort((left, right) => left.level - right.level || compareText(left.title, right.title));
  const versions = displayHarnesses(harnesses);
  const section = element("section", "results-panel results-matrix card");
  const heading = element("header", "results-section-heading card-header");
  heading.append(
    element("h2", "card-title", "Test coverage"),
    element("p", "", observational ? "Selected observed correctness, not decision-grade scores. Original report warnings and review gaps remain visible." : "Decision scores include qualifying attempts. Exploratory, failed, incomplete, unreviewed, and protected-state-limited evidence remains visible beside them.")
  );
  const cue = element("p", "results-scroll-cue", "Swipe horizontally to compare every harness version.");
  const scroll = element("div", "results-table-scroll table-responsive");
  scroll.setAttribute("tabindex", "0");
  scroll.setAttribute("aria-label", "Test coverage by harness version");
  const table = element("table", "results-table results-matrix-table table table-vcenter card-table");
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
      const excluded = observational ? rawValues : rawValues.filter((value) => !admittedSet.has(value));
      const score = mean(values.map(({correctness}) => correctness));
      let unavailable = "—";
      if (rawValues.some(({evidenceFlags}) => evidenceFlags.includes("quarantined"))) unavailable = "Quarantined";
      else if (rawValues.some(({evidenceFlags}) => evidenceFlags.includes("diagnostic"))) unavailable = "Diagnostic";
      else if (rawValues.some(({evidenceFlags}) => evidenceFlags.includes("old policy"))) unavailable = "Old policy";
      else if (rawValues.some(({status}) => INCOMPLETE_STATUSES.has(status))) unavailable = "Incomplete";
      else if (rawValues.some(({status}) => status === "agent_failed" || status === "timeout")) unavailable = "Failed";
      const cell = element("td", score == null ? "results-matrix-empty" : "results-matrix-score");
      cell.append(element("strong", "", score == null ? unavailable : formatPercent(score)));
      const evidence = matrixEvidence(rawValues, excluded);
      if (evidence.length) cell.append(element("small", "results-cell-evidence", evidence.join(" · ")));
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
  const panel = element("article", "results-tradeoff-chart card");
  const header = element("header", "card-header");
  header.append(element("h3", "card-title", title));
  panel.append(header);
  const points = rows.flatMap((row) => {
    const tradeoff = row.tradeoffs[field];
    return tradeoff.quality != null && tradeoff.value != null ? [{row, tradeoff}] : [];
  });
  if (points.length === 0) {
    panel.append(element("p", "results-empty", `No decision-grade Quality and ${title.split(" vs ")[1].toLowerCase()} measurements share the same trials in this cohort.`));
    return panel;
  }

  const width = 520;
  const height = 300;
  const margin = {top: 20, right: 24, bottom: 42, left: 48};
  const observedMaximum = Math.max(...points.map(({tradeoff}) => tradeoff.value));
  const observedMinimum = Math.min(...points.map(({tradeoff}) => tradeoff.value));
  const padding = (observedMaximum - observedMinimum || observedMaximum || 1) * 0.1;
  const minValue = Math.max(0, observedMinimum - padding);
  const maxValue = observedMaximum + padding;
  const valueRange = maxValue - minValue;
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const svg = svgElement("svg", {viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `${ariaLabel}. Higher Quality is up; lower ${field} is right.`});
  for (const score of [0, 0.25, 0.5, 0.75, 1]) {
    const y = margin.top + (1 - score) * plotHeight;
    svg.append(
      svgElement("line", {x1: margin.left, x2: margin.left + plotWidth, y1: y, y2: y, class: "results-chart-grid"}),
      svgElement("text", {x: margin.left - 9, y: y + 4, class: "results-chart-axis", "text-anchor": "end"}, formatPercent(score))
    );
  }
  for (const ratio of [0, 0.5, 1]) {
    const x = margin.left + ratio * plotWidth;
    svg.append(svgElement("text", {x, y: height - 14, class: "results-chart-axis", "text-anchor": "middle"}, formatter(maxValue - valueRange * ratio)));
  }
  points.forEach(({row, tradeoff}) => {
    const x = margin.left + (maxValue - tradeoff.value) / valueRange * plotWidth;
    const y = margin.top + (1 - tradeoff.quality) * plotHeight;
    const point = svgElement("circle", {
      cx: x,
      cy: y,
      r: 7,
      class: `results-chart-point results-chart-${row.family}`,
      role: "img",
      "aria-label": `${row.label}: ${formatPercent(tradeoff.quality)} Quality, ${formatter(tradeoff.value)}, ${plural(tradeoff.observations, "matched trial")}`
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
  const communication = rows.reduce((sum, row) => sum + row.communicationObservations, 0);
  heading.append(
    element("h2", "mb-0", "Quality trade-offs"),
    element("p", "", "Better is toward the top right: higher Quality, less time, fewer tokens, and lower cost. Horizontal scales fit the displayed results with padding; Quality stays on a 0–100% scale. Each point uses matched trials. Cost is an API-equivalent estimate; incompatible pricing snapshots are not pooled.")
  );
  const qualityNote = element("div", "results-quality-note alert alert-info");
  qualityNote.append(
    element("strong", "", `Quality has ${plural(graded, "complete grade")} in this ${rows.some(row => row.observational) ? "observational" : "decision"} cohort.`),
    element("span", "", `Quality requires all six tim-work-quality-v2 dimensions; missing dimensions stay unknown. Trial grades are automated evidence and never decide the ranking.${communication ? ` ${plural(communication, "older communication grade")} ${communication === 1 ? "remains" : "remain"} exploratory automated evidence.` : ""}`)
  );
  const qualityRows = rows.filter(row => row.quality != null || row.communicationQuality != null || row.tradeoffs.runtime.quality != null);
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
      element("span", "", formatPercent(row.quality ?? row.communicationQuality)),
      element("span", "", `${formatRuntime(row.runtime)} · ${formatTokens(row.tokens)} · ${formatCost(row.cost)}`)
    );
    mobileSummary.append(item);
  }
  const charts = element("div", "results-tradeoff-grid");
  charts.append(
    renderTradeoffChart(rows, {field: "runtime", title: "Quality vs runtime", formatter: formatRuntime, ariaLabel: "Quality versus average runtime by harness on matched trials"}),
    renderTradeoffChart(rows, {field: "tokens", title: "Quality vs tokens", formatter: formatTokens, ariaLabel: "Quality versus average tokens by harness on matched trials"}),
    renderTradeoffChart(rows, {field: "cost", title: "Quality vs cost", formatter: formatCost, ariaLabel: "Quality versus estimated API-equivalent cost by harness on matched trials"})
  );
  section.append(heading, qualityNote, legend, mobileSummary, charts);
  return section;
}

export function aggregateBehavior(observations, harnesses, filters = {}) {
  // Every model and harness version with completed trials, side by side, so a change in
  // either axis is visible. Type and level filters apply; cohort and model filters do not.
  const scoped = observations.filter((row) =>
    row.status === "completed" &&
    (filters.type == null || filters.type === "all" || row.type === filters.type) &&
    (filters.level == null || filters.level === "all" || row.level === Number(filters.level))
  );
  const versions = readyHarnesses(harnesses);
  const models = [...new Map(scoped.map(({modelKey, model, effort}) => [modelKey, {model, effort}]))]
    .sort((left, right) => compareText(`${left[1].model}\0${left[1].effort}`, `${right[1].model}\0${right[1].effort}`));
  const columns = [];
  for (const [modelKey, {model, effort}] of models) {
    for (const harness of versions) {
      const values = scoped.filter((row) => row.modelKey === modelKey && row.harnessId === harness.id);
      if (!values.length) continue;
      const column = {
        modelKey, model, effort,
        harnessId: harness.id, family: harness.family,
        label: `${HARNESS_FAMILIES[harness.family].name} ${harness.versionLabel}`,
        trials: values.length,
        values: {}
      };
      for (const group of BEHAVIOR_GROUPS) {
        for (const {key} of group.metrics) {
          const samples = values.map((row) => row.behavior?.[group.id]?.[key]).filter((value) => Number.isFinite(value));
          column.values[`${group.id}.${key}`] = samples.length ? {mean: mean(samples), samples: samples.length} : null;
        }
      }
      columns.push(column);
    }
  }
  return columns;
}

function formatBehavior(value, format) {
  if (value == null) return "—";
  if (format === "rate") return `${Math.round(value * 100)}%`;
  if (format === "grade") return `${value.toFixed(2)} / 5`;
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function renderBehavior(columns) {
  const section = element("section", "results-panel results-behavior");
  const heading = element("header", "results-section-heading");
  heading.append(
    element("h2", "mb-0", "Behavior across models and harness versions"),
    element("p", "", "How each harness made the agent talk and work, per completed trial, for every kickoff model that has evidence. Values are means; the arrow shows the direction Tim prefers. Type and level filters apply; the cohort and model selectors do not, so a change in either axis stays visible.")
  );
  section.append(heading);
  if (!columns.length) {
    section.append(element("p", "results-scope-note", "No completed trials carry behavior evidence in this scope."));
    return section;
  }
  for (const group of BEHAVIOR_GROUPS) {
    const present = group.metrics.filter(({key}) => columns.some((column) => column.values[`${group.id}.${key}`] != null));
    if (!present.length) continue;
    const block = element("div", "results-behavior-group");
    block.append(element("h3", "results-behavior-title", group.title), element("p", "results-scope-note", group.note));
    const scroll = element("div", "results-table-scroll table-responsive");
    scroll.setAttribute("tabindex", "0");
    scroll.setAttribute("aria-label", `${group.title} by model and harness version`);
    const table = element("table", "results-table results-behavior-table table table-vcenter card-table");
    const head = element("thead");
    const headerRow = element("tr");
    headerRow.append(element("th", "", "Metric"));
    for (const column of columns) {
      const cell = element("th", "");
      cell.append(
        element("span", `results-harness-mark results-harness-${column.family}`),
        element("strong", "", column.label),
        element("small", "", `${column.model} · ${column.effort} · ${plural(column.trials, "trial")}`)
      );
      headerRow.append(cell);
    }
    head.append(headerRow);
    const body = element("tbody");
    for (const metric of present) {
      const row = element("tr");
      row.setAttribute("data-metric", `${group.id}.${metric.key}`);
      row.append(element("td", "", `${metric.label} ${metric.better === "lower" ? "↓" : "↑"}`));
      for (const column of columns) {
        const value = column.values[`${group.id}.${metric.key}`];
        const cell = element("td", "results-behavior-cell", formatBehavior(value?.mean ?? null, metric.format));
        if (value && value.samples !== column.trials) cell.append(element("small", "", ` (${value.samples}/${column.trials})`));
        row.append(cell);
      }
      body.append(row);
    }
    table.append(head, body);
    scroll.append(table);
    block.append(scroll);
    section.append(block);
  }
  return section;
}

function selectedTestCount(tests, filters) {
  return tests.filter((test) =>
    (filters.type === "all" || test.type === filters.type) &&
    (filters.level === "all" || test.level === Number(filters.level))
  ).length;
}

function cohortLabel(group) {
  const state = group.decisionEligible ? (group.provisional ? "provisional" : "decision-grade") : "exploratory";
  return `${group.label} · ${state}`;
}

function scopeDescription(observations, cohort) {
  const selected = observations.filter(row => row.observationalCohort?.id === cohort);
  if (selected.length) return `${selected.length} explicitly selected submissions from ${new Set(selected.map(row => row.reportId)).size} immutable reports · Observational · Original warnings retained`;
  const primary = observations.find(({reportId}) => reportId === cohort);
  if (primary == null) return "No report cohort available";
  const parts = primary.evidenceFlags.map(titleCase);
  if (primary.decisionEligible) parts.push("Decision-grade");
  if (primary.provisional) parts.push("Provisional");
  parts.push("exact referenced reports only");
  return parts.join(" · ");
}

export function renderResults({tests, harnesses, reports, selection = null}) {
  const observations = normalizeResults(reports, tests, harnesses);
  const selected = selectCohort(reports, selection);
  if (selected) {
    const ids = new Set(selected.members.map(member => `${member.reportId}\0${member.trialId}`));
    const matched = observations.filter(row => ids.has(row.observationId));
    if (matched.length !== ids.size) throw new Error("Selected cohort contains unknown catalog entries");
    for (const row of matched) row.observationalCohort = {id: selected.id, label: selected.label};
  }
  const admitted = admitResults(observations);
  const exploratory = observations.filter(({decisionEligible}) => !decisionEligible);
  const modelOptions = [...new Map(observations.map(({modelKey, model, effort}) => [modelKey, `${model} · ${effort}`]))]
    .sort((left, right) => compareText(left[1], right[1]));
  const state = {type: "all", level: "all", model: defaultModel(observations), cohort: null};
  state.cohort = defaultCohort(observations, state.model);
  const root = element("section", "results-page container-xl");
  root.setAttribute("aria-label", "Harness results");

  const intro = element("header", "results-intro page-header");
  intro.append(
    element("h1", "page-title fs-1", "Results"),
    element("p", "", "Compare correctness first, then inspect working quality beside the whole agent-tree time, tokens, and estimated API-equivalent cost required to get there."),
    element("p", "results-evidence-line", `${plural(admitted.length, "decision attempt")} · ${plural(exploratory.length, "exploratory observation")} · ${new Set(admitted.map(({taskId}) => taskId)).size} of ${tests.length} Toolbox tests represented by decision-grade evidence`)
  );

  const filters = element("nav", "results-filters card card-body");
  filters.setAttribute("aria-label", "Results scope");
  const body = element("div", "results-body");

  function update() {
    const groups = reportGroups(observations, state.model);
    if (!groups.some(({id}) => id === state.cohort)) state.cohort = defaultCohort(observations, state.model);
    filters.replaceChildren(
      renderFilterButtons([...TYPE_LABELS], state.type, "Test type", (value) => { state.type = value; update(); }),
      renderFilterButtons([["all", "All levels"], ...[1, 2, 3, 4].map((level) => [`${level}`, `L${level}`])], state.level, "Test level", (value) => { state.level = value; update(); })
    );
    filters.append(
      renderSelect("Model and effort", "results-model-select", modelOptions, state.model, (value) => {
        state.model = value;
        state.cohort = defaultCohort(observations, value);
        update();
      }),
      renderSelect("Evidence cohort", "results-cohort-select", groups.map((group) => [group.id, cohortLabel(group)]), state.cohort, (value) => {
        state.cohort = value;
        update();
      }),
      element("p", "results-scope-note", scopeDescription(observations, state.cohort))
    );

    const effective = {...state};
    const rows = aggregateHarnesses(observations, harnesses, effective);
    const testCount = selectedTestCount(tests, effective);
    body.replaceChildren(
      renderLeaderboard(rows, testCount),
      renderTradeoffs(rows),
      renderBehavior(aggregateBehavior(observations, harnesses, effective)),
      renderMatrix(observations, tests, harnesses, effective)
    );
  }

  update();
  root.append(intro, filters, body);
  return root;
}
