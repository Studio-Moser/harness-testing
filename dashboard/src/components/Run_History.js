function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function providerKey(provider) {
  if (provider === "claude-code") return "claude";
  return provider;
}

function matchKey(manifestDigest, provider, arm, task) {
  return [manifestDigest, providerKey(provider), arm, task].join("\0");
}

function resultSortKey(result) {
  return [
    result.run.finalized_at ?? result.run.finished_at,
    result.run.finished_at,
    result.result_id
  ].join("\0");
}

function observationSortKey(observation) {
  return [
    observation.finishedAt ?? observation.startedAt ?? "",
    observation.runId,
    observation.provider,
    observation.arm,
    observation.task,
    observation.observationId
  ].join("\0");
}

function reviewState(results, fallback) {
  if (results.some((result) => result.review.quarantined)) return "quarantined";
  if (results.some((result) => result.review.partial)) return "partial";
  return results.length ? "reviewed" : fallback;
}

function releaseDecision(results) {
  const decisions = [...new Set(results.map((result) => result.run.release_decision))];
  return decisions.length === 1 ? decisions[0] : decisions.length ? "mixed" : null;
}

function resultLimitations(result) {
  const limitations = [];
  if (result.review.partial) limitations.push("partial-run");
  if (result.review.quarantined) limitations.push("obsolete-methodology");
  if (result.infrastructure.status !== "passed") limitations.push("infrastructure-failure");
  return limitations;
}

function reportObservation(report, job, matchingResults) {
  const finalized = matchingResults.at(-1) ?? null;
  return {
    observationId: `${report.run_id}\0${job.name}`,
    reportId: report.report_id,
    resultId: finalized?.result_id ?? null,
    resultIds: matchingResults.map((result) => result.result_id),
    runId: report.run_id,
    manifestDigest: report.manifest_digest,
    manifestSchema: report.manifest_schema_version,
    profile: report.profile,
    runStatus: report.status,
    runFinishedAt: report.finished_at,
    startedAt: job.started_at,
    finishedAt: job.finished_at,
    provider: job.provider,
    agent: job.agent,
    agentVersion: job.agent_version,
    model: job.model,
    effort: job.effort,
    arm: job.arm,
    role: job.role,
    harnessCommit: job.harness_commit,
    task: job.task,
    taskPack: job.task_pack,
    taskDigest: job.task_digest,
    jobStatus: job.status,
    dimensions: job.dimensions,
    runtimeSeconds: job.runtime_seconds,
    promptTokens: job.efficiency.prompt_tokens,
    cachedTokens: job.efficiency.cached_tokens,
    completionTokens: job.efficiency.completion_tokens,
    observedCost: job.efficiency.api_equivalent_cost_usd,
    efficiency: finalized?.efficiency ?? job.efficiency,
    infrastructureStatus: finalized?.infrastructure.status ?? null,
    skillEvaluation: finalized?.skill_evaluation ?? null,
    sourceKind: report.source.kind,
    sourceLabel: report.source.label,
    reviewState: reviewState(matchingResults, report.evidence.review_state),
    limitations: [...new Set([
      ...report.evidence.limitations,
      ...matchingResults.flatMap(resultLimitations)
    ])],
    comparability: job.comparability,
    seriesKey: job.series_key,
    seriesUnavailableReason: job.series_key_unavailable_reason,
    methodology: finalized?.provenance.methodology_schema ?? report.manifest_schema_version,
    releaseDecision: releaseDecision(matchingResults)
  };
}

function finalizedObservation(result) {
  const limitations = resultLimitations(result);
  const runtime = [result.efficiency.agent_seconds, result.efficiency.verifier_seconds];
  return {
    observationId: `finalized\0${result.result_id}`,
    reportId: null,
    resultId: result.result_id,
    resultIds: [result.result_id],
    runId: result.run.id,
    manifestDigest: result.run.manifest_digest,
    manifestSchema: null,
    profile: null,
    runStatus: "completed",
    runFinishedAt: result.run.finished_at,
    startedAt: result.run.started_at,
    finishedAt: result.run.finished_at,
    provider: providerKey(result.provider.agent),
    agent: result.provider.agent,
    agentVersion: result.provider.agent_version,
    model: result.provider.model,
    effort: result.provider.effort,
    arm: result.arm.id,
    role: result.arm.role,
    harnessCommit: result.run.harness_testing_commit,
    task: result.task.id,
    taskPack: result.task.pack,
    taskDigest: result.task.digest,
    jobStatus: result.infrastructure.status === "passed" ? "completed" : "failed",
    dimensions: result.dimensions,
    runtimeSeconds: runtime.every((value) => value != null)
      ? runtime[0] + runtime[1]
      : null,
    promptTokens: result.efficiency.prompt_tokens,
    cachedTokens: result.efficiency.cached_tokens,
    completionTokens: result.efficiency.completion_tokens,
    observedCost: result.efficiency.cost_usd,
    efficiency: result.efficiency,
    infrastructureStatus: result.infrastructure.status,
    skillEvaluation: result.skill_evaluation,
    sourceKind: "finalized-result",
    sourceLabel: null,
    reviewState: reviewState([result], "reviewed"),
    limitations,
    comparability: result.compatibility.key == null ? "diagnostic-only" : "comparable",
    seriesKey: result.compatibility.key,
    seriesUnavailableReason: result.compatibility.key == null ? "missing-provenance" : null,
    methodology: result.provenance.methodology_schema,
    releaseDecision: result.run.release_decision
  };
}

export function runObservations(runReports, finalizedResults) {
  const finalizedByJob = new Map();
  for (const result of finalizedResults) {
    const key = matchKey(
      result.run.manifest_digest,
      result.provider.agent,
      result.arm.id,
      result.task.id
    );
    const matches = finalizedByJob.get(key) ?? [];
    matches.push(result);
    finalizedByJob.set(key, matches);
  }
  for (const matches of finalizedByJob.values()) {
    matches.sort((left, right) => compareText(resultSortKey(left), resultSortKey(right)));
  }

  const matchedResultIds = new Set();
  const observations = [];
  for (const report of runReports) {
    for (const job of report.jobs) {
      const matches = finalizedByJob.get(
        matchKey(report.manifest_digest, job.provider, job.arm, job.task)
      ) ?? [];
      matches.forEach((result) => matchedResultIds.add(result.result_id));
      observations.push(reportObservation(report, job, matches));
    }
  }
  for (const result of finalizedResults) {
    if (!matchedResultIds.has(result.result_id)) observations.push(finalizedObservation(result));
  }
  return observations.sort((left, right) =>
    compareText(observationSortKey(left), observationSortKey(right))
  );
}

function subtract(later, earlier) {
  return later == null || earlier == null ? null : later - earlier;
}

export function observationTokens(observation) {
  return observation.promptTokens == null || observation.completionTokens == null
    ? null
    : observation.promptTokens + observation.completionTokens;
}

function observationDelta(earlier, later) {
  return {
    correctness: subtract(later.dimensions.correctness, earlier.dimensions.correctness),
    workflow: subtract(later.dimensions.workflow, earlier.dimensions.workflow),
    efficiencyPolicy: subtract(
      later.dimensions.efficiency_policy,
      earlier.dimensions.efficiency_policy
    ),
    runtimeSeconds: subtract(later.runtimeSeconds, earlier.runtimeSeconds),
    tokens: subtract(observationTokens(later), observationTokens(earlier)),
    observedCost: subtract(later.observedCost, earlier.observedCost)
  };
}

export function pairedArmComparisons(observations) {
  const groups = new Map();
  for (const observation of observations) {
    if (observation.arm !== "A0" && observation.arm !== "A2") continue;
    const key = [observation.runId, observation.provider, observation.task].join("\0");
    const group = groups.get(key) ?? {};
    group[observation.arm] = observation;
    groups.set(key, group);
  }
  return [...groups.entries()]
    .filter(([, group]) => group.A0 != null && group.A2 != null)
    .map(([key, group]) => ({
      comparisonId: key,
      runId: group.A0.runId,
      provider: group.A0.provider,
      task: group.A0.task,
      baseline: group.A0,
      candidate: group.A2,
      ...observationDelta(group.A0, group.A2)
    }))
    .sort((left, right) => compareText(left.comparisonId, right.comparisonId));
}

export function seriesDeltas(observations) {
  const groups = new Map();
  for (const observation of observations) {
    if (observation.seriesKey == null) continue;
    const byRun = groups.get(observation.seriesKey) ?? new Map();
    const previous = byRun.get(observation.runId);
    if (
      previous == null ||
      compareText(observationSortKey(previous), observationSortKey(observation)) < 0
    ) {
      byRun.set(observation.runId, observation);
    }
    groups.set(observation.seriesKey, byRun);
  }

  const deltas = [];
  for (const [seriesKey, byRun] of groups) {
    const series = [...byRun.values()].sort((left, right) =>
      compareText(observationSortKey(left), observationSortKey(right))
    );
    for (let index = 1; index < series.length; index += 1) {
      const earlier = series[index - 1];
      const later = series[index];
      deltas.push({
        deltaId: `${seriesKey}\0${earlier.runId}\0${later.runId}`,
        seriesKey,
        earlier,
        later,
        ...observationDelta(earlier, later)
      });
    }
  }
  return deltas.sort((left, right) => compareText(left.deltaId, right.deltaId));
}

export function latestRun(runReports) {
  return runReports.reduce((latest, report) => {
    if (latest == null) return report;
    const latestKey = [
      latest.finished_at ?? latest.updated_at,
      latest.run_id,
      latest.report_id
    ].join("\0");
    const reportKey = [
      report.finished_at ?? report.updated_at,
      report.run_id,
      report.report_id
    ].join("\0");
    return compareText(latestKey, reportKey) < 0 ? report : latest;
  }, null);
}

export function evidenceState(value) {
  return value.evidence?.review_state ?? value.reviewState ?? "unreviewed";
}

export function coverageStates(value) {
  const limitations = value.evidence?.limitations ?? value.limitations ?? [];
  const states = [];
  if (
    limitations.includes("partial-run") ||
    new Set(["pending", "running", "incomplete"]).has(value.status ?? value.runStatus)
  ) {
    states.push("partial");
  }
  if (
    limitations.includes("failed-run") ||
    value.status === "failed" ||
    value.runStatus === "failed" ||
    value.jobStatus === "failed"
  ) {
    states.push("failed");
  }
  return states;
}

export function coverageState(value) {
  const states = coverageStates(value);
  if (states.includes("failed")) return "failed";
  if (states.includes("partial")) return "partial";
  return "complete";
}

export function evidenceLabel(value) {
  const review = evidenceState(value).replaceAll("-", " ").replace(/^./, (letter) => letter.toUpperCase());
  const coverage = coverageState(value);
  return coverage === "complete" ? review : `${review} · ${coverage} execution`;
}

export function completionLabel(report) {
  return `${report.completed_jobs} / ${report.expected_jobs} jobs · ${report.completed_trials} / ${report.expected_trials} trials`;
}

export function formatObservedCost(value) {
  return value == null ? "Unavailable" : `$${value.toFixed(4)} API-equivalent`;
}

export function seriesLabel(observation) {
  if (observation.seriesKey != null) return `Comparable · ${observation.seriesKey.slice(0, 18)}…`;
  const reason = observation.seriesUnavailableReason?.replaceAll("-", " ") ?? "series unavailable";
  return `Diagnostic only · ${reason}`;
}
