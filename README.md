# Harness Testing

Harness Testing is Studio Moser's deterministic benchmark for measuring how coding-agent harness changes affect correctness, workflow discipline, testing churn, time, tokens, and cost.

The benchmark runs only against frozen test projects. It never mounts a live product repository, personal Claude or Codex configuration, Shelby memory, or private project state. Model-backed runs are manual and require approval of an exact manifest digest and estimated maximum spend.

The initial release targets Claude Code and Codex across React, TypeScript, static HTML/CSS/JavaScript, and Rust tasks. Shelby is represented only by a future adapter contract.

Implementation is in progress on `feature/initial-harness-testing`.
