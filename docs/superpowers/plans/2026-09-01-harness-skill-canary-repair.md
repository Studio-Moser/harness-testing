# Harness Skill Canary Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Studio Harness discoverable for explicit typed pre-dispatch work, encode blocked `HarnessResult` values deterministically, and avoid loading unrelated references, then prove the repair with the two failed A2 provider cells only.

**Architecture:** The production Harness plugin remains the source of execution semantics. Its `execute` metadata advertises explicit routing and typed preflight blockers, `harness-contract.md` owns the provider-neutral terminal encoding, and `SKILL.md` routes supporting references only when their execution path is entered. Harness Testing continues to use the unchanged protected task and scorer while pinning one immutable Harness `0.8.2` commit.

**Tech Stack:** Markdown agent skills, Claude plugin manifests, Bash/Bats, Git worktrees, Python 3.12, pytest, Ruff, Harbor 0.22.0, Claude Code 2.1.236, Codex 0.150.1.

**Spec:** [`docs/superpowers/specs/2026-09-01-harness-skill-canary-repair-design.md`](../specs/2026-09-01-harness-skill-canary-repair-design.md)

## Global constraints

- Do not edit the shared Skills-n-Stuff checkout at `/Users/timmoser/Projects/Studio Moser Internal/Skills-n-Stuff`; it owns unrelated branch `fix/narrow-harness-delegation` and an untracked `.DS_Store`.
- Do not change the `missing-rubric` task instruction, protected expectation, scorer, public result schema, dashboard, task images, or provider adapters.
- Treat run `run-38eee85f60f36d221fdb` as the model-backed RED: Claude A2 did not invoke `harness:execute`; Codex A2 read all six references and returned the wrong terminal encoding.
- Use focused tests while editing. Run each repository's complete relevant checkpoint once after all edits settle.
- Start no provider model until the new two-session manifest has an exact content-addressed approval.
- Do not rerun A0. Its delivery isolation and baseline behavior are already proven.
- Never commit raw trajectories, provider homes, credentials, materialized arms, or ignored run artifacts.

---

### Task 1: Create the isolated production worktree and encode the RED expectations

**Files:**

- Create worktree: `/Users/timmoser/Projects/Studio Moser Internal/Harness Testing/.worktrees/skills-n-stuff-harness-execute-canary-repair`
- Modify: `plugins/harness/tests/skill-contracts.bats`
- Modify: `plugins/harness/tests/reference-contracts.bats`

**Interfaces:**

- Consumes: current `origin/main` at `456e8b7985ab24f67a5f7539fb9163dd020c6fd2` and the approved design.
- Produces: branch `bugfix/harness-execute-canary-repair` with static expectations for discovery, progressive disclosure, and blocked-result encoding.

- [ ] **Step 1: Load the worktree instructions and create the isolated branch from the exact remote main.**

  ```bash
  git fetch origin
  git worktree add \
    /Users/timmoser/Projects/Studio\ Moser\ Internal/Harness\ Testing/.worktrees/skills-n-stuff-harness-execute-canary-repair \
    -b bugfix/harness-execute-canary-repair \
    456e8b7985ab24f67a5f7539fb9163dd020c6fd2
  git rev-parse HEAD
  ```

  Expected: the new worktree prints `456e8b7985ab24f67a5f7539fb9163dd020c6fd2`; the shared checkout remains untouched.

- [ ] **Step 2: Establish the local baseline with only the affected Bats files.**

  ```bash
  cd plugins/harness
  bats tests/skill-contracts.bats tests/reference-contracts.bats tests/version-consistency.bats
  ```

  Expected: the current `0.8.1` targeted tests pass.

- [ ] **Step 3: Add focused failing assertions.**

  In `skill-contracts.bats`, add one test that requires the normalized `execute` frontmatter description to cover all of these explicit triggers:

  ```text
  bounded Harness execution
  semantic routing
  typed pre-dispatch blocker
  missing rubric
  missing executor
  ```

  The same test must split the opening reference section from `## Validate the request`, reject the current unconditional six-reference sentence, and require these conditional predicates:

  ```text
  harness-contract.md -> request validation or terminal-result construction
  routing.md -> successful preflight followed by route selection
  handoff.md -> delegated dispatch
  verification.md -> artifact or review-claim acceptance
  context.md -> context-mode selection
  shelby-integration.md -> callable Shelby or enabled memory request
  ```

  In `reference-contracts.bats`, require `harness-contract.md` to state the generic pre-dispatch encoding from the approved spec: typed reason propagation, no-dispatch null/zero provenance, `path:<absolute-path>`, decisive-result-first evidence, and `<reason>:` blocker prefix.

- [ ] **Step 4: Run only those two Bats files and confirm the assertions fail for the intended missing clauses.**

  ```bash
  cd plugins/harness
  bats tests/skill-contracts.bats tests/reference-contracts.bats
  ```

  Expected: failures name discovery metadata, unconditional reference loading, and the absent terminal encoding; no unrelated test fails.

**Task done when:** the production defect has a small executable RED boundary without modifying the benchmark or overfitting to `missing-rubric` output values.

---

### Task 2: Repair the execute skill and release Harness 0.8.2

**Files:**

- Modify: `plugins/harness/skills/execute/SKILL.md`
- Modify: `plugins/harness/references/harness-contract.md`
- Modify: `plugins/harness/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Modify: tests from Task 1 only if an assertion is proven inaccurate

**Interfaces:**

- `execute` remains limited to explicit Harness requests and does not claim ordinary repository development.
- `harness-contract.md` remains provider-neutral and owns the stable blocked-result recipe.
- Plugin version becomes `0.8.2`; marketplace metadata version becomes `0.19.3`.

- [ ] **Step 1: Expand only the frontmatter discovery boundary.**

  Replace the current description with a concise folded value that says to use `execute` for explicit bounded Harness execution, semantic routing, or a typed pre-dispatch blocker such as a missing rubric or executor, whether execution is native or uses the internal cross-provider adapter.

- [ ] **Step 2: Replace the unconditional reference list with progressive disclosure.**

  Keep links to all six existing references so packaging tests can prove they remain reachable, but attach each link to its approved predicate. State that only the references whose predicates match the active path are read. The initial preflight path reads `harness-contract.md`; it must not read routing, handoff, verification, context, or Shelby material unless that path is entered.

- [ ] **Step 3: Add the generic blocked pre-dispatch recipe to the shared contract.**

  Immediately after HarnessResult routing provenance, document:

  ```text
  route.fallback_reason = typed pre-dispatch reason
  unresolved route fields = null; route.attempted = []; telemetry.attempts = 0
  evidence.fixed_target = path:<absolute-path> for a checked absolute path
  evidence.checks entry starts with the exact decisive result
  blocker starts with <reason>: followed by recovery
  ```

  Clarify that commands/procedures may follow the decisive result and that no-dispatch terminal values must not imply a selected provider or executor.

- [ ] **Step 4: Bump both plugin manifests.**

  Set `plugins/harness/.claude-plugin/plugin.json` and the Harness marketplace entry to `0.8.2`. Increment marketplace `metadata.version` from `0.19.2` to `0.19.3`; leave every unrelated plugin version unchanged.

- [ ] **Step 5: Run the focused GREEN checks.**

  ```bash
  cd plugins/harness
  bats tests/skill-contracts.bats tests/reference-contracts.bats tests/version-consistency.bats
  ```

  Expected: all selected Bats tests pass.

- [ ] **Step 6: Perform the one Skills-n-Stuff checkpoint.**

  ```bash
  cd plugins/harness
  ./tests/run-tests.sh
  git diff --check
  git status --short
  ```

  Expected: the complete Harness plugin Bats suite passes once, diff checking is clean, and only the six intended production/test/manifest files are modified.

- [ ] **Step 7: Commit and publish the immutable candidate branch.**

  ```bash
  git add .claude-plugin/marketplace.json plugins/harness/.claude-plugin/plugin.json \
    plugins/harness/skills/execute/SKILL.md \
    plugins/harness/references/harness-contract.md \
    plugins/harness/tests/skill-contracts.bats \
    plugins/harness/tests/reference-contracts.bats
  git commit -m "fix: encode Harness preflight blockers"
  git push -u origin bugfix/harness-execute-canary-repair
  git rev-parse HEAD
  ```

  Expected: the printed 40-character SHA is fetchable from `https://github.com/Studio-Moser/skills-n-stuff.git` and becomes the sole candidate pin used below.

**Task done when:** Harness `0.8.2` is a focused, tested, remote-fetchable commit and the unrelated shared checkout has exactly its original state.

---

### Task 3: Pin the immutable production repair in Harness Testing

**Files:**

- Modify: `Versions.toml`
- Modify: `tests/unit/test_Materialize.py`
- Modify: `tests/unit/test_Runs.py`
- Modify: `tests/Fixtures/Public_Results/Valid.json`
- Modify only if a focused failure proves another current-pin fixture exists

**Interfaces:**

- Consumes: the exact remote-fetchable Harness `0.8.2` commit from Task 2.
- Produces: all current-candidate fixtures and generated-arm expectations bound to that one version/SHA pair.

- [ ] **Step 1: Update current-pin test expectations before the ledger.**

  Replace only fixtures that model the current Studio Harness source from `0.8.1` and `ff8852e737a43a7e23f2cad423905f9361fde8ae` to `0.8.2` and the Task 2 SHA. Do not change historical prose or unrelated dependency strings such as Node's `>=0.8.19`.

- [ ] **Step 2: Run the pin-focused tests and confirm they fail against the old ledger.**

  ```bash
  uv run pytest -q tests/unit/test_Materialize.py tests/unit/test_Runs.py \
    -k 'harness or source or version or commit or bundle or plugin'
  ```

  Expected: failures show the test fixtures expect `0.8.2` while `Versions.toml` still selects `0.8.1`.

- [ ] **Step 3: Update the source ledger and public provenance fixture.**

  Set Studio Harness in `Versions.toml` to version `0.8.2` and the exact Task 2 SHA. Update the Studio Harness commit URL/digest in `tests/Fixtures/Public_Results/Valid.json`. Search the repository outside `docs/superpowers/**` and confirm no stale current-pin literal remains.

  ```bash
  rg -n '0\.8\.1|ff8852e737a43a7e23f2cad423905f9361fde8ae' \
    Versions.toml tests
  ```

  Expected: no Studio Harness current-pin occurrence remains; unrelated semver substrings are ignored.

- [ ] **Step 4: Run focused pin, materialization, and static checks.**

  ```bash
  uv run ruff check tests/unit/test_Materialize.py tests/unit/test_Runs.py
  uv run pytest -q tests/unit/test_Materialize.py tests/unit/test_Runs.py
  uv run harness-test validate --static-only
  ```

  Expected: all commands pass without building images or starting a model.

- [ ] **Step 5: Run the one Harness Testing checkpoint.**

  ```bash
  uv run ruff check src tests
  uv run pytest -q tests/unit
  uv run harness-test validate --static-only
  git diff --check
  ```

  Expected: the unit suite and static input validator pass once. Dashboard, task-pack, and image-build gates stay skipped because their inputs did not change.

- [ ] **Step 6: Commit the immutable pin.**

  ```bash
  git add Versions.toml tests/unit/test_Materialize.py tests/unit/test_Runs.py \
    tests/Fixtures/Public_Results/Valid.json
  git commit -m "test: pin Harness preflight repair"
  git status --short
  git rev-parse HEAD
  ```

  Expected: tracked status is clean and the printed implementation SHA freezes the canary input.

**Task done when:** deterministic Harness Testing checks accept the exact `0.8.2` candidate and no current fixture still identifies `0.8.1`.

---

### Task 4: Materialize only the repaired A2 cells and compile the canary

**Files:**

- Generate locally/ignored: `arms/materialized/**`
- Generate locally/ignored: `runs/generated/**`
- Generate locally/ignored: Harbor YAML under the content-addressed run directory

**Interfaces:**

- Produces exactly two sequential subscription sessions for task `missing-rubric`: Claude A2 and Codex A2, each high effort and each bound to the Task 2 candidate SHA.

- [ ] **Step 1: Materialize the two candidate arms without a model session.**

  ```bash
  HARNESS_CANDIDATE_SHA="$(git -C \
    /Users/timmoser/Projects/Studio\ Moser\ Internal/Harness\ Testing/.worktrees/skills-n-stuff-harness-execute-canary-repair \
    rev-parse HEAD)"
  uv run harness-test arm materialize \
    --provider claude --arm A2 \
    --harness-source https://github.com/Studio-Moser/skills-n-stuff.git \
    --harness-commit "$HARNESS_CANDIDATE_SHA"
  uv run harness-test arm materialize \
    --provider codex --arm A2 \
    --harness-source https://github.com/Studio-Moser/skills-n-stuff.git \
    --harness-commit "$HARNESS_CANDIDATE_SHA"
  ```

  Inspect both `Provenance.json` files. Each must contain only Studio Harness as the benchmark plugin; Claude must expose `claude-plugin-dir`, Codex must expose `codex-plugin`, and every declared path must exist in the immutable bundle.

- [ ] **Step 2: Compile the exact two-session dry-run manifest.**

  ```bash
  HARNESS_PLAN_OUTPUT="$(uv run harness-test run plan \
    --profile smoke \
    --billing-mode subscription \
    --cell "claude:A2:candidate:$HARNESS_CANDIDATE_SHA" \
    --cell "codex:A2:candidate:$HARNESS_CANDIDATE_SHA" \
    --task missing-rubric \
    --max-sessions 2 \
    --max-budget-usd 0 \
    --attempts 1 \
    --concurrency 1 \
    --agent-timeout-seconds 1800)"
  printf '%s\n' "$HARNESS_PLAN_OUTPUT"
  HARNESS_MANIFEST_PATH="$(printf '%s\n' "$HARNESS_PLAN_OUTPUT" | sed -n 's/^Manifest path: //p')"
  HARNESS_APPROVAL_DIGEST="$(printf '%s\n' "$HARNESS_PLAN_OUTPUT" | sed -n 's/^Run manifest: //p')"
  ```

  Expected: the plan reports two sequential sessions, zero incremental subscription cost, Claude Sonnet 4.6 high and Codex GPT-5.6 Terra high, exact bundle/adapter/task/image digests, one manifest path, and no model session started.

- [ ] **Step 3: Stop at the mandatory approval boundary.**

  Report the manifest path and digest, session order, model/effort, timeout, candidate SHA, and API-equivalent estimate. Obtain the user's exact content-addressed approval for the value printed on the `Run manifest:` line before Task 5. General permission to continue does not replace this authorization.

**Task done when:** the smallest valid model-backed canary is compiled and immutable, with no provider session started before exact approval.

---

### Task 5: Execute and evaluate the approved two-session canary

**Files:**

- Generate locally/ignored: `jobs/raw/**`
- Generate locally/ignored: provider receipts and trajectories
- Do not modify tracked files unless the canary exposes a new proven production defect

**Interfaces:**

- Consumes: the exact approved manifest/digest from Task 4 and subscription credentials only.
- Produces: provider delivery receipts, protected score output, and bounded efficiency comparison against preserved Harness `0.8.1` A2 cells.

- [ ] **Step 1: Verify subscription-only credentials and execute exactly the approved manifest.**

  Unset API billing variables. Use the existing local Codex subscription credential and the user's current Claude OAuth token without printing either value.

  ```bash
  uv run harness-test run execute \
    --manifest "$HARNESS_MANIFEST_PATH" \
    --approve "$HARNESS_APPROVAL_DIGEST"
  ```

  Expected: one Claude session followed by one Codex session, no API fallback, no retry, and no execution outside the approved manifest.

- [ ] **Step 2: Inspect the two job results and delivery receipts.**

  Require for each cell:

  ```text
  n_completed_trials = 1
  n_errored_trials = 0
  no pending/running/cancelled trial
  exactly one workflow attempt
  correctness = 1.0
  workflow = 1.0
  efficiency = 1.0
  ```

  Confirm A2 startup receipts expose Studio Harness `0.8.2` only. Claude must invoke `harness:execute`. Neither trajectory may read all six supporting references; the pre-dispatch path should read only the execution skill and shared contract needed to construct the result.

- [ ] **Step 3: Compare bounded efficiency telemetry with preserved `0.8.1` A2 evidence.**

  Record provider-reported input/output/cache tokens, wall time, and API-equivalent cost when available. Compare Codex with the preserved `0.8.1` A2 values (130,345 prompt tokens and `$0.0987` API-equivalent trajectory cost) and report Claude's invocation/reference-loading change. Treat missing telemetry as missing, never as zero.

- [ ] **Step 4: Apply the canary stop rule.**

  If both cells pass, do not expand into A0, more tasks, or a release matrix; the repair is proven at the observed seam. If either cell fails, diagnose that two-session result only, make the smallest production correction, rerun deterministic affected checks once, create a new candidate commit/pin/manifest, and obtain a new digest-specific approval before any replacement session.

**Task done when:** both provider cells pass correctness, workflow, and efficiency; activation and progressive disclosure are visible in trajectories; and no raw or secret-bearing artifact enters git.

---

## Final spec-coverage audit

- [ ] Discovery metadata covers explicit semantic routing and typed pre-dispatch blockers without claiming ordinary development work.
- [ ] The provider-neutral contract defines all five blocked-result encoding rules from the approved design.
- [ ] Each of the six references has one explicit path predicate and unrelated references are not loaded in the canary.
- [ ] Harness `0.8.2` is committed and pushed from the isolated worktree; the shared checkout remains unchanged.
- [ ] Harness Testing pins the exact remote-fetchable commit and contains no stale current-pin fixture.
- [ ] Each repository ran focused checks during editing and one final relevant checkpoint.
- [ ] The unchanged protected task/scorer awarded `1.0` for correctness, workflow, and efficiency in both A2 cells.
- [ ] No A0 rerun, broad release run, dashboard change, image rebuild, protected-answer leak, raw trajectory commit, or credential exposure occurred.
