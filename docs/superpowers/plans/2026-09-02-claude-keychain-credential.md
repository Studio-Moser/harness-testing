# Claude Keychain Credential Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the local Claude subscription token once in macOS Keychain and load it automatically for isolated Harness Testing runs.

**Architecture:** A focused credential module owns the two native Keychain operations. The CLI exposes prompt-only storage, while `execute_run()` resolves an environment override or Keychain fallback immediately before subscription preflight and passes the result only to Harbor's child environment.

**Tech Stack:** Python 3.12, macOS `/usr/bin/security`, argparse, pytest, Ruff.

**Spec:** [`docs/superpowers/specs/2026-09-02-claude-keychain-credential-design.md`](../specs/2026-09-02-claude-keychain-credential-design.md)

## Global Constraints

- Never place a token in argv, repository files, generated inputs, logs, errors, or test output.
- Harbor 0.22.0 expands per-exec environment values into Docker argv; bridge the
  token through mode-`0600` temporary files and delete the container copy before
  Claude starts.
- Preserve `CLAUDE_CODE_OAUTH_TOKEN` as the first-precedence portable override.
- Query Keychain only for subscription manifests containing a Claude cell and only on macOS.
- Preserve the existing API-key rejection and exact manifest approval gates.
- Run only focused tests during implementation, then Ruff and the full Python suite once before commit.
- Do not start a provider model session.

---

### Task 1: Add Keychain-backed Claude subscription authentication

**Files:**

- Create: `src/harness_testing/Credentials.py`
- Create: `tests/unit/test_Credentials.py`
- Modify: `src/harness_testing/Runs.py`
- Modify: `src/harness_testing/CLI.py`
- Modify: `tests/unit/test_Runs.py`
- Modify: `tests/unit/test_CLI.py`
- Modify: `docs/Runbook.md`

**Interfaces:**

- Produces: `load_claude_subscription_token(environment: Mapping[str, str]) -> str`.
- Produces: `store_claude_subscription_token() -> None`.
- `load_claude_subscription_token()` returns an explicit non-empty environment value first, otherwise the trimmed Keychain value on macOS, otherwise `""`.
- `store_claude_subscription_token()` asks `/usr/bin/security` to prompt for the value and raises `ValueError` on unsupported platforms or storage failure.

- [ ] **Step 1: Write the failing credential unit tests.**

  Cover environment precedence without a Keychain call, successful macOS
  Keychain loading, fail-closed lookup errors, and a storage invocation whose
  final argument is bare `-w` with no token value in argv.

- [ ] **Step 2: Run the credential tests and verify the expected import failure.**

  ```bash
  uv run pytest -q tests/unit/test_Credentials.py
  ```

  Expected: collection fails because `harness_testing.Credentials` does not yet exist.

- [ ] **Step 3: Implement the minimal credential module.**

  Use `subprocess.run()` with captured output for lookup and inherited terminal
  I/O for storage. Discard lookup and storage diagnostics so no credential-like
  subprocess output enters Harness logs.

- [ ] **Step 4: Run the credential tests to green.**

  ```bash
  uv run pytest -q tests/unit/test_Credentials.py
  ```

  Expected: all credential tests pass.

- [ ] **Step 5: Write failing CLI and runner integration tests.**

  The CLI test invokes `main(["auth", "claude"])`, observes a redacted success
  line, and verifies errors return one without secret output. The runner test
  compiles one Claude subscription cell, supplies the credential through the
  resolver, and observes it only in the Harbor child environment.

- [ ] **Step 6: Run only the new integration selections and verify failure.**

  ```bash
  uv run pytest -q tests/unit/test_CLI.py -k claude_auth
  uv run pytest -q tests/unit/test_Runs.py -k keychain
  ```

  Expected: both selections fail because CLI dispatch and runner resolution are absent.

- [ ] **Step 7: Wire the CLI and subscription execution seam.**

  Add the `auth claude` parser/dispatch. In `execute_run()`, resolve the token
  only when subscription mode selects Claude, add a non-empty result only to
  `execution_environment`, and validate that child environment before Harbor.
  In `HarnessClaude`, remove the token from every per-exec and trial-scoped
  agent environment, transfer it through mode-`0600` temporary files, and delete
  the container file before the model command starts and again in a final
  cleanup. Disable inherited ACP support until its pre-run bridge has the same
  secret-safe lifecycle.

- [ ] **Step 8: Document one-time setup and portable fallback.**

  Add `claude setup-token` followed by `uv run harness-test auth claude` to the
  subscription runbook. State that CI/non-macOS uses
  `CLAUDE_CODE_OAUTH_TOKEN` and that neither path authorizes API billing.

- [ ] **Step 9: Run focused checks, then the single checkpoint suite.**

  ```bash
  uv run ruff check src/harness_testing/Credentials.py src/harness_testing/Runs.py src/harness_testing/CLI.py tests/unit/test_Credentials.py tests/unit/test_Runs.py tests/unit/test_CLI.py
  uv run pytest -q tests/unit/test_Credentials.py tests/unit/test_CLI.py
  uv run pytest -q tests/unit/test_Runs.py -k 'keychain or subscription'
  uv run pytest -q
  ```

  Expected: Ruff and all tests pass; no command starts Harbor or a provider model.

- [ ] **Step 10: Perform the security check and commit.**

  Inspect the staged diff for credentials, credential-shaped fixtures, argv
  exposure, and unrelated files. Commit only this task as
  `feat: persist Claude benchmark auth in Keychain`.
