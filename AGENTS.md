# Working in Harness Testing

Start with [README.md](README.md) for the goals, task lanes, repository map and safe commands. Read [Agent Experiment Guide](docs/Agent%20Experiment%20Guide.md) before preparing a comparison, and [Capability Pack — Next Queued Experiment](docs/Capability_Pack.md#next-queued-experiment) before choosing the next task.

Check the actual checkout, branch, working tree and local evidence before reporting status. Run `uv run harness-test` from the intended checkout; its installed module determines the repository root. A prepared manifest or a prior chat's result is not proof that a run executed here.

Compare Nothing, Superpowers and the **full Skills-n-Stuff collection**. Correctness comes first; then compare whole-tree cost, elapsed time and tokens. The dashboard is read-only and should explain outcomes and uncertainty. Preserve normal child routing when fixing the kickoff model/effort.

Use the versioned `run plan --request` workflow for these comparisons. Legacy A0–A3 commands are separate diagnostics. Planning and documentation requests do not authorize model execution: [Runbook](docs/Runbook.md#plan-before-any-model-backed-run) requires fresh approval of each exact manifest digest. Model-free work can still incur downloads, image builds and substantial local compute.

Keep private inputs, provider state and raw traces in ignored local paths. Preserve immutable reports, explicit baseline/predecessor references and original evidence when correcting a result. Do not publish local-only evidence. The detailed authority, privacy and evidence rules live in the linked guide and runbook; do not duplicate them into new startup documents.
