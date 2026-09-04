function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

export function formatCount(value) {
  return value == null ? "Unavailable" : new Intl.NumberFormat("en-US").format(value);
}

export function formatCost(value) {
  return value == null ? "Unavailable" : `$${value.toFixed(4)}`;
}

export function formatScore(value) {
  return value == null ? "Unavailable" : `${Math.round(value * 100)}%`;
}

export function formatSeconds(value) {
  return value == null ? "Unavailable" : `${value.toFixed(1)} s`;
}

export function formatTimestamp(value) {
  return value == null
    ? "Unavailable"
    : new Intl.DateTimeFormat("en-US", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "UTC"
      }).format(new Date(value));
}

export function totalRuntime(result) {
  const {agent_seconds: agent, verifier_seconds: verifier} = result.efficiency;
  return agent == null || verifier == null ? null : agent + verifier;
}

export function totalTokens(result) {
  const {prompt_tokens: prompt, completion_tokens: completion} = result.efficiency;
  return prompt == null || completion == null ? null : prompt + completion;
}

export function deliveryLabel(result) {
  const basic = `${result.provider.agent} · ${result.arm.id}`;
  if (!new Set(["A1", "A3"]).has(result.arm.id)) return basic;
  if (result.provider.agent === "claude-code") {
    return `${basic} · Superpowers hook-capable`;
  }
  if (result.provider.agent === "codex") {
    return `${basic} · Superpowers skills-only`;
  }
  return `${basic} · Superpowers`;
}

export function resultLabel(result) {
  return `${result.task.id} · ${deliveryLabel(result)} · ${formatTimestamp(result.run.finished_at)}`;
}

export function latestResults(results) {
  const latest = new Map();
  for (const result of results) {
    const key = [result.provider.agent, result.arm.id, result.task.id].join("\0");
    const previous = latest.get(key);
    if (
      previous == null ||
      compareText(
        `${previous.run.finished_at}\0${previous.result_id}`,
        `${result.run.finished_at}\0${result.result_id}`
      ) < 0
    ) {
      latest.set(key, result);
    }
  }
  return [...latest.values()].sort((left, right) =>
    compareText(
      [left.provider.agent, left.arm.id, left.task.id].join("\0"),
      [right.provider.agent, right.arm.id, right.task.id].join("\0")
    )
  );
}
