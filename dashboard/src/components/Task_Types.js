const TASK_TYPE_IDS = {
  "react-accent-polish": "polish",
  "react-active-badge-count": "small",
  "react-bulk-dashboard-updates": "grouped",
  "react-grouped-ui-updates": "grouped",
  "react-saved-view-feature": "feature",
  "rust-quoted-value-parser": "small",
  "rust-workspace-warning-summary": "feature",
  "static-accessible-disclosure": "small",
  "static-grouped-page-updates": "grouped",
  "static-pricing-copy-polish": "polish",
  "quill-shared-toolbar-focus": "feature"
};

export const TASK_TYPES = [
  {id: "polish", label: "Polish", description: "Styling, spacing, and copy changes."},
  {id: "small", label: "Small changes", description: "Bug fixes and focused behaviors."},
  {id: "grouped", label: "Grouped updates", description: "Independent updates batched before one final gate."},
  {id: "feature", label: "Features", description: "New behavior across files or with design choices."}
];

const UNCLASSIFIED = {
  id: "unclassified",
  label: "Unclassified",
  description: "This task is not classified in the dashboard."
};
const TOKEN_FIELDS = ["input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens"];

export function taskType(taskId) {
  return Object.hasOwn(TASK_TYPE_IDS, taskId) ? TASK_TYPE_IDS[taskId] : UNCLASSIFIED.id;
}

function finiteNonnegative(value) {
  return Number.isFinite(value) && value >= 0;
}

function scheduledTasks(report) {
  const values = report?.experiment?.conditions?.task_ids;
  if (!Array.isArray(values)) return [];
  return [...new Set(values.filter((value) => typeof value === "string"))];
}

function attemptsFor(report) {
  const value = report?.experiment?.conditions?.attempts;
  return Number.isInteger(value) && value >= 0 ? value : 0;
}

function selectedContenders(report) {
  const experiment = report?.experiment ?? {};
  const rows = Array.isArray(experiment.comparison?.contenders)
    ? experiment.comparison.contenders
    : experiment.contenders;
  if (!Array.isArray(rows)) return [];
  const ids = new Set();
  return rows.filter((row) => {
    if (typeof row?.id !== "string" || ids.has(row.id)) return false;
    ids.add(row.id);
    return true;
  });
}

function trialSlots(trials, taskIds, attempts, contenderId) {
  const allowedTasks = new Set(taskIds);
  const bySlot = new Map();
  for (const trial of trials) {
    if (
      trial?.contender_id !== contenderId
      || !allowedTasks.has(trial.task_id)
      || !Number.isInteger(trial.attempt)
      || trial.attempt < 1
      || trial.attempt > attempts
    ) continue;
    const key = `${trial.task_id}\0${trial.attempt}`;
    const values = bySlot.get(key) ?? [];
    values.push(trial);
    bySlot.set(key, values);
  }
  return bySlot;
}

function singleTrials(bySlot) {
  return [...bySlot.values()].flatMap((values) => values.length === 1 ? values : []);
}

function total(values) {
  const value = values.reduce((sum, item) => sum + item, 0);
  return Number.isFinite(value) ? value : null;
}

function tokensFor(trials) {
  const values = [];
  for (const trial of trials) {
    if (!trial.usage_complete || !Array.isArray(trial.model_usage) || !trial.model_usage.length) return null;
    for (const usage of trial.model_usage) {
      for (const field of TOKEN_FIELDS) {
        if (!finiteNonnegative(usage?.[field])) return null;
        values.push(usage[field]);
      }
    }
  }
  return total(values);
}

function pricingDigestFor(trials) {
  const digests = trials.map((trial) => trial.pricing_digest);
  if (!digests.length || digests.some((digest) => typeof digest !== "string" || !digest)) return null;
  return digests.every((digest) => digest === digests[0]) ? digests[0] : null;
}

function rowFor(contender, taskIds, attempts, trials) {
  const bySlot = trialSlots(trials, taskIds, attempts, contender.id);
  const exactTrials = singleTrials(bySlot);
  const scheduled = taskIds.length * attempts;
  const complete = bySlot.size === scheduled && exactTrials.length === scheduled
    && exactTrials.every(trial => ["completed", "agent_failed", "timeout"].includes(trial.status));
  const metrics = complete && scheduled ? exactTrials : [];
  const costs = metrics.map((trial) => trial.usage_complete && finiteNonnegative(trial.cost_usd) ? trial.cost_usd : null);
  const durations = metrics.map((trial) => finiteNonnegative(trial.duration_seconds) ? trial.duration_seconds : null);
  const pricing_digest = pricingDigestFor(metrics);
  const costKnown = Boolean(metrics.length) && pricing_digest != null && costs.every((value) => value != null);
  const durationKnown = Boolean(metrics.length) && durations.every((value) => value != null);
  return {
    id: contender.id,
    label: contender.label ?? contender.id,
    scheduled,
    selected: bySlot.size,
    passed: exactTrials.filter((trial) => trial.status === "completed" && trial.correctness === true).length,
    complete,
    total_cost_usd: costKnown ? total(costs) : null,
    pricing_digest,
    mean_duration_seconds: durationKnown ? total(durations) / scheduled : null,
    total_tokens: metrics.length ? tokensFor(metrics) : null,
    trials: exactTrials
  };
}

export function summarizeTaskTypes(report, trials = []) {
  const taskIds = scheduledTasks(report);
  const attempts = attemptsFor(report);
  const trialList = Array.isArray(trials) ? trials : [];
  const groups = TASK_TYPES.map((type) => ({...type, task_ids: []}));
  const unclassified = {...UNCLASSIFIED, task_ids: []};
  const byType = new Map(groups.map((group) => [group.id, group]));

  for (const taskId of taskIds) {
    const type = taskType(taskId);
    const group = byType.get(type) ?? unclassified;
    group.task_ids.push(taskId);
  }

  const contenders = selectedContenders(report);
  const withRows = (group) => {
    const rows = contenders.map((contender) => rowFor(contender, group.task_ids, attempts, trialList));
    return {...group, rows};
  };
  const known = groups.map(withRows);
  return unclassified.task_ids.length ? [...known, withRows(unclassified)] : known;
}
