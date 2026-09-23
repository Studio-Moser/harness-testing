# Working in Harness Testing

Start with [README.md](README.md) for the goal, task lanes, repository map and safe commands. Read [Methodology](docs/Methodology.md) before changing how anything is measured and the [Runbook](docs/Runbook.md) before preparing a run.

Check the actual checkout, branch, working tree and local evidence before reporting status. Run `uv run harness-test` from the intended checkout. A prepared manifest or a prior chat's result is not proof that a run executed here.

Compare Nothing, Superpowers and the full Skills-n-Stuff collection. Correctness comes first; then whole-tree cost, elapsed time and tokens; behavior metrics and automated grades are descriptive. The dashboard is read-only. Preserve normal child routing when fixing the kickoff model and effort.

Planning and documentation requests do not authorize model execution: every exact manifest digest needs fresh approval, and grader or reviewer sessions need their own. Model-free work can still incur downloads, image builds and substantial local compute.

Keep private inputs, provider state and raw traces in ignored local paths. Keep retained reports immutable; correct by adding a revision or a recovery run, never by editing evidence.
