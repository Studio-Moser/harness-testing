import {HARNESS_FAMILIES} from "../data/Harness Catalog.js";
import {ANNOYANCE_COUNTERS, ANNOYANCE_PUNCTUATION} from "../data/Annoyance Phrases.js";

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
const ANNOYANCE_METRICS = [
  ...ANNOYANCE_COUNTERS.map(({key, label}) => ({key, label, better: "lower", format: "count"})),
  ...ANNOYANCE_PUNCTUATION.map(({key, label}) => ({key, label, better: "lower", format: "count"}))
];
const BEHAVIOR_GROUPS = [
  {id: "transcript", title: "Transcript metrics", note: "Deterministic counts over the user-visible root conversation.", metrics: TRANSCRIPT_METRICS},
  {id: "annoyance", title: "Annoyances", note: "Phrase and punctuation counts over the assistant's visible messages, from the list in data/Annoyance Phrases.js. Lower is better.", metrics: ANNOYANCE_METRICS},
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

// A version delivered to more than one provider has one identity per delivery.
function byAnyIdentity(versions) {
  return new Map(versions.flatMap((version) =>
    [version.identity, ...(version.extraIdentities ?? [])].map((identity) => [identity, version])
  ));
}

function evidenceFlags(report) {
  const flags = [];
  const experiment = report.experiment ?? {};
  if (experiment.conditions?.decision_policy !== DECISION_POLICY) flags.push("old policy");
  if (!CORE_VERDICTS.has(experiment.comparison?.status)) flags.push("no core verdict");
  if ((report.evidence?.limitations ?? []).includes("obsolete-methodology")) flags.push("obsolete methodology");
  return flags;
}

function primaryEvidenceState(flags) {
  for (const state of ["old policy", "no core verdict", "obsolete methodology"]) {
    if (flags.includes(state)) return state.replaceAll(" ", "-");
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

export function annoyanceFromTranscript(transcript) {
  if (!Array.isArray(transcript)) return {};
  const messages = transcript
    .filter((row) => row?.role === "assistant" && typeof row.content === "string")
    .map((row) => row.content);
  if (!messages.length) return {};
  const counts = {};
  for (const {key, phrases} of ANNOYANCE_COUNTERS) {
    let total = 0;
    for (const message of messages) {
      const lower = message.toLowerCase().replaceAll("\u2019", "'").replaceAll("\u2018", "'");
      for (const phrase of phrases) {
        let index = lower.indexOf(phrase);
        while (index !== -1) {
          total += 1;
          index = lower.indexOf(phrase, index + phrase.length);
        }
      }
    }
    counts[key] = total;
  }
  for (const {key, pattern} of ANNOYANCE_PUNCTUATION) {
    counts[key] = messages.reduce((sum, message) => sum + (message.match(pattern) ?? []).length, 0);
  }
  return counts;
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
    annoyance: annoyanceFromTranscript(trial.collaboration?.transcript),
    quality: dimensionScores(grade, QUALITY_RUBRIC, QUALITY_DIMENSIONS),
    communication: dimensionScores(grade, COMMUNICATION_RUBRIC, COMMUNICATION_DIMENSIONS)
  };
}

function sessionCost(session, pricing) {
  const rates = pricing?.[`${session.provider}/${session.model}`];
  if (!rates) return null;
  let total = 0;
  for (const [field, rate] of [["input_tokens", rates.input], ["output_tokens", rates.output], ["cache_read_tokens", rates.cache_read], ["cache_write_tokens", rates.cache_write]]) {
    const tokens = session[field] ?? 0;
    if (tokens && !Number.isFinite(rate)) return null;
    total += tokens * (rate ?? 0) / 1_000_000;
  }
  return total;
}

function sessionsFromTrial(trial, pricing) {
  if (!Array.isArray(trial.session_usage)) return [];
  return trial.session_usage
    .filter((row) => row && typeof row.session === "string")
    .map((row) => ({
      session: row.session,
      child: row.session !== "root",
      model: row.model ?? "unknown",
      effort: row.effort ?? "unknown",
      provider: row.provider ?? "unknown",
      tokens: TOKEN_FIELDS.reduce((sum, field) => sum + (Number.isFinite(row[field]) ? row[field] : 0), 0),
      cost: sessionCost(row, pricing)
    }));
}

export function normalizeResults(reports, tests, harnesses, pricing = null) {
  const testById = new Map(tests.map((entry) => [entry.id, entry]));
  const harnessByIdentity = byAnyIdentity(readyHarnesses(harnesses));
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
        usageComplete: trial.usage_complete === true,
        sessions: sessionsFromTrial(trial, pricing)
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

export const CAMPAIGN_COHORT_ID = "campaign";

// Each stitched campaign is a complete cohort: every scheduled slot filled once from its
// member reports, minus the trials that recovery or correction runs superseded. Its trials
// are decision evidence even though each member report is only a slice. A campaign has
// one kickoff model, so every trial belongs to at most one campaign.
export function applyCampaignCohort(observations, campaigns) {
  const list = campaigns == null ? [] : Array.isArray(campaigns) ? campaigns : [campaigns];
  for (const campaign of list) {
    if (campaign != null && typeof campaign === "object") tagCampaign(observations, campaign);
  }
  return observations;
}

// The campaign whose trials ran under the selected model, if any.
export function campaignForModel(observations, campaigns, model) {
  const digest = observations.find((row) => row.campaignCohort && row.modelKey === model)?.campaignCohort.digest;
  const list = campaigns == null ? [] : Array.isArray(campaigns) ? campaigns : [campaigns];
  return list.find((campaign) => campaign?.campaign_digest === digest) ?? null;
}

function tagCampaign(observations, campaign) {
  const members = new Set();
  const superseded = new Set();
  for (const lane of Object.values(campaign.lanes ?? {})) {
    for (const member of lane.members ?? []) members.add(member.report_id);
    // A replacement keeps the replaced trial's ID, so identity is report plus trial.
    for (const row of lane.superseded_trials ?? []) superseded.add(`${row.report_id}\0${row.trial_id}`);
  }
  if (!members.size) return;
  const status = campaign.status ?? "unknown";
  const label = `Campaign · ${status.replaceAll("_", " ")}`;
  for (const observation of observations) {
    if (!members.has(observation.reportId) || superseded.has(observation.observationId)) continue;
    if (observation.status === "pending") continue;
    // The stitched lane resolved its members' partial-run states.
    observation.campaignCohort = {id: CAMPAIGN_COHORT_ID, label, digest: campaign.campaign_digest ?? null};
    observation.decisionEligible = true;
    observation.evidenceFlags = [];
    observation.evidenceState = "campaign";
    observation.limitations = [];
    observation.provisional = true;
  }
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
  const campaign = observations.filter((row) => row.campaignCohort && (model == null || row.modelKey === model));
  if (campaign.length) {
    groups.set(CAMPAIGN_COHORT_ID, {
      id: CAMPAIGN_COHORT_ID, label: campaign[0].campaignCohort.label, campaign: true,
      decisionEligible: true, provisional: true, observations: campaign.length,
      updatedAt: campaign.map((row) => row.updatedAt).sort().at(-1)
    });
  }
  return [...groups.values()];
}

export function defaultCohort(observations, model = null) {
  return reportGroups(observations, model).sort((left, right) =>
    Number(Boolean(right.campaign)) - Number(Boolean(left.campaign)) ||
    Number(right.decisionEligible) - Number(left.decisionEligible) ||
    compareText(right.updatedAt ?? "", left.updatedAt ?? "") ||
    right.observations - left.observations ||
    compareText(left.id, right.id)
  )[0]?.id ?? null;
}

function cohortObservations(observations, cohort) {
  if (cohort == null) return [];
  if (cohort === CAMPAIGN_COHORT_ID) return observations.filter((row) => row.campaignCohort);
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
  const admitted = admitResults(scoped);
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
      eligible: eligibleIds.has(harness.id),
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
      deltaFromNothing: exactPairedDelta(admitted, harness.id, nothingId, "baselineReportIds"),
      deltaFromPredecessor: exactPairedDelta(admitted, harness.id, harness.predecessorId, "predecessorReportIds")
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
  const confirmed = rawValues.reduce((sum, {codeReview}) => sum + (codeReview?.findings ?? []).filter(({status}) => status === "confirmed").length, 0);
  if (failures) parts.push(plural(failures, "agent failure"));
  if (infrastructure) parts.push(plural(infrastructure, "incomplete slot"));
  for (const flag of [...new Set(excluded.flatMap(({evidenceFlags}) => evidenceFlags))]) parts.push(flag);
  if (confirmed) parts.push(plural(confirmed, "confirmed defect"));
  return parts;
}

function renderMatrix(observations, tests, harnesses, filters) {
  const filtered = filterResults(observations, filters);
  const admitted = admitResults(filtered);
  const admittedSet = new Set(admitted);
  const visibleTests = tests
    .filter((test) => (filters.type === "all" || test.type === filters.type) && (filters.level === "all" || test.level === Number(filters.level)))
    .sort((left, right) => left.level - right.level || compareText(left.title, right.title));
  const versions = displayHarnesses(harnesses);
  const section = element("section", "results-panel results-matrix card");
  const heading = element("header", "results-section-heading card-header");
  heading.append(
    element("h2", "card-title", "Results by task"),
    element("p", "", "API-equivalent cost, wall time and automated quality score per task for each harness version, under the selected model. A task that did not fully pass says so in red. Filter by type and difficulty to see where a harness helps or hurts.")
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
    name.append(element("strong", "", test.title), element("small", "", `Difficulty ${test.level} · ${TYPE_LABELS.get(test.type)}`));
    row.append(name);
    for (const version of versions) {
      const rawValues = filtered.filter(({taskId, harnessId}) => taskId === test.id && harnessId === version.id);
      const values = admitted.filter(({taskId, harnessId}) => taskId === test.id && harnessId === version.id);
      const excluded = rawValues.filter((value) => !admittedSet.has(value));
      const score = mean(values.map(({correctness}) => correctness));
      let unavailable = "—";
      if (rawValues.some(({evidenceFlags}) => evidenceFlags.includes("diagnostic"))) unavailable = "Diagnostic";
      else if (rawValues.some(({evidenceFlags}) => evidenceFlags.includes("old policy"))) unavailable = "Old policy";
      else if (rawValues.some(({status}) => INCOMPLETE_STATUSES.has(status))) unavailable = "Incomplete";
      else if (rawValues.some(({status}) => status === "agent_failed" || status === "timeout")) unavailable = "Failed";
      const cell = element("td", score == null ? "results-matrix-empty" : "results-matrix-score");
      if (score == null) {
        cell.append(element("strong", "", unavailable));
      } else {
        // Passing is the norm, so the headline is what it cost; correctness appears only when it slipped.
        const quality = mean(values.map((value) => value.quality));
        cell.append(element("strong", "", `${formatCost(mean(values.map(({cost}) => cost)))} · ${formatRuntime(mean(values.map(({runtime}) => runtime)))} · ${quality == null ? "—" : formatPercent(quality)} quality`));
        if (score < 1) cell.append(element("small", "results-cell-failure", score === 0 ? "Failed" : `${formatPercent(score)} correct`));
        const children = values.flatMap(({sessions}) => sessions.filter(({child}) => child));
        if (children.length) cell.append(element("small", "results-cell-subagents", `${plural(children.length, "subagent")} · ${modelMix(children)}`));
      }
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

function shortModel(model) {
  return model.replace(/^gpt-/, "").replace(/^claude-/, "");
}

function modelMix(sessions) {
  const counts = new Map();
  for (const {model, effort} of sessions) {
    const key = `${shortModel(model)} ${effort}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts].map(([key, count]) => (count > 1 ? `${key} ×${count}` : key)).join(", ");
}

function outputRate(pricing, provider, model) {
  return pricing?.[`${provider}/${model}`]?.output ?? null;
}

// How each harness used subagents under the selected model: how often, on which models,
// what they cost, and whether they ran on cheaper models than the kickoff.
export function aggregateDelegation(observations, harnesses, filters = {}, pricing = null) {
  const scoped = filterResults(observations, filters).filter((row) => ATTEMPT_STATUSES.has(row.status));
  const rows = [];
  for (const harness of readyHarnesses(harnesses)) {
    const values = scoped.filter(({harnessId}) => harnessId === harness.id);
    if (!values.length) continue;
    const sessions = values.flatMap(({sessions}) => sessions);
    const children = sessions.filter(({child}) => child);
    const withChildren = values.filter(({sessions}) => sessions.some(({child}) => child));
    const known = (list) => list.every(({cost}) => Number.isFinite(cost));
    const sum = (list, field) => list.reduce((total, row) => total + (row[field] ?? 0), 0);
    const totalCost = known(sessions) && sessions.length ? sum(sessions, "cost") : null;
    const childCost = known(children) ? sum(children, "cost") : null;
    const totalTokens = sum(sessions, "tokens");
    const kickoff = sessions.find(({child}) => !child);
    const kickoffRate = kickoff ? outputRate(pricing, kickoff.provider, kickoff.model) : null;
    let routing = "none";
    if (children.length) {
      const rates = children.map(({provider, model}) => outputRate(pricing, provider, model));
      const onKickoff = children.every(({model, effort}) => kickoff && model === kickoff.model && effort === kickoff.effort);
      if (onKickoff) routing = "kickoff";
      else if (kickoffRate != null && rates.every((rate) => rate != null && rate < kickoffRate)) routing = "cheaper";
      else if (kickoffRate != null && rates.some((rate) => rate != null && rate > kickoffRate)) routing = "pricier";
      else routing = "mixed";
    }
    rows.push({
      harnessId: harness.id,
      family: harness.family,
      label: `${HARNESS_FAMILIES[harness.family].name} ${harness.versionLabel}`,
      tasks: values.length,
      tasksWithSubagents: withChildren.length,
      subagents: children.length,
      models: modelMix(children),
      childCost,
      childCostShare: totalCost ? (childCost ?? 0) / totalCost : null,
      childTokenShare: totalTokens ? sum(children, "tokens") / totalTokens : null,
      ...delegatedTaskCost(scoped, harness.id, withChildren),
      routing
    });
  }
  return rows;
}

// On exactly the tasks where a harness delegated, what it spent against the other harnesses'
// mean on those same tasks. This answers "did delegating save money", not just "did it route".
function delegatedTaskCost(scoped, harnessId, withChildren) {
  const taskIds = new Set(withChildren.map(({taskId}) => taskId));
  if (!taskIds.size) return {delegatedCost: null, othersCost: null};
  const own = mean(withChildren.map(({cost}) => cost));
  const others = [...taskIds].map((taskId) => mean(scoped
    .filter((row) => row.taskId === taskId && row.harnessId !== harnessId)
    .map(({cost}) => cost)));
  return {delegatedCost: own, othersCost: others.every(Number.isFinite) ? mean(others) : null};
}

function renderDelegation(rows) {
  const section = element("section", "results-panel results-delegation card card-body");
  const heading = element("header", "results-section-heading");
  heading.append(
    element("h2", "card-title", "Subagents and routing"),
    element("p", "", "How often each harness delegated to subagents under the selected model, which models they ran on, and what they cost. \"Cheaper\" means every subagent ran on a model with a lower list price than the kickoff; \"kickoff\" means they reused the kickoff model. The last two columns compare the whole trial cost on the tasks where it delegated with the other harnesses' mean on the same tasks, which is what tells you whether delegating saved money. Costs are API-equivalent estimates from the pinned price list.")
  );
  section.append(heading);
  if (!rows.length) {
    section.append(element("p", "results-scope-note", "No completed trials in this scope yet."));
    return section;
  }
  const scroll = element("div", "results-table-scroll table-responsive");
  const table = element("table", "results-table table table-vcenter card-table");
  const head = element("thead");
  const headerRow = element("tr");
  for (const text of ["Harness", "Tasks delegated", "Subagents", "Models used", "Routing", "Subagent cost", "Share of cost", "Delegated tasks cost", "Others on those tasks"]) headerRow.append(element("th", "", text));
  head.append(headerRow);
  const body = element("tbody");
  const routingText = {none: "never delegated", kickoff: "kickoff model", cheaper: "cheaper models", pricier: "pricier models", mixed: "mixed"};
  for (const row of rows) {
    const tr = element("tr");
    const name = element("td", "results-harness-name");
    name.append(element("span", `results-harness-mark results-harness-${row.family}`), element("strong", "", row.label));
    tr.append(
      name,
      element("td", "", `${row.tasksWithSubagents} of ${row.tasks}`),
      element("td", "", String(row.subagents)),
      element("td", "results-delegation-models", row.models || "—"),
      element("td", "", routingText[row.routing]),
      element("td", "", row.subagents ? formatCost(row.childCost) : "—"),
      element("td", "", row.subagents ? formatPercent(row.childCostShare) : "—"),
      element("td", "", row.subagents ? formatCost(row.delegatedCost) : "—"),
      element("td", "", row.subagents ? formatCost(row.othersCost) : "—")
    );
    body.append(tr);
  }
  table.append(head, body);
  scroll.append(table);
  section.append(scroll);
  return section;
}

function renderBehavior(columns) {
  const section = element("section", "results-panel results-behavior");
  const heading = element("header", "results-section-heading");
  heading.append(
    element("h2", "mb-0", "Behavior by harness version"),
    element("p", "", "How each harness made the agent talk and work, per completed trial, under the selected model. Values are means; the arrow shows the direction Tim prefers. Switch the model above to compare behavior across models.")
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
        element("small", "", plural(column.trials, "trial"))
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

export function campaignVerdict(campaign, harnesses) {
  if (campaign == null || typeof campaign !== "object") return null;
  const byIdentity = byAnyIdentity(harnesses.filter(({identity}) => identity != null));
  const label = (id) => {
    const version = byIdentity.get(id);
    return version ? `${HARNESS_FAMILIES[version.family].name} ${version.versionLabel}` : (id ?? "—");
  };
  const lanes = Object.entries(campaign.lanes ?? {}).map(([lane, value]) => {
    const comparison = value.comparison ?? {};
    return {
      lane,
      status: comparison.status ?? "unknown",
      winner: comparison.winner_id ? label(comparison.winner_id) : null,
      reasons: comparison.reasons ?? [],
      unsolved: comparison.unsolved_tasks ?? [],
      limitations: value.limitations ?? [],
      contenders: (comparison.contenders ?? []).map((row) => ({
        label: label(row.id),
        family: byIdentity.get(row.id)?.family ?? "unknown",
        successes: row.successes,
        scheduled: row.scheduled,
        eligible: row.eligible === true,
        reviewed: row.reviewed !== false,
        unconfirmed: row.code_review?.unconfirmed ?? 0,
        meanCost: Number.isFinite(row.mean_cost_usd) ? row.mean_cost_usd : null,
        meanDuration: Number.isFinite(row.mean_duration_seconds) ? row.mean_duration_seconds : null
      }))
    };
  });
  return {
    status: campaign.status ?? "unknown",
    winner: campaign.winner_id ? label(campaign.winner_id) : null,
    reasons: campaign.reasons ?? [],
    lanes,
    digest: campaign.campaign_digest ?? null
  };
}

function ratioText(value, best) {
  return `${(value / best).toFixed(1)}×`;
}

// A plain-language read of each harness: what it does better or worse than the others in
// the selected scope, and which one to use. Every sentence is derived from the same
// numbers the tables show; nothing here is a model's opinion.
export function harnessRead(rows, behaviorColumns, verdict = null, delegation = []) {
  const scored = rows.filter((row) => row.observations > 0);
  if (!scored.length) return null;
  const finite = (values) => values.filter(Number.isFinite);
  const bestOf = (field, pick) => {
    const values = finite(scored.map((row) => row[field]));
    return values.length ? pick(...values) : null;
  };
  const bestCorrect = bestOf("correctness", Math.max);
  const bestCost = bestOf("cost", Math.min);
  const bestTime = bestOf("runtime", Math.min);
  const bestQuality = bestOf("quality", Math.max);
  const behavior = new Map();
  for (const column of behaviorColumns) {
    const value = (key) => column.values[key]?.mean ?? null;
    const annoyance = ANNOYANCE_METRICS.map(({key}) => value(`annoyance.${key}`)).filter(Number.isFinite);
    behavior.set(column.harnessId, {
      words: value("transcript.assistant_words"),
      approvals: value("transcript.unnecessary_approval_request_count"),
      questions: value("transcript.unnecessary_question_count"),
      annoyance: annoyance.length ? annoyance.reduce((sum, v) => sum + v, 0) : null
    });
  }
  const minWords = finite([...behavior.values()].map((b) => b.words));
  const minAnnoyance = finite([...behavior.values()].map((b) => b.annoyance));
  const quietest = minWords.length ? Math.min(...minWords) : null;
  const calmest = minAnnoyance.length ? Math.min(...minAnnoyance) : null;
  const allSameCorrectness = new Set(finite(scored.map((row) => row.correctness))).size === 1;
  const cards = scored.map((row) => {
    const pros = [];
    const cons = [];
    if (Number.isFinite(row.correctness)) {
      if (row.correctness === bestCorrect) {
        pros.push(allSameCorrectness && scored.length > 1
          ? `Same correctness as the others (${formatPercent(row.correctness)})`
          : `Most correct (${formatPercent(row.correctness)})`);
      } else {
        cons.push(`Less correct: ${formatPercent(row.correctness)} against ${formatPercent(bestCorrect)} for the best`);
      }
    }
    if (Number.isFinite(row.cost) && bestCost != null) {
      if (row.cost === bestCost) pros.push(`Cheapest per task (${formatCost(row.cost)})`);
      else if (row.cost / bestCost >= 1.2) cons.push(`Costs ${ratioText(row.cost, bestCost)} the cheapest (${formatCost(row.cost)} vs ${formatCost(bestCost)} per task)`);
    }
    if (Number.isFinite(row.runtime) && bestTime != null) {
      if (row.runtime === bestTime) pros.push(`Fastest per task (${formatRuntime(row.runtime)})`);
      else if (row.runtime / bestTime >= 1.2) cons.push(`Takes ${ratioText(row.runtime, bestTime)} the fastest (${formatRuntime(row.runtime)} vs ${formatRuntime(bestTime)} per task)`);
    }
    if (Number.isFinite(row.quality) && bestQuality != null) {
      if (row.quality === bestQuality && scored.filter((other) => other.quality === bestQuality).length === 1) pros.push(`Highest work-quality grade (${formatPercent(row.quality)})`);
      else if (bestQuality - row.quality >= 0.03) cons.push(`Lower work-quality grade (${formatPercent(row.quality)} vs ${formatPercent(bestQuality)})`);
    }
    const b = behavior.get(row.id);
    if (b) {
      if (Number.isFinite(b.words) && quietest != null) {
        if (b.words === quietest && behavior.size > 1) pros.push(`Says the least (${Math.round(b.words)} words per task)`);
        else if (b.words / quietest >= 1.25) cons.push(`Talks ${ratioText(b.words, quietest)} more than the quietest (${Math.round(b.words)} words per task)`);
      }
      if (Number.isFinite(b.approvals) && b.approvals >= 0.1) cons.push(`Asks for unneeded approvals (${b.approvals.toFixed(1)} per task)`);
      if (Number.isFinite(b.questions) && b.questions >= 0.1) cons.push(`Asks unneeded questions (${b.questions.toFixed(1)} per task)`);
      if (Number.isFinite(b.annoyance) && calmest != null) {
        if (b.annoyance === calmest && behavior.size > 1) pros.push(`Fewest annoyances (${b.annoyance.toFixed(1)} per task)`);
        else if (b.annoyance - calmest >= 1) cons.push(`More annoyances (${b.annoyance.toFixed(1)} per task vs ${calmest.toFixed(1)})`);
      }
    }
    const d = delegation.find(({harnessId}) => harnessId === row.id);
    if (d && d.subagents) {
      const where = `${d.tasksWithSubagents} of ${d.tasks} tasks (${d.models})`;
      const verb = d.routing === "cheaper" ? "Routed subagents to cheaper models" : d.routing === "kickoff" ? "Spawned subagents on the kickoff model" : "Spawned subagents";
      const ratio = d.delegatedCost != null && d.othersCost ? d.delegatedCost / d.othersCost : null;
      const outcome = ratio == null ? "" : `; those tasks cost ${formatCost(d.delegatedCost)} against ${formatCost(d.othersCost)} for the others`;
      // Delegation counts as a pro only when it actually made those tasks cheaper.
      if (ratio != null && ratio <= 0.8) pros.push(`${verb} in ${where}${outcome}`);
      else if (ratio != null && ratio < 1.2) pros.push(`${verb} in ${where} at about the same cost as the others`);
      else cons.push(`${verb} in ${where}${outcome}`);
    } else if (d && row.family === "studio-moser") {
      cons.push("Never used its model rubric to route a subagent");
    }
    return {id: row.id, family: row.family, label: row.label, pros, cons};
  });
  const ranked = [...cards].sort((left, right) => {
    const l = scored.find((row) => row.id === left.id);
    const r = scored.find((row) => row.id === right.id);
    return (r.correctness ?? -1) - (l.correctness ?? -1) || (l.cost ?? Infinity) - (r.cost ?? Infinity) || left.cons.length - right.cons.length;
  });
  const pick = verdict?.winner ? cards.find((card) => card.label === verdict.winner) ?? ranked[0] : ranked[0];
  const because = pick.pros.length ? pick.pros.map((text) => text.charAt(0).toLowerCase() + text.slice(1)).join(", ") : "it has the fewest drawbacks in this scope";
  return {
    recommendation: `Use ${pick.label}: ${because}.`,
    cards: ranked
  };
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

function renderTradeoffCharts(rows) {
  const section = element("div", "results-tradeoffs");
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
  section.append(legend, mobileSummary, charts);
  return section;
}

function renderHarnessRead(read, rows) {
  const section = element("section", "results-panel results-read card card-body");
  const heading = element("header", "results-section-heading");
  heading.append(element("h2", "card-title", "The read"));
  if (read == null) {
    heading.append(element("p", "", "No completed trials in this scope yet."));
    section.append(heading);
    return section;
  }
  heading.append(element("p", "results-read-recommendation", read.recommendation));
  section.append(heading);
  const grid = element("div", "results-read-grid");
  for (const card of read.cards) {
    const article = element("article", "results-read-card card");
    const body = element("div", "card-body");
    const title = element("h3", "card-title");
    title.append(element("span", `results-harness-mark results-harness-${card.family}`), element("span", "", card.label));
    body.append(title);
    for (const [name, items] of [["Pros", card.pros], ["Cons", card.cons]]) {
      body.append(element("h4", "results-read-list-title", name));
      const list = element("ul", "results-read-list");
      if (!items.length) list.append(element("li", "results-read-none", name === "Pros" ? "Nothing stands out" : "None in this scope"));
      for (const item of items) list.append(element("li", "", item));
      body.append(list);
    }
    article.append(body);
    grid.append(article);
  }
  section.append(grid);
  const charts = element("div", "results-read-charts");
  charts.append(
    element("p", "results-scope-note", "Quality against runtime, tokens and cost. Better is toward the top right. Each point uses matched trials under the selected model; more runs add more points."),
    renderTradeoffCharts(rows)
  );
  section.append(charts);
  return section;
}



function scopeDescription(observations, cohort, model) {
  if (cohort === CAMPAIGN_COHORT_ID) {
    const selected = observations.filter((row) => row.campaignCohort && row.modelKey === model);
    return `${selected.length} trials stitched from ${new Set(selected.map((row) => row.reportId)).size} reports · Decision-grade · Provisional until reviewed`;
  }
  const primary = observations.find(({reportId}) => reportId === cohort);
  if (primary == null) return "No report cohort available";
  const parts = primary.evidenceFlags.map(titleCase);
  if (primary.decisionEligible) parts.push("Decision-grade");
  if (primary.provisional) parts.push("Provisional");
  parts.push("exact referenced reports only");
  return parts.join(" · ");
}

export function renderResults({tests, harnesses, reports, campaign = null, pricing = null}) {
  const observations = applyCampaignCohort(normalizeResults(reports, tests, harnesses, pricing), campaign);
  const admitted = admitResults(observations);
  const modelOptions = [...new Map(observations.map(({modelKey, model, effort}) => [modelKey, `${model} · ${effort}`]))]
    .sort((left, right) => compareText(left[1], right[1]));
  const state = {type: "all", level: "all", model: defaultModel(observations), cohort: null};
  state.cohort = defaultCohort(observations, state.model);
  const root = element("section", "results-page container-xl");
  root.setAttribute("aria-label", "Harness results");

  const intro = element("header", "results-intro page-header");
  intro.append(
    element("h1", "page-title fs-1", "Results"),
    element("p", "", "Does the harness make the agent more correct, cheaper, faster or less annoying? Read the summary, then the per-task results by type and difficulty, then how each harness behaves across models."),
    element("p", "results-evidence-line", `${plural(admitted.length, "trial")} across ${new Set(admitted.map(({taskId}) => taskId)).size} of ${tests.length} tasks`)
  );

  const filters = element("nav", "results-filters card card-body");
  filters.setAttribute("aria-label", "Results scope");
  const body = element("div", "results-body");

  function update() {
    const groups = reportGroups(observations, state.model);
    if (!groups.some(({id}) => id === state.cohort)) state.cohort = defaultCohort(observations, state.model);
    filters.replaceChildren(
      renderFilterButtons([...TYPE_LABELS], state.type, "Test type", (value) => { state.type = value; update(); }),
      renderFilterButtons([["all", "All difficulties"], ...[1, 2, 3, 4].map((level) => [`${level}`, `Difficulty ${level}`])], state.level, "Difficulty", (value) => { state.level = value; update(); })
    );
    filters.append(
      renderSelect("Model and effort", "results-model-select", modelOptions, state.model, (value) => {
        state.model = value;
        state.cohort = defaultCohort(observations, value);
        update();
      }),
      element("p", "results-scope-note", scopeDescription(observations, state.cohort, state.model))
    );

    const effective = {...state};
    const verdict = campaignVerdict(campaignForModel(observations, campaign, state.model), harnesses);
    const rows = aggregateHarnesses(observations, harnesses, effective);
    const behavior = aggregateBehavior(observations, harnesses, effective)
      .filter((column) => column.modelKey === effective.model);
    const delegation = aggregateDelegation(observations, harnesses, effective, pricing);
    body.replaceChildren(
      renderHarnessRead(harnessRead(rows, behavior, verdict, delegation), rows),
      renderMatrix(observations, tests, harnesses, effective),
      renderDelegation(delegation),
      renderBehavior(behavior)
    );
  }

  update();
  root.append(intro, filters, body);
  return root;
}
