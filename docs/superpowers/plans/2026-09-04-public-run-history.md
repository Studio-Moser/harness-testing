# Public Run History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish every recoverable public-safe Harness Testing run to a useful longitudinal dashboard while retaining a separate reviewed, decision-grade result lane.

**Architecture:** Version 2 run reports form a strict allowlisted summary shared by live execution and model-free historical backfill. The CLI batches validated reports onto a dedicated `dashboard-data` branch and invokes the existing default-branch Pages workflow once; the dashboard joins those reports with reviewed public results and computes deltas only within compatible series.

**Tech Stack:** Python 3.12, argparse, jsonschema Draft 2020-12, GitHub CLI, Git, GitHub Actions, GitHub Pages, Observable Framework 1.13.4, Observable Plot 0.6.17, Node 22 test runner.

**Spec:** [`docs/superpowers/specs/2026-09-04-public-run-history-design.md`](../specs/2026-09-04-public-run-history-design.md)

## Global Constraints

- Start no Claude, Codex, or other provider model session for this implementation or backfill.
- Read only generated manifests and top-level Harbor job summaries during backfill; never read prompts, trajectories, logs, workspaces, command output, or provider homes.
- Publish no credentials, environment variables, raw Harbor extras, local paths, or unknown fields.
- Preserve `result sanitize` as the separate reviewed/finalized decision-grade boundary.
- Plot every recoverable run, but calculate deltas only for equal non-null development series keys.
- Treat planned manifests without result artifacts as plans, not executed runs.
- Publish at most one data commit and one Pages workflow dispatch per terminal run or batch sync.
- Do not force-push or delete remote reports.
- Keep publication failure separate from benchmark outcome and retain a retryable local report.
- Add no hosted service, database, analytics SDK, or third-party reporting package.
- Use focused tests during Tasks 1–6 and run the complete deterministic checkpoint once in Task 7.

## Integration references

- [GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) requires the Pages artifact, `pages: write`, `id-token: write`, and the `github-pages` environment already used here.
- [GitHub manual workflow dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow) requires the workflow to exist on the default branch and supports `gh workflow run Publish_Pages.yml --repo Studio-Moser/harness-testing --ref main`.
- [actions/checkout multiple checkout guidance](https://github.com/actions/checkout/blob/main/README.md) supports a second checkout at an explicit `ref` and `path` beneath the workspace.
- [GitHub CLI API manual](https://cli.github.com/manual/gh_api) confirms authenticated request bodies can use standard input; this implementation instead keeps report content out of command arguments by publishing through a temporary Git checkout.

---

### Task 1: Canonical public-safety checks and run-report schema v2

**Files:**
- Create: `src/harness_testing/Public_Safety.py`
- Modify: `src/harness_testing/Results.py`
- Modify: `src/harness_testing/Run_Reports.py`
- Modify: `policy/Run_Report.schema.json`
- Modify: `tests/Fixtures/Run_Reports/Valid.json`
- Create: `tests/Fixtures/Run_Reports/Legacy_V1.json`
- Create: `tests/unit/test_Public_Safety.py`
- Modify: `tests/unit/test_Results.py`
- Modify: `tests/unit/test_Runs.py`

**Interfaces:**
- Produces: `public_safety_errors(value: object, path: str = "$") -> tuple[str, ...]`.
- Produces: `run_report_id(document: Mapping[str, object]) -> str`.
- Produces: `validate_run_report(root: Path, document: object, *, published: bool = False) -> tuple[str, ...]`.
- Produces: `load_run_report(root: Path, path: Path, *, published: bool = False) -> dict[str, object]`.
- Consumed by: live report generation, historical backfill, publisher, and dashboard fixtures.

- [ ] **Step 1: Add failing shared-safety and v2 identity tests.**

Add tests that prove public results retain their current sensitive-value rejection and that reports reject private keys, local paths, secret-shaped values, unknown fields, a mismatched content identity, and schema version 1 when `published=True`:

```python
def test_public_safety_rejects_private_keys_and_values():
    assert public_safety_errors({"prompt": "private"}) == (
        "forbidden public field: $.prompt",
    )
    assert public_safety_errors({"model": "/Users/example/model"}) == (
        "sensitive or local-only string: $.model",
    )


def test_published_run_report_requires_v2_and_content_identity(run_root: Path):
    report = json.loads((FIXTURES / "Run_Reports" / "Valid.json").read_text())
    assert validate_run_report(run_root, report, published=True) == ()
    report["report_id"] = f"sha256:{'0' * 64}"
    assert "identity does not match" in "; ".join(
        validate_run_report(run_root, report, published=True)
    )


def test_v1_run_report_is_local_only(run_root: Path):
    report = json.loads((FIXTURES / "Run_Reports" / "Legacy_V1.json").read_text())
    assert any("version 1" in error for error in validate_run_report(
        run_root, report, published=True
    ))
```

- [ ] **Step 2: Run only those tests and verify RED.**

Run:

```bash
uv run pytest -q \
  tests/unit/test_Public_Safety.py \
  tests/unit/test_Results.py \
  tests/unit/test_Runs.py \
  -k 'public_safety or published_run_report or v1_run_report'
```

Expected: collection or assertion failures because the shared module and v2 validation do not exist.

- [ ] **Step 3: Extract the existing public-value scanner without changing public-result behavior.**

Move the sensitive-key, private-field, local-path, and secret-value patterns from `Results.py` into `Public_Safety.py` and expose an immutable tuple:

```python
def public_safety_errors(value: object, path: str = "$") -> tuple[str, ...]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-zA-Z0-9]+", "_", str(key)).strip("_").lower()
            child_path = f"{path}.{key}"
            if normalized in _PRIVATE_FIELDS or _SENSITIVE_KEY.search(normalized):
                errors.append(f"forbidden public field: {child_path}")
            errors.extend(public_safety_errors(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(public_safety_errors(child, f"{path}[{index}]"))
    elif isinstance(value, str) and (
        _LOCAL_PATH.search(value) or _SECRET_VALUE.search(value)
    ):
        errors.append(f"sensitive or local-only string: {path}")
    return tuple(errors)
```

Replace `Results._sensitive_errors(document)` with `list(public_safety_errors(document))`. Keep all existing message text stable.

- [ ] **Step 4: Replace the run-report fixture and schema with exact v2 semantics.**

Retain the existing job measurements and add these required report fields:

```json
{
  "schema_version": "2",
  "report_id": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
  "manifest_schema_version": "0.3.0",
  "source": {
    "kind": "current",
    "label": null
  },
  "evidence": {
    "review_state": "unreviewed",
    "limitations": []
  },
  "admission_estimate_usd": 1.25,
  "observed_api_equivalent_cost_usd": 0.01
}
```

After assembling the fixture, replace the illustrative `report_id` above with
the value returned by `run_report_id(document)` so the committed fixture has a
valid content identity.

Use exact enums:

```text
source.kind: current | identified-historical | legacy-historical
evidence.review_state: unreviewed | reviewed | quarantined
evidence.limitations: partial-run | failed-run | obsolete-methodology |
                      legacy-run-identity | missing-provenance |
                      infrastructure-failure
job.comparability: comparable | diagnostic-only
job.series_key_unavailable_reason: missing-provenance |
                                   incompatible-methodology | null
```

Each job requires `agent`, `agent_version`, `task_pack`, `task_digest`,
`comparability`, nullable `series_key`, and nullable
`series_key_unavailable_reason`. Make both top-level cost fields nullable
non-negative numbers. Keep `additionalProperties: false` at every object.

- [ ] **Step 5: Implement report identity and validation.**

Use canonical compact JSON and validate safety, schema, and identity in that order:

```python
def run_report_id(document: Mapping[str, object]) -> str:
    unsigned = dict(document)
    unsigned.pop("report_id", None)
    payload = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def validate_run_report(
    root: Path,
    document: object,
    *,
    published: bool = False,
) -> tuple[str, ...]:
    errors = list(public_safety_errors(document))
    errors.extend(_run_report_schema_errors(root, document))
    if published and isinstance(document, Mapping) and document.get("schema_version") != "2":
        errors.append("published run report requires schema version 2")
    if isinstance(document, Mapping) and document.get("schema_version") == "2":
        if document.get("report_id") != run_report_id(document):
            errors.append("run report identity does not match its content")
    return tuple(dict.fromkeys(errors))
```

`load_run_report` reads one JSON object and raises one `ValueError` containing the joined validation errors.

- [ ] **Step 6: Run focused tests and commit.**

Run:

```bash
uv run ruff check \
  src/harness_testing/Public_Safety.py \
  src/harness_testing/Results.py \
  src/harness_testing/Run_Reports.py \
  tests/unit/test_Public_Safety.py \
  tests/unit/test_Results.py \
  tests/unit/test_Runs.py
uv run pytest -q \
  tests/unit/test_Public_Safety.py \
  tests/unit/test_Results.py \
  tests/unit/test_Runs.py \
  -k 'public_safety or sensitive or run_report'
```

Expected: PASS with no change to existing public-result safety assertions.

Commit:

```bash
git add \
  policy/Run_Report.schema.json \
  src/harness_testing/Public_Safety.py \
  src/harness_testing/Results.py \
  src/harness_testing/Run_Reports.py \
  tests/Fixtures/Run_Reports \
  tests/unit/test_Public_Safety.py \
  tests/unit/test_Results.py \
  tests/unit/test_Runs.py
git commit -m "feat: define public run report history"
```

---

### Task 2: Generate v2 reports and bind publication to approved manifests

**Files:**
- Create: `policy/Dashboard_Publication.toml`
- Create: `src/harness_testing/Report_Publication.py`
- Modify: `src/harness_testing/Runs.py`
- Modify: `src/harness_testing/Run_Reports.py`
- Modify: `src/harness_testing/CLI.py`
- Create: `tests/unit/test_Report_Publication.py`
- Modify: `tests/unit/test_Runs.py`
- Modify: `tests/unit/test_Validate.py`

**Interfaces:**
- Produces: immutable `PublicationTarget(repository, data_branch, workflow, code_ref)`.
- Produces: `load_publication_target(root: Path) -> PublicationTarget`.
- Produces: `publication_manifest_record(target: PublicationTarget) -> dict[str, str]`.
- Changes: `plan_run` accepts `publish_report: bool = True` and returns `RunManifest`.
- Changes: `write_run_report` writes schema version 2 and returns its path.
- Consumed by: publisher and execution in Task 4.

- [ ] **Step 1: Add failing publication-policy and manifest tests.**

```python
def test_new_manifest_binds_public_report_destination(run_root: Path):
    manifest = _compile_pair(run_root)
    assert manifest.provenance["report_publication"] == {
        "mode": "public",
        "repository": "Studio-Moser/harness-testing",
        "data_branch": "dashboard-data",
        "workflow": "Publish_Pages.yml",
        "code_ref": "main",
    }
    assert "Public run report: Studio-Moser/harness-testing" in format_plan(manifest)


def test_local_only_manifest_is_explicit_and_content_addressed(run_root: Path):
    public = _compile_pair(run_root)
    local = _compile_pair(run_root, publish_report=False)
    assert local.provenance["report_publication"] == {"mode": "local-only"}
    assert local.digest != public.digest
    assert local.provenance["run_id"] != public.provenance["run_id"]


def test_v2_report_separates_estimate_from_observed_cost(run_root: Path):
    manifest = _compile_pair(run_root)
    _write_completed_jobs(run_root, manifest)
    report = json.loads(write_run_report(run_root, manifest, "completed").read_text())
    assert report["admission_estimate_usd"] == float(manifest.api_equivalent_cost_usd)
    assert report["observed_api_equivalent_cost_usd"] == 0.04
    assert report["report_id"] == run_report_id(report)
```

- [ ] **Step 2: Run the selected tests and verify RED.**

```bash
uv run pytest -q tests/unit/test_Runs.py tests/unit/test_Report_Publication.py \
  -k 'publication or separates_estimate'
```

Expected: FAIL because the tracked policy, manifest record, local-only option, and v2 generator do not exist.

- [ ] **Step 3: Add and parse the fixed publication policy.**

Create:

```toml
[public_reports]
repository = "Studio-Moser/harness-testing"
data_branch = "dashboard-data"
workflow = "Publish_Pages.yml"
code_ref = "main"
```

`load_publication_target` must reject missing keys, extra keys, an invalid `OWNER/REPO`, branch names containing whitespace or `..`, a workflow name outside `.github/workflows`, and a code ref other than `main`. Do not read a destination from `origin` or environment variables.

- [ ] **Step 4: Add publication mode to run identity and provenance.**

In `compile_run`, select one exact record before constructing `run_identity`:

```python
publication = (
    publication_manifest_record(load_publication_target(root))
    if publish_report
    else {"mode": "local-only"}
)
run_identity["report_publication"] = publication
provenance["report_publication"] = publication
```

In `_verify_generated_inputs`, accept old manifests with no publication record as local-only. For new records, require exact equality with the tracked policy. Add `--local-report-only` to `harness-test run plan`, pass `publish_report=not arguments.local_report_only`, and print the exact destination or `local-only` in `format_plan`.

- [ ] **Step 5: Generate complete v2 report metadata.**

Build the per-job development series input from known manifest data and exclude the tested Harness commit because it is the independent variable:

```python
series_inputs = {
    "manifest_schema_version": manifest.schema_version,
    "provider": cell.provider,
    "agent": job.agents[0].import_path,
    "agent_version": job.agents[0].kwargs["version"],
    "model": cell.model,
    "effort": cell.effort,
    "arm": cell.arm,
    "role": cell.role,
    "skill_evaluation": (
        manifest.skill_evaluation.to_dict()
        if manifest.skill_evaluation is not None
        else None
    ),
    "task_digest": task_digest,
    "image_input_digests": manifest.provenance["image_input_digests"],
    "agent_adapter_digest": manifest.provenance["agent_adapter_digests"][cell.provider],
}
```

Hash canonical `series_inputs` for a non-null job `series_key`. Set current reports to `source.kind=current`, `review_state=unreviewed`, and derive `partial-run`, `failed-run`, or `infrastructure-failure` only from observed completion/error counts. Sum measured per-job cost into `observed_api_equivalent_cost_usd`; use `null` when every job lacks cost telemetry.

- [ ] **Step 6: Route the new files to focused validation.**

Update `affected_validation_commands` so changes to `Report_Publication.py`, `Dashboard_Publication.toml`, run-report fixtures, or the run-report schema run only Ruff for changed Python, `test_Runs.py`, `test_Report_Publication.py`, `test_Validate.py`, and dashboard test/build. Do not route these files to image builds or task QA.

- [ ] **Step 7: Run focused checks and commit.**

```bash
uv run ruff check \
  src/harness_testing/CLI.py \
  src/harness_testing/Report_Publication.py \
  src/harness_testing/Run_Reports.py \
  src/harness_testing/Runs.py \
  src/harness_testing/Validate.py \
  tests/unit/test_Report_Publication.py \
  tests/unit/test_Runs.py \
  tests/unit/test_Validate.py
uv run pytest -q \
  tests/unit/test_Report_Publication.py \
  tests/unit/test_Runs.py \
  tests/unit/test_Validate.py \
  -k 'publication or run_report or affected_validation'
```

Expected: PASS.

```bash
git add \
  policy/Dashboard_Publication.toml \
  src/harness_testing/CLI.py \
  src/harness_testing/Report_Publication.py \
  src/harness_testing/Run_Reports.py \
  src/harness_testing/Runs.py \
  src/harness_testing/Validate.py \
  tests/unit/test_Report_Publication.py \
  tests/unit/test_Runs.py \
  tests/unit/test_Validate.py
git commit -m "feat: bind run report publication"
```

---

### Task 3: Model-free historical backfill

**Files:**
- Create: `src/harness_testing/Run_History.py`
- Create: `runs/Historical_Backfill.toml`
- Modify: `src/harness_testing/CLI.py`
- Create: `tests/Fixtures/Run_History/Identified_Manifest.json`
- Create: `tests/Fixtures/Run_History/Identified_Result.json`
- Create: `tests/Fixtures/Run_History/Legacy_Mapping.toml`
- Create: `tests/unit/test_Run_History.py`
- Modify: `.gitignore`
- Modify: `src/harness_testing/Validate.py`
- Modify: `tests/unit/test_Validate.py`

**Interfaces:**
- Produces: immutable `LegacyRunMapping(label, manifest_digest, jobs_subdirectory, expected_jobs, review_state, limitations)`.
- Produces: `backfill_run_reports(root: Path, source_roots: tuple[Path, ...], mapping_path: Path, output_directory: Path) -> tuple[Path, ...]`.
- Produces CLI: repeatable `harness-test report backfill --source-root PATH --mapping PATH --output PATH`.
- Consumed by: report sync and the one-time rollout.

- [ ] **Step 1: Add failing identified and legacy backfill tests.**

```python
def test_backfill_groups_identified_jobs_without_reading_trials(history_root: Path):
    paths = backfill_run_reports(
        history_root,
        (history_root / "archive",),
        history_root / "Empty_Mapping.toml",
        history_root / "runs" / "history",
    )
    assert [path.name for path in paths] == ["run-11111111111111111111.json"]
    report = load_run_report(history_root, paths[0], published=True)
    assert report["source"]["kind"] == "identified-historical"
    assert len(report["jobs"]) == 2


def test_backfill_requires_exact_legacy_count(history_root: Path):
    with pytest.raises(ValueError, match="expected 2 jobs, found 1"):
        backfill_run_reports(
            history_root,
            (history_root / "archive",),
            history_root / "Legacy_Mapping.toml",
            history_root / "runs" / "history",
        )


def test_backfill_never_opens_trial_artifacts(history_root: Path, monkeypatch):
    real_read = Path.read_text
    def guarded_read(path: Path, *args, **kwargs):
        assert "trajectory" not in path.name.lower()
        assert "trial.log" not in path.name
        return real_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", guarded_read)
    backfill_run_reports(
        history_root,
        (history_root / "archive",),
        history_root / "Empty_Mapping.toml",
        history_root / "runs" / "history",
    )
```

- [ ] **Step 2: Run the new module and verify RED.**

```bash
uv run pytest -q tests/unit/test_Run_History.py
```

Expected: collection failure because `Run_History.py` does not exist.

- [ ] **Step 3: Implement fail-closed manifest/job matching.**

For identified runs:

1. Verify each manifest's recorded content digest with `verify_manifest_document`.
2. Read `provenance.run_id` only when it matches `^run-[0-9a-f]{20}$`.
3. Match only direct `jobs/raw/<run-id>-*/result.json` files.
4. Match each job name to exactly one generated Harbor config from that manifest.
5. Emit nothing for a manifest with zero matching result files.
6. Reject a non-empty partial match only when job identities are ambiguous; otherwise emit a partial report with exact expected/completed counts.

Set `review_state=quarantined` and add `obsolete-methodology` whenever a
historical manifest schema differs from the current repository schema. Keep
current-schema history `unreviewed` unless an explicit legacy mapping says
otherwise. Derive `partial-run`, `failed-run`, and `infrastructure-failure`
strictly from counts and exceptions in the top-level job summaries.

For legacy mappings, resolve the manifest digest beneath one supplied source root, load only the configured jobs subdirectory, match exactly the manifest's generated job names, and enforce `expected_jobs`. Construct a stable legacy run ID from the manifest digest plus mapping label:

```python
legacy_run_id = "run-" + hashlib.sha256(
    f"{mapping.manifest_digest}\0{mapping.label}".encode()
).hexdigest()[:20]
```

Use the same allowlisted job builder and series-key builder as live reports. Unknown old agent or provenance fields yield `diagnostic-only` with `missing-provenance`; they are never guessed.

- [ ] **Step 4: Add the two explicit historical mappings.**

```toml
[[legacy]]
label = "archived-smoke-2026-08-28"
manifest_digest = "sha256:8a5439fddef1e8c677a6a0330a18ccb987232e8d81427eacf029c93a798e96ac"
jobs_subdirectory = "Archived_Smoke-2026-08-28"
expected_jobs = 2
review_state = "quarantined"
limitations = ["obsolete-methodology", "legacy-run-identity"]

[[legacy]]
label = "pre-run-id-release-2026-08-29"
manifest_digest = "sha256:0bd5b98a55200465b9d7bd77bee10e00bf4b3dd18775e1d95e2c5820179cc714"
jobs_subdirectory = "."
expected_jobs = 34
review_state = "quarantined"
limitations = ["obsolete-methodology", "legacy-run-identity"]
```

Ignore generated `runs/history/` while keeping `runs/Historical_Backfill.toml` tracked.

- [ ] **Step 5: Add the report CLI and focused validation route.**

Add `report` subcommands without overloading `result`:

```text
harness-test report backfill --source-root PATH [--source-root SECOND_PATH]
                             --mapping runs/Historical_Backfill.toml
                             --output runs/history
```

Reject duplicate source roots and an output path outside the current repository's ignored `runs/history/` directory. Print one line per report plus final report/job counts.

- [ ] **Step 6: Run focused checks and commit.**

```bash
uv run ruff check \
  src/harness_testing/CLI.py \
  src/harness_testing/Run_History.py \
  src/harness_testing/Validate.py \
  tests/unit/test_Run_History.py \
  tests/unit/test_Validate.py
uv run pytest -q tests/unit/test_Run_History.py tests/unit/test_Validate.py \
  -k 'backfill or run_history or affected_validation'
```

Expected: PASS.

```bash
git add \
  .gitignore \
  runs/Historical_Backfill.toml \
  src/harness_testing/CLI.py \
  src/harness_testing/Run_History.py \
  src/harness_testing/Validate.py \
  tests/Fixtures/Run_History \
  tests/unit/test_Run_History.py \
  tests/unit/test_Validate.py
git commit -m "feat: backfill historical run reports"
```

---

### Task 4: Batched data-branch publication and retryable sync

**Files:**
- Modify: `src/harness_testing/Report_Publication.py`
- Modify: `src/harness_testing/Run_Reports.py`
- Modify: `src/harness_testing/Runs.py`
- Modify: `src/harness_testing/CLI.py`
- Modify: `tests/unit/test_Report_Publication.py`
- Modify: `tests/unit/test_Runs.py`

**Interfaces:**
- Produces: immutable `PublicationReceipt(report_id, repository, branch, commit)`.
- Produces: `pending_run_reports(root: Path) -> tuple[Path, ...]`.
- Produces: `publish_run_reports(root: Path, report_paths: tuple[Path, ...], target: PublicationTarget, *, runner=subprocess.run) -> tuple[PublicationReceipt, ...]`.
- Produces: `sync_pending_reports(root: Path, target: PublicationTarget, *, runner=subprocess.run) -> tuple[PublicationReceipt, ...]`.
- Produces CLI: `harness-test report sync`.
- Consumed by: `execute_run` after completion and handled failure.

- [ ] **Step 1: Add failing publisher tests with a temporary remote.**

```python
def test_publish_batches_reports_without_dirtying_caller(tmp_path: Path):
    caller, remote = initialized_repositories(tmp_path)
    report_paths = write_valid_reports(caller, 2)
    before = git(caller, "status", "--porcelain")
    receipts = publish_run_reports(
        caller,
        report_paths,
        TEST_TARGET,
        runner=recording_runner(remote),
    )
    assert len(receipts) == 2
    assert git(caller, "status", "--porcelain") == before
    assert commit_count(remote, "dashboard-data") == 2  # bootstrap + one batch
    assert workflow_dispatches() == [("Publish_Pages.yml", "main")]


def test_older_report_cannot_replace_newer_remote_report(tmp_path: Path):
    caller, remote = initialized_repositories(tmp_path)
    newer, older = write_newer_and_older_reports(caller)
    publish_run_reports(
        caller, (newer,), TEST_TARGET, runner=recording_runner(remote)
    )
    with pytest.raises(ValueError, match="older than published report"):
        publish_run_reports(
            caller, (older,), TEST_TARGET, runner=recording_runner(remote)
        )


def test_failed_publish_leaves_report_pending(tmp_path: Path):
    caller, remote = initialized_repositories(tmp_path)
    expected_report_path = write_valid_reports(caller, 1)[0]
    with pytest.raises(ValueError, match="could not publish"):
        publish_run_reports(
            caller,
            (expected_report_path,),
            TEST_TARGET,
            runner=failing_push_runner(remote),
        )
    assert pending_run_reports(caller) == (expected_report_path,)
```

- [ ] **Step 2: Run publication tests and verify RED.**

```bash
uv run pytest -q tests/unit/test_Report_Publication.py -k 'publish or pending'
```

Expected: FAIL because publication and receipt handling are absent.

- [ ] **Step 3: Implement one temporary-checkout batch.**

The publisher must execute this logical sequence with tuple arguments and no shell:

```python
commands = (
    ("gh", "auth", "status", "--hostname", "github.com"),
    (
        "gh", "repo", "clone", target.repository, str(checkout), "--",
        "--branch", target.data_branch, "--single-branch", "--depth", "1",
    ),
    ("git", "-C", str(checkout), "add", "reports"),
    (
        "git", "-C", str(checkout),
        "-c", "user.name=Studio Moser Harness Testing",
        "-c", "user.email=harness-testing@users.noreply.github.com",
        "commit", "-m", commit_message,
    ),
    ("git", "-C", str(checkout), "push", "origin", target.data_branch),
    (
        "gh", "workflow", "run", target.workflow,
        "--repo", target.repository, "--ref", target.code_ref,
    ),
)
```

Before copying, validate each report with `published=True`. Read a remote report
only at `reports/<run_id>.json`; reject a different run identity, reject an older
`updated_at`, skip identical `report_id`, and overwrite only with a newer report.
Use `TemporaryDirectory`, `shutil.copyfile`, and `os.replace` where local atomic
writes are needed. Capture subprocess output and never place it in a raised
error because authentication helpers can emit sensitive context.

If the push reports a non-fast-forward conflict, discard the temporary clone,
clone the data branch once more, repeat validation and monotonic timestamp
checks, and retry one ordinary push. A second conflict fails locally; never use
`--force` or `--force-with-lease`.

- [ ] **Step 4: Record local receipts and implement pending detection.**

Write ignored `Run_Report.Publication.json` beside each source report only after
push succeeds. It contains exactly:

```json
{
  "schema_version": "1",
  "report_id": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
  "repository": "Studio-Moser/harness-testing",
  "branch": "dashboard-data",
  "commit": "2222222222222222222222222222222222222222"
}
```

A missing receipt, mismatched report ID, or mismatched destination makes the
report pending. Scan both `runs/generated/*/Run_Report.json` and
`runs/history/*.json`, sort deterministically, and batch all pending paths.

- [ ] **Step 5: Integrate best-effort terminal publication.**

After calling `write_run_report` with status `completed` or `failed`, inspect
the approved manifest publication
record. For `mode=public`, call sync once. Catch publication errors separately:

```python
try:
    receipts = sync_pending_reports(root, target)
except ValueError as publication_error:
    print(
        "Public dashboard update pending; retry with "
        f"`uv run harness-test report sync`: {publication_error}",
        file=sys.stderr,
    )
else:
    if receipts:
        print(f"Published {len(receipts)} run report(s) to {target.repository}")
```

Do not replace, suppress, or reclassify the original execution exception. Add
`harness-test report sync` to CLI and make it load only the tracked target.

- [ ] **Step 6: Run focused checks and commit.**

```bash
uv run ruff check \
  src/harness_testing/CLI.py \
  src/harness_testing/Report_Publication.py \
  src/harness_testing/Runs.py \
  tests/unit/test_Report_Publication.py \
  tests/unit/test_Runs.py
uv run pytest -q tests/unit/test_Report_Publication.py tests/unit/test_Runs.py \
  -k 'publish or pending or execution_updates'
```

Expected: PASS; no command contacts GitHub because tests use temporary remotes and fakes.

```bash
git add \
  src/harness_testing/CLI.py \
  src/harness_testing/Report_Publication.py \
  src/harness_testing/Run_Reports.py \
  src/harness_testing/Runs.py \
  tests/unit/test_Report_Publication.py \
  tests/unit/test_Runs.py
git commit -m "feat: publish run reports once"
```

---

### Task 5: Join the data branch in Pages and the dashboard loader

**Files:**
- Modify: `.github/workflows/Publish_Pages.yml`
- Modify: `dashboard/src/data/Public_Results.json.js`
- Modify: `dashboard/test/Public_Results.test.js`
- Modify: `tests/unit/test_Validate.py`

**Interfaces:**
- Changes loader output to `{schema_version, results, run_reports, local_runs, compatibility_series}`.
- Consumes `HARNESS_PUBLISHED_REPORTS_DIRECTORY` during Pages builds.
- Preserves local `runs/generated/*/Run_Report.json` discovery for local builds.
- Consumed by: all dashboard pages and `Run_History.js` in Task 6.

- [ ] **Step 1: Add failing published-report loader tests.**

```javascript
test("loads data-branch reports and deduplicates local copies", async () => {
  const root = await testRoot();
  await cp(validV2, resolve(root, "published", "run-a.json"));
  await cp(validV2, resolve(root, "runs", "generated", digest, "Run_Report.json"));
  const report = await loadFrom(root);
  assert.equal(report.run_reports.length, 1);
  assert.equal(report.local_runs.length, 1);
});

test("rejects malformed published reports", async () => {
  const root = await testRoot();
  await writeFile(resolve(root, "published", "Bad.json"), "{}\n");
  await assert.rejects(loadFrom(root), /published run report schema validation failed/);
});
```

- [ ] **Step 2: Run the dashboard loader test and verify RED.**

```bash
npm --prefix dashboard test -- --test-name-pattern='data-branch|published reports'
```

Expected: FAIL because the loader has no published report directory or `run_reports` output.

- [ ] **Step 3: Implement published/local report loading and deterministic dedupe.**

Extend `loadPublicResults` with:

```javascript
publishedReportsDirectory = process.env.HARNESS_PUBLISHED_REPORTS_DIRECTORY
  ?? resolve(repositoryRoot, "dashboard-data", "reports")
```

Published reports are direct `*.json` files and must validate as schema version
2 plus matching `report_id`. Local reports retain their manifest-directory
check. Sort by `finished_at ?? updated_at`, then `run_id`, then `report_id`.
Deduplicate the combined `run_reports` by run ID, preferring a newer
`updated_at`; reject equal timestamps with different identities.

Keep `local_runs` as local-only UI state. Return all published reports plus any
newer local report in `run_reports`, so a local dashboard sees the latest run
without losing published history.

- [ ] **Step 4: Update Pages to check out main plus dashboard data.**

Keep the existing pinned action SHAs. Change the first checkout to `path: source`
and add a second checkout of the same repository:

```yaml
      - name: Check out dashboard code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803
        with:
          ref: main
          path: source
          persist-credentials: false

      - name: Check out published run reports
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803
        with:
          ref: dashboard-data
          path: dashboard-data
          sparse-checkout: reports
          persist-credentials: false
```

Run Node setup, install, and build with `working-directory: source`. Set:

```yaml
        env:
          HARNESS_PUBLISHED_REPORTS_DIRECTORY: ${{ github.workspace }}/dashboard-data/reports
```

Upload `source/dashboard/dist`. Retain `workflow_dispatch`, Pages permissions,
the `github-pages` environment, and `concurrency: pages`. Add the run-report
schema and workflow itself to main-push paths.

- [ ] **Step 5: Add static workflow assertions and run focused checks.**

Assert the parsed workflow has `workflow_dispatch`, two pinned checkout steps,
the exact data ref/path, the report-directory environment variable, and no
provider credentials or live model command.

```bash
npm --prefix dashboard test
uv run pytest -q tests/unit/test_Validate.py -k 'pages or workflow'
uv run harness-test validate --static-only
```

Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add \
  .github/workflows/Publish_Pages.yml \
  dashboard/src/data/Public_Results.json.js \
  dashboard/test/Public_Results.test.js \
  tests/unit/test_Validate.py
git commit -m "feat: load published run history"
```

---

### Task 6: Make longitudinal run history the dashboard default

**Files:**
- Create: `dashboard/src/components/Run_History.js`
- Create: `dashboard/test/Run_History.test.js`
- Modify: `dashboard/src/index.md`
- Modify: `dashboard/src/Trends.md`
- Modify: `dashboard/src/Comparisons.md`
- Modify: `dashboard/src/Task_Matrix.md`
- Modify: `dashboard/src/Run_Detail.md`
- Modify: `dashboard/src/Quality_Versus_Efficiency.md`
- Modify: `dashboard/test/Public_Results.test.js`

**Interfaces:**
- Produces: `runObservations(runReports, finalizedResults) -> Observation[]`.
- Produces: `pairedArmComparisons(observations) -> Pair[]`.
- Produces: `seriesDeltas(observations) -> Delta[]`.
- Produces: `latestRun(runReports) -> RunReport | null`.
- Produces: formatting helpers for evidence, completion, observed cost, and series availability.
- Consumed by: all six dashboard pages.

- [ ] **Step 1: Load the Impeccable frontend instructions before editing UI.**

Read the available `impeccable` skill completely, run its project-context
script if supplied, and apply only guidance relevant to this existing
Observable dashboard. Record no generated design artifact and add no UI
dependency.

- [ ] **Step 2: Add failing normalization and comparison tests.**

```javascript
test("normalizes every run job without double-counting finalized evidence", () => {
  const observations = runObservations([report], [matchingFinalizedResult]);
  assert.equal(observations.length, report.jobs.length);
  assert.equal(observations[0].reviewState, "reviewed");
  assert.equal(observations[0].releaseDecision, "pass");
});

test("only computes deltas inside one non-null series", () => {
  assert.equal(seriesDeltas([first, {...second, seriesKey: null}]).length, 0);
  assert.equal(seriesDeltas([first, {...second, seriesKey: "sha256:other"}]).length, 0);
  assert.equal(seriesDeltas([first, second]).length, 1);
});

test("pairs A0 and A2 only within the same run provider and task", () => {
  assert.deepEqual(pairedArmComparisons(observations), [expectedPair]);
});
```

- [ ] **Step 3: Run helper tests and verify RED.**

```bash
npm --prefix dashboard test -- --test-name-pattern='normalizes|deltas|pairs A0'
```

Expected: FAIL because `Run_History.js` does not exist.

- [ ] **Step 4: Implement one normalized observation shape.**

Each job becomes:

```javascript
{
  observationId: `${report.run_id}\0${job.name}`,
  reportId: report.report_id,
  runId: report.run_id,
  manifestDigest: report.manifest_digest,
  manifestSchema: report.manifest_schema_version,
  profile: report.profile,
  runStatus: report.status,
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
  jobStatus: job.status,
  dimensions: job.dimensions,
  runtimeSeconds: job.runtime_seconds,
  promptTokens: job.efficiency.prompt_tokens,
  cachedTokens: job.efficiency.cached_tokens,
  completionTokens: job.efficiency.completion_tokens,
  observedCost: job.efficiency.api_equivalent_cost_usd,
  sourceKind: report.source.kind,
  reviewState: report.evidence.review_state,
  limitations: report.evidence.limitations,
  comparability: job.comparability,
  seriesKey: job.series_key,
  releaseDecision: null
}
```

Match decision-grade results by manifest digest, provider, arm, and task. Enrich
the aggregate observation with review/release state; do not append a duplicate.
If a finalized result has no report observation, synthesize one so the strict
lane remains complete.

- [ ] **Step 5: Replace the empty landing state with history status.**

The first viewport must show:

- recoverable run count;
- job observation count;
- latest run status and finish time;
- evidence counts for reviewed, unreviewed, quarantined, partial, and failed;
- the latest run's jobs with three scores, runtime, tokens, and observed cost;
- a note separating observed API-equivalent usage, admission estimate, and
  incremental subscription spend.

When history is empty, state exactly that no public-safe run reports have been
published; do not claim the next local run is already present on Pages.

- [ ] **Step 6: Convert all five analytical pages to run observations.**

- `Trends.md`: use point marks for every observation; connect only equal
  non-null series keys; expose provider, arm, task, profile, methodology, and
  review-state filters.
- `Comparisons.md`: show within-run A0/A2 pairs first, then equal-series
  cross-run deltas; label every diagnostic-only row.
- `Task_Matrix.md`: include missing/failed cells and evidence status alongside
  scores and telemetry.
- `Run_Detail.md`: select a run report, show all jobs and limitations, then show
  any linked decision-grade results.
- `Quality_Versus_Efficiency.md`: plot all correct observations with symbol or
  opacity for reviewed/comparable/diagnostic evidence; do not filter the page to
  finalized results.

All filters must retain a useful all-values default. Use text labels in addition
to color for evidence state and preserve explicit `Unavailable` values.

- [ ] **Step 7: Run dashboard tests and production build.**

```bash
npm --prefix dashboard test
npm --prefix dashboard run build
```

Expected: every dashboard test passes and all six HTML pages build without an
Observable runtime error.

- [ ] **Step 8: Run one browser hardening pass and commit.**

Serve `dashboard/dist` locally, inspect all six pages at desktop width and the
landing/trends pages at a narrow mobile width, exercise every filter, and check
the browser console. Fix only observed accessibility, overflow, empty-state, or
runtime defects and rerun the dashboard test/build once if code changes.

```bash
git add \
  dashboard/src/components/Run_History.js \
  dashboard/src/index.md \
  dashboard/src/Trends.md \
  dashboard/src/Comparisons.md \
  dashboard/src/Task_Matrix.md \
  dashboard/src/Run_Detail.md \
  dashboard/src/Quality_Versus_Efficiency.md \
  dashboard/test/Public_Results.test.js \
  dashboard/test/Run_History.test.js
git commit -m "feat: show harness progress over time"
```

---

### Task 7: Backfill, review, checkpoint, merge, and publish

**Files:**
- Modify: `README.md`
- Modify: `docs/Runbook.md`
- Modify: `docs/Methodology.md`
- Modify: `docs/superpowers/plans/2026-09-04-public-run-history.md`
- Data branch only: `README.md`
- Data branch only: `reports/*.json`

**Interfaces:**
- Consumes all Tasks 1–6.
- Produces the live 21-cohort/182-job public dashboard and the documented future workflow.

- [ ] **Step 1: Document the two lanes and exact commands.**

State that development history is public-safe but not automatically
decision-grade. Document:

```bash
uv run harness-test report backfill \
  --source-root "$HARNESS_HISTORY_ARCHIVE_ROOT" \
  --source-root "$PWD" \
  --mapping runs/Historical_Backfill.toml \
  --output runs/history

uv run harness-test report sync
```

Document one publish per terminal run, retry behavior, `dashboard-data`, equal
series-key comparisons, and the strict unchanged `result sanitize` path.

- [ ] **Step 2: Generate the real model-free historical reports.**

From the current feature worktree, run with the existing archive checkout and
current worktree as sources:

```bash
uv run harness-test report backfill \
  --source-root "/Users/timmoser/Projects/Studio Moser Internal/Harness Testing" \
  --source-root "/Users/timmoser/Projects/Studio Moser Internal/Harness Testing/.worktrees/harness-testing-current-main" \
  --mapping runs/Historical_Backfill.toml \
  --output runs/history
```

Expected: exactly 21 reports and 182 job summaries. Validate every file as
published v2, scan it for local paths and secret-shaped strings, and confirm no
raw file is staged.

- [ ] **Step 3: Run focused affected validation once after documentation settles.**

```bash
uv run harness-test validate --changed-from 9d16059
```

Expected: only the affected Python unit modules plus dashboard install/test/build;
no task image build, task QA pack, or provider session.

- [ ] **Step 4: Obtain one independent review of the frozen feature diff.**

Freeze the target commit, use the repository's configured Harness review route,
and ask specifically about data leakage, incorrect historical grouping,
comparability leakage, Git worktree mutation, unsafe pushes, and duplicate
dashboard observations. Apply only evidenced findings with their focused test,
then freeze and review once more only if code changed.

- [ ] **Step 5: Run the one complete deterministic checkpoint.**

Run each command once after all review fixes settle:

```bash
uv run ruff check src tests
uv run pytest tests/unit -q
npm ci --prefix dashboard --ignore-scripts
npm --prefix dashboard test
npm --prefix dashboard run build
uv run harness-test task qa --pack workflow --all-cases
uv run harness-test task qa --pack contract --all-cases
```

Expected: all checks pass. Do not repeat successful full commands unless a later
change affects them.

- [ ] **Step 6: Commit documentation and checkpoint evidence.**

Update this plan's checkboxes and append exact focused/checkpoint outcomes. Then:

```bash
git add README.md docs/Runbook.md docs/Methodology.md \
  docs/superpowers/plans/2026-09-04-public-run-history.md
git commit -m "docs: explain public run history"
```

- [ ] **Step 7: Push the feature branch, open a pull request, and require CI.**

```bash
git push -u origin feature/public-run-history
gh pr create \
  --base main \
  --head feature/public-run-history \
  --title "Publish harness run history" \
  --body 'Publishes all recoverable public-safe run history, keeps decision-grade results separate, adds one terminal data sync, and starts no provider model sessions.'
```

Prepare the PR body in a temporary file outside the repository. Include the
21/182 backfill evidence, focused checks, single checkpoint, review disposition,
privacy boundary, and no-model-session statement. Wait for required checks and
merge without bypassing a failed check.

- [ ] **Step 8: Initialize the data branch without touching the code worktree.**

After required checks pass and before merging if the new Pages workflow would
otherwise race a missing branch, create one orphan branch in a temporary clone:

```bash
publication_tmp="$(mktemp -d)"
gh repo clone Studio-Moser/harness-testing "$publication_tmp/repository"
git -C "$publication_tmp/repository" switch --orphan dashboard-data
git -C "$publication_tmp/repository" rm -r --cached .
```

Use `apply_patch` or the implementation's branch-initialization helper to place
only a short `README.md`, verify `git status --short` lists no repository source
files, commit with the fixed publication identity, and push
`dashboard-data`. Never force-push. Remove the temporary directory only after
the push is verified.

- [ ] **Step 9: Merge code, sync local main, and publish one backfill commit.**

Merge the PR, fast-forward the dedicated local `main`, delete only this merged
topic branch, and run:

```bash
uv run harness-test report sync
```

Expected: one `dashboard-data` commit containing 21 JSON reports, 21 local
publication receipts, and one `Publish_Pages.yml` workflow dispatch.

- [ ] **Step 10: Verify the live dashboard.**

Wait for the dispatched Pages workflow, then verify
`https://studio-moser.github.io/harness-testing/` in the collaborative browser:

- 21 run cohorts and 182 job observations are visible;
- the latest `run-ba05867eab926cd91f6c` smoke is 3/3 with all three dimensions at 100%;
- the Aug 28 archived smoke and Aug 29 pre-ID release are visible as quarantined legacy evidence;
- partial/failed runs are labeled;
- no cross-series delta is shown;
- all six pages and filters work without console errors;
- the public JSON contains no raw prompt, trajectory, command output, credential, or local path.

Record the data commit, Pages run, deployed URL, and final test counts in this plan.
