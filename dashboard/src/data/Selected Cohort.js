// A display selection is not a new run report or permission to clear evidence flags.
export function selectCohort(reports, selection) {
  if (selection == null) return null;
  const digest = /^sha256:[0-9a-f]{64}$/;
  if (selection.schemaVersion !== 1 || typeof selection.label !== "string" ||
      !selection.label.trim() || !Array.isArray(selection.members) || !selection.members.length ||
      !Array.isArray(selection.taskIds) || !selection.taskIds.length ||
      new Set(selection.taskIds).size !== selection.taskIds.length ||
      !Array.isArray(selection.contenderIds) || selection.contenderIds.length !== 3 ||
      new Set(selection.contenderIds).size !== 3 || !selection.contenderIds.every(id => digest.test(id))) {
    throw new Error("Invalid observational cohort selection");
  }
  const byId = new Map(reports.map(report => [report.report_id, report]));
  const slots = new Set(), trialIds = new Set(), reportIds = new Set(), members = [];
  let kickoff = null;
  const taskConditions = new Map();
  for (const member of selection.members) {
    const report = byId.get(member.reportId);
    if (!digest.test(member.reportId) || reportIds.has(member.reportId) || !report ||
        !Array.isArray(member.trialIds) || !member.trialIds.length) {
      throw new Error("Missing or duplicated observational source report");
    }
    reportIds.add(member.reportId);
    const experiment = report.experiment;
    const currentKickoff = JSON.stringify(experiment.conditions.kickoff);
    if (kickoff !== null && kickoff !== currentKickoff) throw new Error("Mixed kickoff conditions");
    kickoff = currentKickoff;
    const bound = experiment.evaluation_binding?.trial_ids;
    for (const id of member.trialIds) {
      const matches = experiment.trials.filter(trial => trial.trial_id === id);
      if (matches.length !== 1 || trialIds.has(id) || (bound && !bound.includes(id))) {
        throw new Error("Missing, duplicated or unselected observational trial");
      }
      const trial = matches[0];
      const slot = `${trial.contender_id}\0${trial.task_id}`;
      if (!selection.contenderIds.includes(trial.contender_id) ||
          !selection.taskIds.includes(trial.task_id) || trial.attempt !== 1 || slots.has(slot)) {
        throw new Error("Invalid observational task/contender slot");
      }
      const taskDigest = experiment.conditions.task_digests?.[trial.task_id];
      if (!taskDigest || (taskConditions.has(trial.task_id) && taskConditions.get(trial.task_id) !== taskDigest)) {
        throw new Error("Incompatible task inputs across contenders");
      }
      taskConditions.set(trial.task_id, taskDigest);
      slots.add(slot); trialIds.add(id);
      members.push({reportId: member.reportId, trialId: id});
    }
  }
  if (slots.size !== selection.taskIds.length * 3) throw new Error("Incomplete observational cohort");
  return {id: "selected-observational-cohort", label: selection.label, members};
}
