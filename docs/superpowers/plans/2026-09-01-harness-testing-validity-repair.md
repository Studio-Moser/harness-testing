# Harness Testing Validity Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore decision-valid Harness comparisons by publishing the exact `HarnessResult` contract, delivering complete Claude plugins through Harbor, and stopping contaminated or infrastructure-broken runs after their first paired task shard.

**Architecture:** Harbor 0.22.0 remains the sole runner. One packaged Draft 2020-12 schema is read by the public stub, static validator, and RewardKit scorer; provider-specific adapter changes stay narrow; immutable arm provenance drives generated jobs and post-run delivery checks; the existing task-major manifest order becomes the canary boundary.

**Tech Stack:** Python 3.12, `jsonschema` 4.26.0, Harbor 0.22.0, RewardKit 0.1.7, Claude Code 2.1.236, Codex 0.150.1, Docker, pytest, Ruff, TOML, JSON Schema Draft 2020-12.

**Spec:** [`docs/superpowers/specs/2026-09-01-harness-testing-validity-repair-design.md`](../specs/2026-09-01-harness-testing-validity-repair-design.md)

## Global Constraints

- Keep Harbor responsible for installation, authentication, model dispatch, timeouts, logging, artifacts, and trajectory conversion. The custom adapters may expose only the provider features Harbor 0.22.0 is missing.
- Do not edit the production `skills-n-stuff` repository, dashboard code, public result schema, or Shelby contract.
- Do not start a model session during Tasks 1–8. The four-session A0/A2 smoke is compiled only after deterministic implementation and review pass, and execution still requires the generated digest's explicit approval.
- During Tasks 1–7, run only the named unit test or focused `-k` selection. Build images and run the complete unit and task-pack gates once in Task 8.
- Keep correctness all-or-nothing. Diagnostics explain a zero locally; they do not weaken the score or enter the public dashboard.
- Preserve protected expected values. Only the universal schema is model-visible.
- Keep old plugin-seed and hidden-contract cohorts local, partial, quarantined, and outside the repaired compatibility series. Never regrade them under the new model-visible contract.
- Each task ends with a focused commit and a reviewable, independently passing boundary. Do not batch unrelated cleanup into these commits.

---

### Task 1: Add the canonical public HarnessResult schema

**Files:**

- Create: `src/harness_testing/Harness_Result.py`
- Create: `src/harness_testing/Harness_Result.schema.json`
- Create: `tests/unit/test_Harness_Result.py`
- Modify: `src/harness_testing/Contract_Stub_Server.py`
- Modify: `src/harness_testing/Validate.py`
- Modify: `images/Verifier.Dockerfile`
- Modify: `src/harness_testing/Materialize.py`
- Modify: `tests/unit/test_Contract_Stub_Server.py`
- Modify: `tests/unit/test_Validate.py`
- Modify: `tests/unit/test_Materialize.py`

**Interfaces:**

- Consumes: the result shape documented by `plugins/harness/references/harness-contract.md` at the pinned Studio Harness commit and every protected `tasks/contract/*/tests/Expected.json` result.
- Produces:

  ```text
  harness_result_schema_bytes() -> bytes
  load_harness_result_schema() -> dict[str, Any]
  harness_result_schema_errors(value: object) -> tuple[tuple[str, str], ...]
  public_contract(scenario: dict[str, Any]) -> dict[str, Any]
  ```

- `harness_result_schema_errors()` returns `(json_pointer, validator_keyword)` pairs sorted by JSON path and validator keyword. Root is `/`; JSON Pointer escapes `~` and `/`.
- `public_contract()` returns only the `actions` and `harness_result_schema` keys and never returns protected calls, responses, matches, artifacts, evidence requirements, or expected results.

- [ ] **Step 1: Write the failing schema-loader tests.**

  Add `tests/unit/test_Harness_Result.py` with these cases:

  ```python
  import copy
  import json
  from pathlib import Path

  from harness_testing.Harness_Result import (
      harness_result_schema_bytes,
      harness_result_schema_errors,
      load_harness_result_schema,
  )

  REPOSITORY_ROOT = Path(__file__).parents[2]


  def _expected_results() -> list[dict[str, object]]:
      return [
          json.loads(path.read_text())["result"]
          for path in sorted(
              REPOSITORY_ROOT.glob("tasks/contract/*/tests/Expected.json")
          )
      ]


  def test_every_protected_expected_result_matches_the_public_schema():
      assert harness_result_schema_bytes() == (
          REPOSITORY_ROOT
          / "src/harness_testing/Harness_Result.schema.json"
      ).read_bytes()
      assert load_harness_result_schema()["$schema"] == (
          "https://json-schema.org/draft/2020-12/schema"
      )
      assert all(
          harness_result_schema_errors(result) == ()
          for result in _expected_results()
      )


  def test_schema_rejects_empty_unavailable_values_and_unknown_fields():
      result = copy.deepcopy(_expected_results()[0])
      result["route"]["actual_model"] = ""
      result["unexpected"] = True

      errors = harness_result_schema_errors(result)

      assert ("/route/actual_model", "anyOf") in errors
      assert ("/", "additionalProperties") in errors


  def test_schema_enforces_terminal_status_evidence_invariants():
      accepted = copy.deepcopy(
          next(result for result in _expected_results() if result["status"] == "accepted")
      )
      accepted["evidence"]["outcome"] = "unproven"
      blocked = copy.deepcopy(
          next(result for result in _expected_results() if result["status"] == "blocked")
      )
      blocked["blockers"] = []

      assert ("/evidence/outcome", "const") in harness_result_schema_errors(accepted)
      assert ("/blockers", "minItems") in harness_result_schema_errors(blocked)
  ```

- [ ] **Step 2: Run the loader test and confirm it fails because the module does not exist.**

  Run:

  ```bash
  uv run pytest -q tests/unit/test_Harness_Result.py
  ```

  Expected: pytest collection fails with `ModuleNotFoundError: harness_testing.Harness_Result`.

- [ ] **Step 3: Add the complete Draft 2020-12 schema.**

  Create `src/harness_testing/Harness_Result.schema.json` with this exact policy:

  ```json
  {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://studio-moser.github.io/harness-testing/Harness_Result.schema.json",
    "title": "HarnessResult",
    "type": "object",
    "additionalProperties": false,
    "required": ["status", "route", "artifacts", "evidence", "telemetry", "shelby", "blockers"],
    "$defs": {
      "nonblankString": {"type": "string", "minLength": 1, "pattern": "\\S"},
      "nullableNonblankString": {
        "anyOf": [
          {"type": "null"},
          {"$ref": "#/$defs/nonblankString"}
        ]
      },
      "nonblankStringArray": {
        "type": "array",
        "items": {"$ref": "#/$defs/nonblankString"}
      }
    },
    "properties": {
      "status": {"enum": ["accepted", "failed", "blocked", "abandoned"]},
      "route": {
        "type": "object",
        "additionalProperties": false,
        "required": ["requested", "actual_model", "effort", "provider", "executor", "resolution", "attempted", "fallback_reason"],
        "properties": {
          "requested": {"enum": ["bulk", "quick", "default", "taste", "batch", "review", "independent"]},
          "actual_model": {"$ref": "#/$defs/nullableNonblankString"},
          "effort": {"$ref": "#/$defs/nullableNonblankString"},
          "provider": {"$ref": "#/$defs/nullableNonblankString"},
          "executor": {"$ref": "#/$defs/nullableNonblankString"},
          "resolution": {
            "anyOf": [
              {"type": "null"},
              {"enum": ["primary", "fallback"]}
            ]
          },
          "attempted": {"$ref": "#/$defs/nonblankStringArray"},
          "fallback_reason": {"$ref": "#/$defs/nullableNonblankString"}
        }
      },
      "artifacts": {
        "type": "object",
        "additionalProperties": false,
        "required": ["files", "report"],
        "properties": {
          "files": {"$ref": "#/$defs/nonblankStringArray"},
          "report": {"$ref": "#/$defs/nullableNonblankString"}
        }
      },
      "evidence": {
        "type": "object",
        "additionalProperties": false,
        "required": ["fixed_target", "checks", "outcome"],
        "properties": {
          "fixed_target": {"$ref": "#/$defs/nullableNonblankString"},
          "checks": {"$ref": "#/$defs/nonblankStringArray"},
          "outcome": {"enum": ["proven", "unproven"]}
        }
      },
      "telemetry": {
        "type": "object",
        "additionalProperties": false,
        "required": ["attempts", "elapsed", "verification_failures", "token_or_quota_usage"],
        "properties": {
          "attempts": {"type": "integer", "minimum": 0},
          "elapsed": {"$ref": "#/$defs/nullableNonblankString"},
          "verification_failures": {"type": "integer", "minimum": 0},
          "token_or_quota_usage": {"$ref": "#/$defs/nullableNonblankString"}
        }
      },
      "shelby": {
        "type": "object",
        "additionalProperties": false,
        "required": ["project_id", "run_id", "checkpoint_ids"],
        "properties": {
          "project_id": {"$ref": "#/$defs/nullableNonblankString"},
          "run_id": {"$ref": "#/$defs/nullableNonblankString"},
          "checkpoint_ids": {"$ref": "#/$defs/nonblankStringArray"}
        }
      },
      "blockers": {"$ref": "#/$defs/nonblankStringArray"}
    },
    "allOf": [
      {
        "if": {"properties": {"status": {"const": "accepted"}}, "required": ["status"]},
        "then": {
          "properties": {
            "evidence": {"properties": {"outcome": {"const": "proven"}}},
            "blockers": {"maxItems": 0}
          }
        }
      },
      {
        "if": {"properties": {"status": {"const": "blocked"}}, "required": ["status"]},
        "then": {
          "properties": {
            "evidence": {"properties": {"outcome": {"const": "unproven"}}},
            "blockers": {"minItems": 1}
          }
        }
      }
    ]
  }
  ```

- [ ] **Step 4: Implement the package-resource loader and stable error paths.**

  In `src/harness_testing/Harness_Result.py`, load bytes with `importlib.resources.files("harness_testing")`, parse a fresh dictionary for every caller, call `Draft202012Validator.check_schema()`, and validate with one module-level `Draft202012Validator`. Use:

  ```python
  _SCHEMA_RESOURCE = files("harness_testing").joinpath("Harness_Result.schema.json")


  def harness_result_schema_bytes() -> bytes:
      return _SCHEMA_RESOURCE.read_bytes()


  def load_harness_result_schema() -> dict[str, Any]:
      schema = json.loads(harness_result_schema_bytes())
      if not isinstance(schema, dict):
          raise ValueError("HarnessResult schema must be a JSON object")
      Draft202012Validator.check_schema(schema)
      return schema


  def _json_pointer(path: Iterable[object]) -> str:
      parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
      return "/" + "/".join(parts) if parts else "/"


  _VALIDATOR = Draft202012Validator(load_harness_result_schema())


  def harness_result_schema_errors(value: object) -> tuple[tuple[str, str], ...]:
      errors = sorted(
          _VALIDATOR.iter_errors(value),
          key=lambda error: (list(error.absolute_path), str(error.validator)),
      )
      return tuple(
          (_json_pointer(error.absolute_path), str(error.validator))
          for error in errors
      )
  ```

- [ ] **Step 5: Make the public stub serve the schema without mutating protected scenarios.**

  Add `public_contract()` to `Contract_Stub_Server.py` and route `GET /contract` through it:

  ```python
  def public_contract(scenario: dict[str, Any]) -> dict[str, Any]:
      contract = scenario.get("contract")
      actions = contract.get("actions") if isinstance(contract, dict) else None
      if not isinstance(actions, list):
          raise ValueError("scenario contract has no public actions")
      return {
          "actions": actions,
          "harness_result_schema": load_harness_result_schema(),
      }
  ```

  Update the server and `test_harness_stub_describe_prints_the_public_contract` assertions to require both keys and to prove that `scenario["calls"]` and responses are absent.

- [ ] **Step 6: Reuse the canonical schema in static task validation.**

  In `_validate_benchmark_task_assets()`, replace the hand-written top-level result-key check with `harness_result_schema_errors(result)`. Reject a scenario whose protected `contract` already contains the reserved `harness_result_schema` key. Format protected expectation failures as `HarnessResult <pointer>: <validator>` without exposing the protected value.

- [ ] **Step 7: Package and digest the schema in the verifier image.**

  Add `Harness_Result.py` and `Harness_Result.schema.json` to the verifier `COPY` line and `_IMAGE_INPUTS["verifier"]`. Extend `test_verifier_image_carries_shared_workflow_support` and `test_verifier_image_digest_binds_the_shared_decoder` so changing either resource changes the verifier input digest.

- [ ] **Step 8: Run only the focused contract-resource tests.**

  Run:

  ```bash
  uv run ruff check src/harness_testing/Harness_Result.py src/harness_testing/Contract_Stub_Server.py src/harness_testing/Validate.py tests/unit/test_Harness_Result.py tests/unit/test_Contract_Stub_Server.py tests/unit/test_Validate.py tests/unit/test_Materialize.py
  uv run pytest -q tests/unit/test_Harness_Result.py tests/unit/test_Contract_Stub_Server.py tests/unit/test_Validate.py -k 'HarnessResult or public_contract or harness_stub or contract_expectation'
  uv run pytest -q tests/unit/test_Materialize.py -k 'verifier_image'
  ```

  Expected: all selected tests pass; no Docker image is built yet.

- [ ] **Step 9: Commit the canonical contract boundary.**

  ```bash
  git add src/harness_testing/Harness_Result.py src/harness_testing/Harness_Result.schema.json src/harness_testing/Contract_Stub_Server.py src/harness_testing/Validate.py src/harness_testing/Materialize.py images/Verifier.Dockerfile tests/unit/test_Harness_Result.py tests/unit/test_Contract_Stub_Server.py tests/unit/test_Validate.py tests/unit/test_Materialize.py
  git commit -m "fix: publish the canonical harness result contract"
  ```

**Task done when:** Every protected expected result validates, invalid empty strings and unknown fields fail, and `harness-stub describe` returns the identical schema bytes available to the scorer without exposing protected answers.

---

### Task 2: Replace opaque contract failures with bounded diagnostics

**Files:**

- Modify: `src/harness_testing/Contract_Criteria.py`
- Modify: `tests/unit/test_Contract_Criteria.py`

**Interfaces:**

- Consumes: actual workspace result, protected expected result, protected-file manifest, and expected artifact rules.
- Produces:

  ```text
  result_contract_diagnostics(
      workspace: Path,
      expected_path: Path,
      protected_manifest: Path,
  ) -> tuple[str, ...]

  result_matches_contract(
      workspace: Path,
      expected_path: Path,
      protected_manifest: Path,
  ) -> bool
  ```

- Diagnostics use `<group>:<json-pointer-or-path>:<code>`, preserve this group order, and stop after 12 entries: `result-json`, `result-schema`, `protected-state`, `result-semantics`, `artifact`.
- The public RewardKit criterion remains the existing boolean `result_matches_contract()`.

- [ ] **Step 1: Add failing tests for stable diagnostic groups and bounds.**

  Extend `tests/unit/test_Contract_Criteria.py` to assert:

  ```python
  def test_contract_diagnostics_distinguish_json_schema_semantics_and_artifacts(tmp_path):
      workspace, expected, manifest = _fixture(tmp_path)
      result_path = workspace / "Harness_Result.json"
      result_path.write_text("{")
      assert Contract_Criteria.result_contract_diagnostics(
          workspace, expected, manifest
      ) == ("result-json:/Harness_Result.json:malformed",)

      result = _result()
      result["route"]["actual_model"] = ""
      result_path.write_text(json.dumps(result))
      assert any(
          item == "result-schema:/route/actual_model:anyOf"
          for item in Contract_Criteria.result_contract_diagnostics(
              workspace, expected, manifest
          )
      )

      result = _result()
      result["route"]["requested"] = "quick"
      result_path.write_text(json.dumps(result))
      assert any(
          item == "result-semantics:/route/requested:mismatch"
          for item in Contract_Criteria.result_contract_diagnostics(
              workspace, expected, manifest
          )
      )

      (workspace / "Output.json").write_text('{"value":3}\n')
      result_path.write_text(json.dumps(_result()))
      assert any(
          item == "artifact:/Output.json:mismatch"
          for item in Contract_Criteria.result_contract_diagnostics(
              workspace, expected, manifest
          )
      )
  ```

  Add one test with more than 12 independent schema errors and assert `len(diagnostics) == 12`. Add a `capsys` test proving `result_matches_contract()` prints only `harness-contract: <diagnostic>` lines and still returns `False`.

- [ ] **Step 2: Run the focused test and confirm the missing diagnostic API.**

  ```bash
  uv run pytest -q tests/unit/test_Contract_Criteria.py -k 'diagnostic'
  ```

  Expected: failures report that `result_contract_diagnostics` does not exist.

- [ ] **Step 3: Delete the hand-written shape validator and use the canonical schema.**

  Remove `_RESULT_KEYS`, `_ROUTE_KEYS`, `_ARTIFACT_KEYS`, `_EVIDENCE_KEYS`, `_TELEMETRY_KEYS`, `_SHELBY_KEYS`, `_strings`, `_nonblank_strings`, `_optional_string`, and `_complete_result`. Import `harness_result_schema_errors`.

- [ ] **Step 4: Implement bounded diagnostics in the scorer's existing comparison flow.**

  Keep `_artifact_matches`, `_attempts_match`, `_evidence_matches`, and protected-state checks. Replace `_result_semantics_match()` with `_result_semantic_diagnostics()` that emits one exact path/code for each existing semantic comparison:

  ```text
  /status
  /route/{requested,actual_model,effort,provider,executor,resolution,attempted,fallback_reason}
  /artifacts/files
  /artifacts/report
  /evidence/fixed_target
  /evidence/checks
  /evidence/outcome
  /telemetry/attempts
  /telemetry/verification_failures
  /shelby
  /blockers
  ```

  Use `duplicate` for duplicate declared files, `missing-prefix` for evidence requirements, and `mismatch` for protected semantic disagreement. Do not compare optional telemetry values `elapsed` or `token_or_quota_usage`; validate only their public types, preserving the current contract.

  Assemble groups in `result_contract_diagnostics()`, skip semantic indexing when the actual result fails schema validation, and truncate once at `_MAX_DIAGNOSTICS = 12`. `result_matches_contract()` becomes:

  ```python
  diagnostics = result_contract_diagnostics(
      workspace, expected_path, protected_manifest
  )
  for diagnostic in diagnostics:
      print(f"harness-contract: {diagnostic}")
  return not diagnostics
  ```

- [ ] **Step 5: Run only the scorer unit module.**

  ```bash
  uv run ruff check src/harness_testing/Contract_Criteria.py tests/unit/test_Contract_Criteria.py
  uv run pytest -q tests/unit/test_Contract_Criteria.py
  ```

  Expected: all scorer tests pass; failed criteria expose bounded local reasons while score behavior is unchanged.

- [ ] **Step 6: Commit the diagnostic boundary.**

  ```bash
  git add src/harness_testing/Contract_Criteria.py tests/unit/test_Contract_Criteria.py
  git commit -m "fix: explain contract result failures locally"
  ```

**Task done when:** Schema, protected-state, semantic, and artifact defects are distinguishable in raw verifier output, and correctness remains strict boolean pass/fail.

---

### Task 3: Add the narrow Claude plugin-directory adapter

**Files:**

- Create: `src/harness_testing/Claude_Agent.py`
- Create: `tests/unit/test_Claude_Agent.py`

**Interfaces:**

- Consumes: Harbor's pinned `ClaudeCode` constructor plus `plugin_dirs: list[str] | None` from generated jobs.
- Produces: `harness_testing.Claude_Agent:HarnessClaude`.
- Valid paths are zero to two unique immediate children of `/harness-arm/claude/plugins/`. Reject non-strings, relative paths, root itself, nested paths, `..`, duplicates, and more than two values before provider execution.
- The only behavior override is `build_cli_flags()`; every other Claude lifecycle method remains Harbor's.

- [ ] **Step 1: Write failing constructor and flag tests.**

  Create `tests/unit/test_Claude_Agent.py`:

  ```python
  from pathlib import Path

  import pytest

  from harness_testing.Claude_Agent import HarnessClaude


  def _agent(tmp_path: Path, plugin_dirs=None) -> HarnessClaude:
      return HarnessClaude(
          logs_dir=tmp_path,
          model_name="anthropic/claude-sonnet-4-6",
          version="2.1.236",
          reasoning_effort="high",
          plugin_dirs=plugin_dirs,
      )


  def test_claude_adapter_appends_ordered_repeatable_plugin_dirs(tmp_path):
      agent = _agent(
          tmp_path,
          [
              "/harness-arm/claude/plugins/superpowers",
              "/harness-arm/claude/plugins/harness",
          ],
      )
      assert agent.build_cli_flags() == (
          "--effort high --permission-mode=bypassPermissions "
          "--plugin-dir /harness-arm/claude/plugins/superpowers "
          "--plugin-dir /harness-arm/claude/plugins/harness"
      )


  @pytest.mark.parametrize(
      "plugin_dirs",
      [
          ["relative/harness"],
          ["/harness-arm/claude/plugins"],
          ["/harness-arm/claude/plugins/harness/nested"],
          ["/harness-arm/claude/plugins/../harness"],
          [
              "/harness-arm/claude/plugins/harness",
              "/harness-arm/claude/plugins/harness",
          ],
          [
              "/harness-arm/claude/plugins/one",
              "/harness-arm/claude/plugins/two",
              "/harness-arm/claude/plugins/three",
          ],
      ],
  )
  def test_claude_adapter_rejects_untrusted_plugin_dirs(tmp_path, plugin_dirs):
      with pytest.raises(ValueError, match="plugin_dirs"):
          _agent(tmp_path, plugin_dirs)
  ```

- [ ] **Step 2: Run the test and confirm import failure.**

  ```bash
  uv run pytest -q tests/unit/test_Claude_Agent.py
  ```

  Expected: collection fails because `Claude_Agent.py` does not exist.

- [ ] **Step 3: Implement the adapter against Harbor's actual extension seam.**

  Use `PurePosixPath` validation before `super().__init__()` and append shell-quoted flags after `super().build_cli_flags()`:

  ```python
  class HarnessClaude(ClaudeCode):
      """Claude Code with Harbor 0.22.0's missing session-local plugin flags."""

      def __init__(
          self,
          *args: Any,
          plugin_dirs: list[str] | None = None,
          **kwargs: Any,
      ) -> None:
          values = [] if plugin_dirs is None else plugin_dirs
          if not isinstance(values, list) or len(values) > 2:
              raise ValueError("plugin_dirs must contain zero to two paths")
          paths = tuple(PurePosixPath(value) for value in values if isinstance(value, str))
          root = PurePosixPath("/harness-arm/claude/plugins")
          if (
              len(paths) != len(values)
              or len(set(paths)) != len(paths)
              or any(path.parent != root or ".." in path.parts for path in paths)
          ):
              raise ValueError(
                  "plugin_dirs must be unique direct children of "
                  "/harness-arm/claude/plugins"
              )
          self._plugin_dirs = paths
          super().__init__(*args, **kwargs)

      @override
      def build_cli_flags(self) -> str:
          parts = [super().build_cli_flags()]
          parts.extend(
              f"--plugin-dir {shlex.quote(path.as_posix())}"
              for path in self._plugin_dirs
          )
          return " ".join(part for part in parts if part)
  ```

- [ ] **Step 4: Run only the Claude adapter tests.**

  ```bash
  uv run ruff check src/harness_testing/Claude_Agent.py tests/unit/test_Claude_Agent.py
  uv run pytest -q tests/unit/test_Claude_Agent.py
  ```

  Expected: all adapter tests pass without invoking Claude or Docker.

- [ ] **Step 5: Commit the Harbor compatibility shim.**

  ```bash
  git add src/harness_testing/Claude_Agent.py tests/unit/test_Claude_Agent.py
  git commit -m "fix: expose claude session plugin directories"
  ```

**Task done when:** Generated code can supply A0–A3's exact ordered Claude plugin paths and no other provider behavior changes.

---

### Task 4: Materialize intact Claude plugins and exact delivery provenance

**Files:**

- Modify: `src/harness_testing/Materialize.py`
- Modify: `tests/unit/test_Materialize.py`

**Interfaces:**

- Consumes: `_PluginInput.plugin_path`, pinned Node agent image containing Claude Code 2.1.236, and arm layer order.
- Produces:

  ```text
  claude/plugins/superpowers/
  claude/plugins/harness/
  ```

  and ordered provenance entries:

  ```json
  {
    "layer": "Studio Harness",
    "surface": "claude-plugin-dir",
    "path": "/harness-arm/claude/plugins/harness",
    "capabilities": ["skills"]
  }
  ```

- Codex remains `codex-plugin` with path `/tmp/codex-home/plugins/cache/<marketplace>/<plugin>/<version>` and Superpowers remains `skills` only unless its exact Codex manifest declares nonempty hooks.
- `_ARM_MATERIALIZER_SCHEMA` changes from `"2"` to `"3"`.

- [ ] **Step 1: Replace plugin-seed expectations with failing direct-plugin tests.**

  Update the Claude materialization tests to require:

  - intact `.claude-plugin/plugin.json`, `skills/`, `references/`, `scripts/`, and Superpowers `hooks/` beneath `claude/plugins/<name>/`;
  - no `claude/plugin-seed`, `known_marketplaces.json`, or `claude/settings.json`;
  - A3 paths ordered `superpowers`, then `harness`;
  - provenance surface `claude-plugin-dir`, exact mounted path, and observed capabilities;
  - materializer schema `"3"`;
  - the strict validation Docker command uses `--network none` and one `claude plugin validate --strict /bundle/claude/plugins/<name>` per plugin.

- [ ] **Step 2: Run the focused materializer selection and observe plugin-seed failures.**

  ```bash
  uv run pytest -q tests/unit/test_Materialize.py -k 'claude or provider_provenance or codex_harness or native_installer'
  ```

  Expected: Claude assertions fail because bundles still contain `plugin-seed` and provenance still says `claude-plugin-seed`.

- [ ] **Step 3: Split Claude validation from Codex installation.**

  Replace `_run_native_plugin_install()` with:

  ```text
  _run_claude_plugin_validation(
      root: Path,
      bundle: Path,
      inputs: tuple[_PluginInput, ...],
  ) -> None

  _run_codex_plugin_install(
      root: Path,
      inputs: tuple[_PluginInput, ...],
      output: Path,
  ) -> None
  ```

  Claude validation mounts the assembled bundle read-only at `/bundle`, uses `--network none`, starts no provider session, and runs `claude plugin validate --strict` on each copied path. Codex retains its existing `CODEX_HOME`, marketplace-add, plugin-add, cache verification, and copied provider home.

- [ ] **Step 4: Assemble Claude plugins directly.**

  Simplify `_assemble_claude_bundle()` to copy each `plugin_input.plugin_path` into `bundle / "claude" / "plugins" / plugin_input.plugin`. Remove Claude branches from `_installed_plugin_source()` and rename the remaining helper `_installed_codex_plugin_source()`.

  In `materialize_arm()`:

  ```python
  if provider == "claude":
      _assemble_claude_bundle(bundle, plugin_inputs)
      if native_cli:
          _run_claude_plugin_validation(root, bundle, plugin_inputs)
  else:
      if native_cli:
          _run_codex_plugin_install(root, plugin_inputs, native_output)
      _assemble_codex_bundle(bundle, plugin_inputs, native_output, native_cli)
  ```

- [ ] **Step 5: Record exact ordered provider paths and capabilities.**

  Change `_delivery_surfaces()` so every entry contains exactly `layer`, `surface`, `path`, and `capabilities`. Detect Claude hooks from the copied plugin's `hooks/` directory or nonempty manifest declaration. Preserve the source/layer iteration order rather than sorting.

- [ ] **Step 6: Run the focused materializer selection.**

  ```bash
  uv run ruff check src/harness_testing/Materialize.py tests/unit/test_Materialize.py
  uv run pytest -q tests/unit/test_Materialize.py -k 'claude or provider_provenance or codex_harness or native_installer'
  ```

  Expected: selected tests pass; no actual arm is materialized and no image is rebuilt.

- [ ] **Step 7: Commit direct Claude delivery.**

  ```bash
  git add src/harness_testing/Materialize.py tests/unit/test_Materialize.py
  git commit -m "fix: materialize complete claude plugins"
  ```

**Task done when:** A0 has no benchmark layer, A1/A2/A3 contain only their exact intact plugins, Claude validation is model-free, and Codex's working native path is unchanged.

---

### Task 5: Generate jobs from arm provenance and bind both adapters

**Files:**

- Modify: `src/harness_testing/Runs.py`
- Modify: `tests/unit/test_Runs.py`

**Interfaces:**

- Consumes: immutable `Provenance.json` delivery entries and provider bundle paths.
- Produces:

  ```python
  _AGENT_ADAPTERS = {
      "claude": (
          "harness_testing.Claude_Agent:HarnessClaude",
          Path("src/harness_testing/Claude_Agent.py"),
      ),
      "codex": (
          "harness_testing.Codex_Agent:HarnessCodex",
          Path("src/harness_testing/Codex_Agent.py"),
      ),
  }
  ```

- Claude generated kwargs contain `plugin_dirs` only when nonempty. Claude jobs contain no plugin-seed environment variable, settings file, or generic Harbor skills path.
- Static cell validation proves exact layer order, exact surface, target existence inside the bundle, and no A0 contamination before a manifest can be approved.

- [ ] **Step 1: Update run fixtures and add failing A0–A3 job assertions.**

  Make `_add_bundle()` write realistic `layers` and `delivery_surfaces`, and make `run_root` copy `Claude_Agent.py`, `Harness_Result.py`, and `Harness_Result.schema.json` because adapter/image digests now bind them.

  Add tests that compile Claude A0, A1, A2, and A3 cells and assert:

  ```python
  assert a0_agent.import_path == "harness_testing.Claude_Agent:HarnessClaude"
  assert "plugin_dirs" not in a0_agent.kwargs
  assert a1_agent.kwargs["plugin_dirs"] == [
      "/harness-arm/claude/plugins/superpowers"
  ]
  assert a2_agent.kwargs["plugin_dirs"] == [
      "/harness-arm/claude/plugins/harness"
  ]
  assert a3_agent.kwargs["plugin_dirs"] == [
      "/harness-arm/claude/plugins/superpowers",
      "/harness-arm/claude/plugins/harness",
  ]
  assert all(agent.env == {} and agent.skills == [] for agent in agents)
  ```

  Add rejection tests for a provenance path outside `/harness-arm`, wrong layer order, missing host directory, extra A0 layer, and a generated Claude `CLAUDE_CODE_PLUGIN_SEED_DIR` value.

- [ ] **Step 2: Run the focused job-generation tests and observe the stock-Claude/plugin-seed mismatch.**

  ```bash
  uv run pytest -q tests/unit/test_Runs.py -k 'generated_job or adapter or delivery or arm_mount or manifest'
  ```

  Expected: Claude import-path and plugin-dir assertions fail.

- [ ] **Step 3: Add both adapter identities and provider-path helpers.**

  Add private helpers with exact signatures:

  ```text
  _bundle_provenance(bundle: Path) -> dict[str, Any]
  _validated_delivery_surfaces(
      bundle: Path,
      provider: str,
      arm: str,
  ) -> tuple[dict[str, object], ...]
  _claude_plugin_dirs(bundle: Path, arm: str) -> list[str]
  ```

  `_validated_delivery_surfaces()` compares layer names to the existing arm policy, requires an empty tuple for A0, maps `/harness-arm/...` and `/tmp/codex-home/...` paths back to the corresponding host bundle tree, and rejects files or paths that escape those provider roots.

- [ ] **Step 4: Generate Claude jobs through `HarnessClaude`.**

  Delete the Claude `settings.json` branch in `_provider_config()`. In `_job_document()`, use the Claude adapter import path and add:

  ```python
  plugin_dirs = _claude_plugin_dirs(bundle, cell.arm)
  if plugin_dirs:
      kwargs["plugin_dirs"] = plugin_dirs
  ```

  Leave `environment = {}` and `skills = []`. Keep Codex's inline native config and read-only cache mount.

- [ ] **Step 5: Bind static delivery agreement into cell and manifest validation.**

  Call `_validated_delivery_surfaces()` from `_validate_cell()`. In `_verify_generated_inputs()`, load every approved YAML and compare its agent import path and Claude `plugin_dirs` to the selected cell's exact provenance. Because configs are task-major, map `manifest.harbor_config_paths[index]` to `manifest.cells[index % len(manifest.cells)]` and reject any order mismatch.

- [ ] **Step 6: Run only the focused run module selection.**

  ```bash
  uv run ruff check src/harness_testing/Runs.py tests/unit/test_Runs.py
  uv run pytest -q tests/unit/test_Runs.py -k 'generated_job or adapter or delivery or arm_mount or manifest'
  ```

  Expected: selected tests pass, Harbor config round-trips, and manifest provenance includes the selected Claude and Codex adapter digests.

- [ ] **Step 7: Commit provenance-driven job generation.**

  ```bash
  git add src/harness_testing/Runs.py tests/unit/test_Runs.py
  git commit -m "fix: bind generated jobs to arm delivery provenance"
  ```

**Task done when:** A generated job cannot claim an arm different from its read-only bundle, and the approved manifest binds every selected custom adapter byte-for-byte.

---

### Task 6: Record Codex inventory and enforce the first-shard delivery gate

**Files:**

- Modify: `src/harness_testing/Codex_Agent.py`
- Modify: `src/harness_testing/Runs.py`
- Modify: `tests/unit/test_Codex_Agent.py`
- Modify: `tests/unit/test_Runs.py`

**Interfaces:**

- Consumes: Codex's effective config upload seam, Claude `system/init` stream event, Harbor job/trial result artifacts, and task-major manifest order.
- Produces:

  ```text
  /logs/agent/plugin-inventory.json
  ```

  before Codex model dispatch, plus:

  ```text
  _completed_job_errors(
      root: Path,
      cell: RunCell,
      job_name: str,
      benchmark_skill_names: frozenset[str],
  ) -> tuple[str, ...]
  ```

- A correctness reward of `0.0` is a completed task outcome, not an execution error.
- Authentication, provider, sandbox, timeout, missing agent evidence, unreadable verifier evidence, trial exception, and delivery mismatch are execution errors.

- [ ] **Step 1: Add a failing Codex inventory-hook test.**

  Use `asyncio.run()` with a fake environment to call `_upload_effective_config()` directly and assert the post-upload command includes:

  ```text
  CODEX_HOME=/tmp/codex-home
  codex plugin list --json
  /logs/agent/plugin-inventory.json
  ```

  Assert that a nonzero inventory command propagates as an adapter failure rather than allowing model dispatch.

- [ ] **Step 2: Add failing delivery and canary tests.**

  In `test_Runs.py`, create minimal completed job fixtures for both providers:

  - job `result.json` with `stats.n_completed_trials == 1`, `n_errored_trials == 0`, and no running/pending/cancelled trials;
  - one trial with `exception_info: null` and readable `verifier/reward.json`;
  - Claude `agent/claude-code.txt` containing one `{"type":"system","subtype":"init","plugins":[],"skills":[]}` line for A0 or the exact expected benchmark names for a layered arm;
  - Codex `agent/plugin-inventory.json` containing `{"installed":[],"available":[]}` for A0 or exact installed benchmark records for a layered arm.

  Add exact tests for:

  1. expected plugin names and plugin skill directories pass;
  2. A0 benchmark plugin/skill contamination fails;
  3. a missing expected A2 plugin fails;
  4. a verifier reward of zero with valid infrastructure passes;
  5. a trial exception fails;
  6. a two-task/two-cell execution with a canary delivery mismatch invokes exactly the first two Harbor jobs and never the third;
  7. the same four-job execution with valid delivery and first-task correctness zero invokes all four jobs.

- [ ] **Step 3: Run focused failing tests.**

  ```bash
  uv run pytest -q tests/unit/test_Codex_Agent.py -k 'inventory'
  uv run pytest -q tests/unit/test_Runs.py -k 'delivery or canary or correctness_zero'
  ```

  Expected: failures identify the absent inventory receipt and absent post-run gate.

- [ ] **Step 4: Record Codex inventory after effective config upload and before dispatch.**

  Override Codex's narrow upload seam rather than copying its full `run()` implementation:

  ```python
  @override
  async def _upload_effective_config(
      self,
      environment: BaseEnvironment,
      config: dict[str, Any],
      remote_path: str,
  ) -> None:
      await super()._upload_effective_config(environment, config, remote_path)
      await self.exec_as_agent(
          environment,
          command=(
              "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
              "mkdir -p /logs/agent; "
              "codex plugin list --json > /logs/agent/plugin-inventory.json"
          ),
          env={"CODEX_HOME": self._REMOTE_CODEX_HOME.as_posix()},
      )
  ```

  Harbor has already created `CODEX_HOME` and uploaded `config.toml` when this seam runs; its `exec_as_agent()` raises on nonzero exit. Harbor's existing cleanup then removes the provider home but retains the receipt in `/logs/agent`.

- [ ] **Step 5: Parse only benchmark delivery evidence.**

  In `Runs.py`, add bounded parsers that:

  - locate exactly one primary Claude init event and normalize plugin entries from either objects with a `name` field, direct names, or `<name>@<marketplace>` strings; reject any other benchmark-looking representation;
  - derive each expected Claude skill as `<plugin-name>:<skill-directory-name>` from the selected immutable plugin path, matching Claude's plugin namespace;
  - derive `benchmark_skill_names` once per manifest as the union of those namespaced skills in every selected non-A0 bundle, then compare each Claude init event's intersection with that union to the cell's expected namespaced skills;
  - compare only the benchmark plugin names `superpowers` and `harness`, leaving provider built-ins alone;
  - parse Codex `installed` entries by `name`, `pluginId`, `marketplaceName`, `version`, `enabled`, and `installed`;
  - compare expected benchmark plugins from provenance and reject an unexpected benchmark plugin in A0;
  - cap reported delivery errors at 12 stable strings.

- [ ] **Step 6: Validate Harbor completion without interpreting correctness.**

  `_completed_job_errors()` must require one completed trial per generated job attempt, `exception_info is None`, readable provider startup evidence, readable `verifier/reward.json`, and a valid `verifier_result.rewards` mapping. It must never inspect reward values when deciding whether execution infrastructure passed.

- [ ] **Step 7: Add the canary boundary to `execute_run()`.**

  Preserve the existing sequential Harbor calls. Execute the first `len(manifest.cells)` configs, which are already the first selected task across all cells, then evaluate every first-shard job together. Raise `ValueError("delivery canary failed: " + "; ".join(errors))` before config `len(cells) + 1` if any infrastructure or delivery error exists. For later configs, run `_completed_job_errors()` immediately after each Harbor return.

  Update `test_subscription_selector_is_scoped_to_the_harbor_process` to stub a valid completed-job check; do not weaken its credential/process-environment assertion.

- [ ] **Step 8: Run only the adapter and canary selections.**

  ```bash
  uv run ruff check src/harness_testing/Codex_Agent.py src/harness_testing/Runs.py tests/unit/test_Codex_Agent.py tests/unit/test_Runs.py
  uv run pytest -q tests/unit/test_Codex_Agent.py
  uv run pytest -q tests/unit/test_Runs.py -k 'delivery or canary or correctness_zero or subscription_selector'
  ```

  Expected: all selected tests pass without running Harbor or a provider model.

- [ ] **Step 9: Commit the fail-fast runtime boundary.**

  ```bash
  git add src/harness_testing/Codex_Agent.py src/harness_testing/Runs.py tests/unit/test_Codex_Agent.py tests/unit/test_Runs.py
  git commit -m "fix: stop runs on invalid arm delivery"
  ```

**Task done when:** The first paired task proves every selected arm loaded as declared, task failure remains measurable, and invalid delivery cannot burn the remaining session budget.

---

### Task 7: Start the repaired compatibility series and document the real workflow

**Files:**

- Modify: `Versions.toml`
- Modify: `src/harness_testing/Results.py`
- Modify: `src/harness_testing/Validate.py`
- Modify: `tests/unit/test_CLI.py`
- Modify: `tests/unit/test_Materialize.py`
- Modify: `tests/unit/test_Results.py`
- Modify: `tests/unit/test_Validate.py`
- Create: `tests/Fixtures/Run_Manifests/Repaired_Manifest.json`
- Modify: `README.md`
- Modify: `docs/Methodology.md`
- Modify: `docs/Runbook.md`
- Modify: `docs/Task_Authoring.md`
- Modify: every tracked `Dockerfile` below `tasks/contract/*/` and `tasks/workflow/*/` that references a `studio-moser/harness-testing-*` image
- Modify: every `tasks/contract/*/task.toml` and `tasks/workflow/*/task.toml` whose environment fixture digest changes

**Interfaces:**

- Consumes: repaired scorer, adapters, arm materializer schema `3`, verifier inputs, and task image pins.
- Produces: repository/methodology schema `0.2.0`, image tags `studio-moser/harness-testing-{node,rust,verifier}:0.2.0`, refreshed frozen environment digests, affected-change routing for the schema resource, and a publication-time current-manifest gate.
- Existing `0.1.0` raw cohorts remain local, cannot be sanitized into `results/` under `0.2.0`, and receive no reviewed compatibility mapping.

- [ ] **Step 1: Add failing version and affected-validation assertions.**

  Update tests to expect CLI/repository schema `0.2.0`, materialized image tags `0.2.0`, and `Harness_Result.schema.json` changes to select:

  ```text
  tests/unit/test_Harness_Result.py
  tests/unit/test_Contract_Criteria.py
  tests/unit/test_Contract_Stub_Server.py
  tests/unit/test_Validate.py
  tests/unit/test_Materialize.py
  verifier image build
  ```

  Keep dashboard commands absent for this change set.

  Add one minimal, internally digest-valid schema `0.2.0` manifest fixture at `tests/Fixtures/Run_Manifests/Repaired_Manifest.json`. Add `test_publication_rejects_an_old_or_missing_run_manifest()` in `test_Results.py`; copy that fixture beneath the temporary content-addressed `runs/generated/<digest>/Manifest.json` path and prove that a finalized candidate cannot be written under `results/` when the manifest is absent, has schema `0.1.0`, or when `provenance.methodology_schema` is not `0.2.0`. Add the positive assertion that the unchanged `0.2.0` manifest and methodology pair reaches the normal sanitizer checks.

- [ ] **Step 2: Run the narrow version/routing tests and observe old-series failures.**

  ```bash
  uv run pytest -q tests/unit/test_CLI.py tests/unit/test_Validate.py tests/unit/test_Materialize.py -k 'version or affected_validation or image_build'
  ```

  Expected: assertions still see `0.1.0` and no schema-resource routing.

- [ ] **Step 3: Bump the repository schema and all task image references.**

  Change `Versions.toml` to:

  ```toml
  [repository]
  schema_version = "0.2.0"
  ```

  Replace every tracked `studio-moser/harness-testing-{node,rust,verifier}:0.1.0` task Dockerfile reference with `:0.2.0`. This mechanical update is required because the schema resource changes the verifier image and the repository schema changes all generated image tags.

- [ ] **Step 4: Recompute frozen environment digests without changing fixture content.**

  Use the existing `Validate._fixture_digest()` algorithm in a read-only command to print each new digest, then apply those exact values to `metadata.fixture_digest` in all 17 task manifests. Do not add a persistent digest-rewrite command.

  Verify the mechanical boundary:

  ```bash
  rg -n 'harness-testing-(node|rust|verifier):0\.1\.0' tasks
  uv run harness-test validate --static-only
  ```

  Expected: `rg` prints nothing; static validation reports no fixture or task-image pin drift.

- [ ] **Step 5: Route canonical-schema changes to the right surgical checks.**

  In `affected_validation_commands()`, treat `src/harness_testing/Harness_Result.schema.json` as shared contract/verifier input. Select the five unit modules and `--verifier` image build listed in Step 1, but do not select dashboard tests.

- [ ] **Step 6: Reject incompatible manifests at the publication boundary.**

  Keep local construction and staging available for review, but before `sanitize_public_result()` writes a finalized document into `results/`:

  1. read the current repository schema from `Versions.toml`;
  2. require `provenance.methodology_schema` to equal that schema;
  3. resolve `run.manifest_digest` only to `runs/generated/<digest-without-prefix>/Manifest.json`;
  4. load it with `Runs.load_manifest()` so its content digest is revalidated;
  5. require the manifest's `schema_version` to equal the current repository schema;
  6. require `compatibility.reviewed_mapping is None` for this repaired series.

  Use a private `Results._current_series_errors(root, document) -> tuple[str, ...]` helper and raise `ValueError("result is not in the current compatibility series: " + "; ".join(errors))` before writing. This leaves old local data inspectable but makes AC11 enforceable rather than documentary.

- [ ] **Step 7: Correct the docs to match the pinned provider integrations.**

  Document these exact facts:

  - Claude uses immutable repeatable `--plugin-dir` paths and model-free `claude plugin validate --strict` materialization; no plugin seed is used.
  - Codex keeps native marketplace/plugin materialization and records a pre-dispatch inventory; its Superpowers capability remains skills-only.
  - `harness-stub describe` exposes the universal result schema plus task-specific public actions, never protected answers.
  - the first selected task is the delivery canary across every selected cell; correctness zero continues, infrastructure/delivery failure stops;
  - full deterministic gates run once at the checkpoint;
  - old hidden-contract/plugin-seed cohorts remain quarantined and are not regraded or mapped into schema `0.2.0`.

- [ ] **Step 8: Run only version, routing, publication, and static validation.**

  ```bash
  uv run ruff check src/harness_testing/Results.py src/harness_testing/Validate.py tests/unit/test_Validate.py tests/unit/test_CLI.py tests/unit/test_Materialize.py tests/unit/test_Results.py
  uv run pytest -q tests/unit/test_CLI.py tests/unit/test_Validate.py tests/unit/test_Materialize.py tests/unit/test_Results.py -k 'version or affected_validation or image_build or methodology or publication'
  uv run harness-test validate --static-only
  ```

  Expected: all selected tests and static validation pass; no image is built yet.

- [ ] **Step 9: Commit the new compatibility boundary.**

  ```bash
  git add Versions.toml src/harness_testing/Results.py src/harness_testing/Validate.py tests/Fixtures/Run_Manifests/Repaired_Manifest.json tests/unit/test_CLI.py tests/unit/test_Materialize.py tests/unit/test_Results.py tests/unit/test_Validate.py README.md docs/Methodology.md docs/Runbook.md docs/Task_Authoring.md tasks/contract tasks/workflow
  git commit -m "docs: start the repaired harness testing series"
  ```

**Task done when:** The repaired verifier and task images have a new series tag, every frozen fixture digest agrees, changed-file routing stays surgical, and docs no longer describe the failed Claude seed path.

---

### Task 8: Review once, run the deterministic checkpoint once, and compile the smoke

**Files:**

- Review: every commit since `ecbd4b0c9fa0102492626e865c8e83dcf78de916`
- Potentially modify: only files already in Tasks 1–7 when a review finding proves a spec or correctness defect
- Generate locally/ignored: `arms/materialized/**`, `runs/generated/**`, `jobs/raw/**`, Docker images

**Interfaces:**

- Consumes: frozen reviewed implementation and the approved design acceptance criteria.
- Produces: one deterministic checkpoint receipt in command output, then one unexecuted four-session subscription manifest for `missing-rubric` across Claude/Codex A0/A2.
- The smoke uses pinned Studio Harness commit `ff8852e737a43a7e23f2cad423905f9361fde8ae`; changing that candidate requires a new plan rationale and naturally creates a different manifest digest.

- [ ] **Step 1: Perform one fresh-context review before the expensive checkpoint.**

  Use `superpowers:requesting-code-review` on the exact branch diff from the approved design commit:

  ```bash
  git diff --stat ecbd4b0c9fa0102492626e865c8e83dcf78de916...HEAD
  git diff --check ecbd4b0c9fa0102492626e865c8e83dcf78de916...HEAD
  ```

  The reviewer must check all 12 design acceptance criteria, especially protected-data exposure, Claude delegation scope, Codex inventory timing, A0 contamination, correctness-zero continuation, and old-series quarantine. Apply only proven findings and run only the affected focused tests for those fixes.

- [ ] **Step 2: Confirm the implementation contains no unfinished markers or stale seed path.**

  ```bash
  git diff --unified=0 ecbd4b0c9fa0102492626e865c8e83dcf78de916...HEAD -- . ':(exclude)docs/superpowers/**' | rg '^\+.*(TODO|FIXME|placeholder)' || true
  rg -n 'CLAUDE_CODE_PLUGIN_SEED_DIR|claude-plugin-seed|plugin-seed' src/harness_testing images
  git diff --check ecbd4b0c9fa0102492626e865c8e83dcf78de916...HEAD
  ```

  Expected: no unfinished marker or live Claude seed implementation remains. Historical wording is allowed only where the approved spec explains the invalid old cohort.

- [ ] **Step 3: Run the single final deterministic checkpoint in this order.**

  ```bash
  uv run harness-test validate --static-only
  uv run ruff check src tests
  uv run harness-test images build --node --rust --verifier
  uv run pytest -q tests/unit
  uv run harness-test task qa --task missing-rubric --case oracle
  uv run harness-test task qa --task missing-rubric --case nop
  uv run harness-test task qa --pack contract --all-cases
  uv run harness-test task qa --pack workflow --all-cases
  ```

  Expected: every command exits zero. Do not run dashboard tests because neither dashboard code nor `policy/Public_Result.schema.json` changed. Do not repeat the full checkpoint after individual successes; if a command fails, diagnose and repair the root cause, run the focused failing check, then rerun only the interrupted checkpoint command and the commands after it.

- [ ] **Step 4: Commit any review-only corrections and record the frozen implementation SHA.**

  ```bash
  git status --short
  git rev-parse HEAD
  ```

  Expected: the worktree is clean and the printed SHA is the immutable implementation target for the smoke review.

- [ ] **Step 5: Materialize the four smoke arms without starting a model.**

  ```bash
  uv run harness-test arm materialize --provider claude --arm A0
  uv run harness-test arm materialize --provider claude --arm A2 --harness-source https://github.com/Studio-Moser/skills-n-stuff.git --harness-commit ff8852e737a43a7e23f2cad423905f9361fde8ae
  uv run harness-test arm materialize --provider codex --arm A0
  uv run harness-test arm materialize --provider codex --arm A2 --harness-source https://github.com/Studio-Moser/skills-n-stuff.git --harness-commit ff8852e737a43a7e23f2cad423905f9361fde8ae
  ```

  Inspect each resulting `Provenance.json`: A0 has no delivery surfaces; A2 has exactly Studio Harness; Claude says `claude-plugin-dir`; Codex says `codex-plugin`; both paths exist in their immutable bundles.

- [ ] **Step 6: Compile the exact four-session smoke manifest.**

  ```bash
  uv run harness-test run plan \
    --profile smoke \
    --billing-mode subscription \
    --cell claude:A0:baseline \
    --cell claude:A2:candidate:ff8852e737a43a7e23f2cad423905f9361fde8ae \
    --cell codex:A0:baseline \
    --cell codex:A2:candidate:ff8852e737a43a7e23f2cad423905f9361fde8ae \
    --task missing-rubric \
    --max-sessions 4 \
    --max-budget-usd 0 \
    --attempts 1 \
    --concurrency 1 \
    --agent-timeout-seconds 1800
  ```

  Expected: the command starts no model, reports four sequential subscription sessions and `$0` incremental cost, binds both adapter digests and all arm/image/task inputs, and prints one content-addressed manifest digest.

- [ ] **Step 7: Stop and request explicit approval for the new digest.**

  Present the exact manifest path, SHA-256 approval digest, session order, provider/model/effort, timeout, candidate Harness commit, and API-equivalent estimate. Do not run `harness-test run execute` in this implementation plan.

**Task done when:** Deterministic review and QA pass once, the worktree is clean, and a new four-session smoke manifest is ready for a separate explicit execution approval. Harness quality conclusions remain deferred until that smoke's delivery and task evidence are inspected.

---

## Final spec-coverage audit

- [ ] AC1–AC4: public schema, protected boundary, shared scorer/stub bytes, nullable and empty-string behavior are covered by Tasks 1–2.
- [ ] AC5–AC8: Claude Harness/Superpowers delivery, Codex skills-only provenance, and A0 isolation are covered by Tasks 3–6.
- [ ] AC9–AC10: first-shard stop and correctness-zero continuation are covered by Task 6's model-free execution tests.
- [ ] AC11: the `0.2.0` compatibility split, no reviewed mapping, and explicit old-cohort quarantine are covered by Task 7 and review.
- [ ] AC12: targeted checks during implementation and one final checkpoint are enforced by the task commands above.
- [ ] No placeholder implementation, dashboard redesign, production Harness edit, Shelby adapter, new runner, or general plugin manager is present.
