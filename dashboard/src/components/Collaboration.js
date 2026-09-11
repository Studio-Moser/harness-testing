const dimensionLabels = {
  directness: "Directness",
  proportionality: "Proportionality",
  progress_usefulness: "Progress usefulness",
  autonomy: "Autonomy",
  candor: "Candor",
  warmth: "Warmth",
  restraint: "Restraint",
  completion_clarity: "Completion clarity"
};

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function mean(values) {
  const known = values.filter(Number.isFinite);
  return known.length ? known.reduce((sum, value) => sum + value, 0) / known.length : null;
}

function format(value, digits = 1) {
  return Number.isFinite(value) ? value.toFixed(digits) : "Unknown";
}

function scenarioLabel(value) {
  return value ? value.replaceAll("_", " ").replace(/^./, letter => letter.toUpperCase()) : "Unknown scenario";
}

function evidenceUrl(reportId, trial, ordinal) {
  const query = new URLSearchParams({comparison: reportId, task: trial.task_id, version: trial.contender_id});
  return `/Run_Detail.html?${query}#${transcriptAnchor(trial, ordinal)}`;
}

export function transcriptAnchor(trial, ordinal) {
  const id = String(trial.trial_id ?? `${trial.contender_id}-${trial.task_id}-${trial.attempt ?? 1}`)
    .replace(/^sha256:/, "")
    .replace(/[^a-zA-Z0-9_-]/g, "-")
    .slice(0, 16);
  return `transcript-${id}-${ordinal}`;
}

export function summarizeCollaboration(contenders, trials) {
  return contenders.map(contender => {
    const selected = trials.filter(trial => trial.contender_id === contender.id);
    const complete = selected.filter(trial => trial.collaboration?.status === "complete" && trial.collaboration.metrics);
    const graded = complete.filter(trial => trial.collaboration.grade?.status === "completed");
    const dimensions = graded.flatMap(trial => trial.collaboration.grade.dimensions ?? []);
    const violations = complete.flatMap(trial => (trial.collaboration.metrics.violations ?? []).map(violation => ({...violation, trial})));
    const scheduled = contender.scheduled ?? selected.length;
    return {
      ...contender,
      scheduled,
      transcriptCount: complete.length,
      gradedCount: graded.length,
      coverageComplete: scheduled > 0 && complete.length === scheduled,
      gradingComplete: scheduled > 0 && graded.length === scheduled,
      wouldWorkAgain: graded.filter(trial => trial.collaboration.grade.would_work_again === true).length,
      meanRubricScore: mean(dimensions.map(row => row.score)),
      meanAssistantTokens: mean(complete.map(trial => trial.collaboration.metrics.assistant_tokens)),
      meanFinalWords: mean(complete.map(trial => trial.collaboration.metrics.final_answer_words)),
      meanCommunicationRatio: mean(complete.map(trial => trial.collaboration.metrics.communication_to_model_output_ratio)),
      interruptionExcess: complete.reduce((sum, trial) => sum + (trial.collaboration.metrics.unnecessary_question_count ?? 0) + (trial.collaboration.metrics.unnecessary_approval_request_count ?? 0), 0),
      slopPhrases: complete.reduce((sum, trial) => sum + (trial.collaboration.metrics.slop_phrase_count ?? 0), 0),
      usefulProgress: complete.reduce((sum, trial) => sum + (trial.collaboration.metrics.useful_progress_update_count ?? 0), 0),
      progressUpdates: complete.reduce((sum, trial) => sum + (trial.collaboration.metrics.progress_update_count ?? 0), 0),
      violations
    };
  });
}

function behaviorSummary(summaries) {
  const complete = summaries.filter(row => row.transcriptCount > 0);
  if (!complete.length) return null;
  const byTokens = [...complete].sort((left, right) => left.meanAssistantTokens - right.meanAssistantTokens);
  const section = el("div", null, "collaboration-behavior-summary");
  section.append(el("p", `${byTokens[0].label} was least talkative at ${format(byTokens[0].meanAssistantTokens, 0)} visible assistant tokens per trial; ${byTokens.at(-1).label} was most talkative at ${format(byTokens.at(-1).meanAssistantTokens, 0)}.`));
  const list = el("ul");
  for (const row of complete) {
    const useful = row.progressUpdates ? `${row.usefulProgress} of ${row.progressUpdates} progress updates contained recognized new information` : "no progress updates were sent";
    const overhead = row.meanCommunicationRatio == null ? "communication overhead is unknown" : `visible communication was ${format(row.meanCommunicationRatio * 100)}% of billed model output tokens`;
    list.append(el("li", `${row.label}: ${useful}; ${overhead}.`));
  }
  section.append(list);
  return section;
}

function humanPreference(report, contenders) {
  const calibration = report.experiment?.collaboration_calibration;
  const labels = calibration?.labels ?? [];
  if (!labels.length) return null;
  const counts = new Map(contenders.map(contender => [contender.id, 0]));
  for (const label of labels) {
    if (counts.has(label.preferred_contender_id)) counts.set(label.preferred_contender_id, counts.get(label.preferred_contender_id) + 1);
  }
  const ordered = [...counts].sort((left, right) => right[1] - left[1]);
  const leader = ordered[0]?.[1] > (ordered[1]?.[1] ?? 0) ? contenders.find(row => row.id === ordered[0][0]) : null;
  const agreement = labels.map(label => label.grader_agreement).filter(value => value != null);
  return {calibrated: calibration.calibrated, labels, leader, wins: ordered[0]?.[1] ?? 0, agreement: agreement.length ? agreement.filter(Boolean).length / agreement.length : null};
}

export function collaborationVerdict(report, contenders, trials) {
  const summaries = summarizeCollaboration(contenders, trials);
  if (summaries.length < 2 || summaries.every(row => row.transcriptCount === 0)) {
    return {heading: "Collaboration quality has not been measured", summary: "This report has no complete user-visible transcripts to compare.", source: "missing"};
  }
  const human = humanPreference(report, contenders);
  if (human?.leader) {
    const status = human.calibrated ? "was preferred" : "leads the early preference check";
    const agreement = human.agreement == null ? "Automated-grader agreement is unknown." : `The automated grader agreed on ${Math.round(human.agreement * 100)}% of labeled pairs.`;
    return {
      heading: `${human.leader.label} ${status} in Tim’s blinded comparison`,
      summary: `${human.leader.label} won ${human.wins} of ${human.labels.length} blinded choices. ${human.calibrated ? "The personal preference calibration threshold has been met." : "Treat this as early evidence until at least 15 choices are labeled."} ${agreement}`,
      source: human.calibrated ? "calibrated-human" : "early-human"
    };
  }
  if (human) {
    return {heading: "Tim’s blinded preference is tied", summary: `${human.labels.length} choices are labeled, with no unique preference leader.`, source: "human-tie"};
  }
  if (!summaries.every(row => row.gradingComplete)) {
    const coverage = summaries.map(row => `${row.label}: ${row.gradedCount} of ${row.scheduled} graded`).join("; ");
    return {heading: "Collaboration grading is incomplete", summary: `${coverage}. No collaboration winner is claimed until every scheduled transcript has a blind grade.`, source: "incomplete"};
  }
  const ordered = [...summaries].sort((left, right) => right.wouldWorkAgain - left.wouldWorkAgain || right.meanRubricScore - left.meanRubricScore);
  const leader = ordered[0];
  const runnerUp = ordered[1];
  if (leader.wouldWorkAgain === runnerUp.wouldWorkAgain && leader.meanRubricScore === runnerUp.meanRubricScore) {
    return {heading: "No clear collaboration winner", summary: "Blind grades are complete, but the top harnesses tie on willingness to work together again and mean rubric score.", source: "automated-tie"};
  }
  return {
    heading: `${leader.label} is the automated collaboration leader`,
    summary: `A blind grader would work with it again in ${leader.wouldWorkAgain} of ${leader.gradedCount} trials; its mean collaboration score is ${format(leader.meanRubricScore)} of 5. Personal calibration has not been recorded yet.`,
    source: "automated"
  };
}

function personalityEffect(summaries) {
  const byFamily = new Map(summaries.map(row => [row.family, row]));
  if (!["nothing", "studio-personality", "studio-moser"].every(family => byFamily.has(family))) return null;
  const row = family => byFamily.get(family);
  return `Personality-only used ${format(row("studio-personality").meanAssistantTokens, 0)} visible assistant tokens per trial, compared with ${format(row("nothing").meanAssistantTokens, 0)} for no instructions and ${format(row("studio-moser").meanAssistantTokens, 0)} for Studio Moser. This isolates communication guidance from the full development harness.`;
}

function summaryTable(summaries) {
  const region = el("div", null, "comparison-table-region");
  region.setAttribute("role", "region");
  region.setAttribute("aria-label", "Collaboration quality comparison");
  region.setAttribute("tabindex", "0");
  const table = el("table", null, "comparison-table collaboration-table");
  const head = el("thead");
  const heading = el("tr");
  for (const title of ["Harness", "Transcript coverage", "Would work again", "Blind score", "Visible assistant tokens", "Unneeded interruptions", "Rule violations"]) {
    const cell = el("th", title);
    cell.scope = "col";
    heading.append(cell);
  }
  head.append(heading);
  const body = el("tbody");
  for (const row of summaries) {
    const item = el("tr");
    const name = el("th", row.label);
    name.scope = "row";
    item.append(
      name,
      el("td", `${row.transcriptCount} / ${row.scheduled}`),
      el("td", row.gradedCount ? `${row.wouldWorkAgain} / ${row.gradedCount}` : "Unknown", row.gradedCount ? null : "comparison-missing"),
      el("td", row.meanRubricScore == null ? "Unknown" : `${format(row.meanRubricScore)} / 5`, row.meanRubricScore == null ? "comparison-missing" : null),
      el("td", format(row.meanAssistantTokens, 0)),
      el("td", String(row.interruptionExcess)),
      el("td", String(row.violations.length))
    );
    body.append(item);
  }
  table.append(head, body);
  region.append(table);
  return region;
}

function behaviorEvidence(report, summaries) {
  const content = el("div");
  const violations = summaries.flatMap(summary => summary.violations.map(row => ({...row, label: summary.label})))
    .sort((left, right) => left.trial.task_id.localeCompare(right.trial.task_id) || left.ordinal - right.ordinal);
  if (!violations.length) content.append(el("p", "No deterministic communication-contract violations were recorded."));
  else {
    const list = el("ul");
    for (const violation of violations.slice(0, 12)) {
      const item = el("li");
      const anchor = el("a", violation.kind.replaceAll("_", " "));
      anchor.href = evidenceUrl(report.report_id, violation.trial, violation.ordinal);
      item.append(anchor, el("span", ` · ${violation.label} · ${scenarioLabel(violation.trial.collaboration.contract.scenario)} · ${violation.detail}`));
      list.append(item);
    }
    content.append(list);
  }
  const annoyance = report.experiment?.collaboration_calibration?.labels?.filter(row => row.annoyance_reason) ?? [];
  if (annoyance.length) {
    content.append(el("h3", "Why Tim rejected an answer"));
    const list = el("ul");
    for (const row of annoyance) list.append(el("li", `${scenarioLabel(row.scenario)}: ${row.annoyance_reason}`));
    content.append(list);
  }
  return content;
}

function scenarioEvidence(contenders, trials) {
  const labels = new Map(contenders.map(row => [row.id, row.label]));
  const selected = trials.filter(trial => trial.collaboration?.status === "complete" && trial.collaboration.metrics);
  const region = el("div", null, "comparison-table-region");
  region.setAttribute("role", "region");
  region.setAttribute("aria-label", "Results by conversation scenario");
  region.setAttribute("tabindex", "0");
  const table = el("table", null, "comparison-table scenario-table");
  const head = el("thead");
  const heading = el("tr");
  for (const title of ["Scenario", "Harness", "Blind score", "Would work again", "Visible tokens", "Unneeded interruptions"]) {
    const cell = el("th", title);
    cell.scope = "col";
    heading.append(cell);
  }
  head.append(heading);
  const body = el("tbody");
  for (const trial of selected.sort((left, right) => left.collaboration.contract.scenario.localeCompare(right.collaboration.contract.scenario) || (labels.get(left.contender_id) ?? "").localeCompare(labels.get(right.contender_id) ?? ""))) {
    const grade = trial.collaboration.grade?.status === "completed" ? trial.collaboration.grade : null;
    const score = grade ? mean(grade.dimensions.map(row => row.score)) : null;
    const metrics = trial.collaboration.metrics;
    const row = el("tr");
    const scenario = el("th", scenarioLabel(trial.collaboration.contract.scenario));
    scenario.scope = "row";
    row.append(
      scenario,
      el("td", labels.get(trial.contender_id) ?? "Harness"),
      el("td", score == null ? "Unknown" : `${format(score)} / 5`, score == null ? "comparison-missing" : null),
      el("td", grade ? (grade.would_work_again ? "Yes" : "No") : "Unknown", grade ? null : "comparison-missing"),
      el("td", String(metrics.assistant_tokens)),
      el("td", String((metrics.unnecessary_question_count ?? 0) + (metrics.unnecessary_approval_request_count ?? 0)))
    );
    body.append(row);
  }
  table.append(head, body);
  region.append(table);
  return region;
}

export function renderCollaboration(report, contenders, trials) {
  const section = el("section", null, "collaboration-quality");
  const verdict = collaborationVerdict(report, contenders, trials);
  const summaries = summarizeCollaboration(contenders, trials);
  section.append(el("h2", verdict.heading), el("p", verdict.summary));
  if (verdict.source === "missing") {
    section.append(el("p", "Engineering correctness, cost, and time remain available elsewhere in this report.", "comparison-meta"));
    return section;
  }
  section.append(summaryTable(summaries));
  section.append(behaviorSummary(summaries));
  section.append(el("p", "Blind score averages directness, proportionality, useful progress, autonomy, candor, warmth, restraint, and completion clarity. Visible assistant tokens use the fixed lexical counter, separate from billed model tokens.", "comparison-meta"));
  const effect = personalityEffect(summaries);
  if (effect) section.append(el("p", effect, "personality-effect"));
  const scenarios = el("details");
  scenarios.append(el("summary", "Compare conversation scenarios"), scenarioEvidence(contenders, trials));
  section.append(scenarios);
  const evidence = behaviorEvidence(report, summaries);
  const details = el("details");
  details.append(el("summary", "See the behaviors behind this result"), evidence);
  section.append(details);
  return section;
}

function gradeEvidence(grade) {
  const section = el("section", null, "collaboration-grade");
  section.append(el("h4", "Blinded collaboration grade"));
  if (!grade) {
    section.append(el("p", "No blind grade has been recorded."));
    return section;
  }
  if (grade.status !== "completed") {
    section.append(el("p", `Grade status: ${grade.status}.`));
    return section;
  }
  section.append(el("p", `Would work together again: ${grade.would_work_again ? "yes" : "no"}.`));
  const list = el("dl", null, "collaboration-dimensions");
  for (const row of grade.dimensions ?? []) {
    list.append(el("dt", `${dimensionLabels[row.name] ?? scenarioLabel(row.name)} · ${row.score} / 5`), el("dd", row.rationale));
  }
  section.append(list);
  return section;
}

export function renderCollaborationEvidence(trial) {
  const collaboration = trial.collaboration;
  const section = el("section", null, "trial-collaboration");
  section.append(el("h4", "User-visible collaboration"));
  if (!collaboration || collaboration.status !== "complete") {
    const reasons = collaboration?.reasons?.length ? collaboration.reasons.join(", ").replaceAll("_", " ") : "missing transcript";
    section.append(el("p", `Collaboration evidence unavailable: ${reasons}.`));
    return section;
  }
  const metrics = collaboration.metrics;
  section.append(
    el("p", `${scenarioLabel(collaboration.contract.scenario)} · ${metrics.assistant_tokens} visible assistant tokens · ${metrics.final_answer_words} final-answer words · ${metrics.unnecessary_question_count + metrics.unnecessary_approval_request_count} unneeded interruptions · ${metrics.violations.length} rule violations.`),
    gradeEvidence(collaboration.grade)
  );
  const transcript = el("ol", null, "visible-transcript");
  for (const row of collaboration.transcript) {
    const item = el("li");
    item.setAttribute("id", transcriptAnchor(trial, row.ordinal));
    item.append(
      el("span", `${row.kind === "user" ? "User" : row.kind === "final" ? "Final" : "Progress"} · ${format(row.elapsed_seconds)}s`, "transcript-meta"),
      el("p", row.content)
    );
    transcript.append(item);
  }
  const details = el("details");
  details.append(el("summary", "Read the visible transcript"), transcript);
  section.append(details);
  return section;
}
