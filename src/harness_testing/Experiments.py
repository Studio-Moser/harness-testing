"""Freeze contender inputs and resolve explicitly selected comparison evidence."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator


def contender_identity(effective_inputs: dict) -> str:
    """Hash effective inputs, never presentation labels or a model's claims."""
    payload = json.dumps(
        effective_inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def validate_experiment_request(document: dict) -> list[str]:
    """Collect schema and semantic errors without running models or fetching sources."""
    schema = Path(__file__).parents[2] / "policy" / "Experiment Request.schema.json"
    validator = Draft202012Validator(json.loads(schema.read_text()))
    errors = [
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in validator.iter_errors(document)
    ]
    try:
        json.dumps(document, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("request must contain only finite JSON values")
    if errors:
        # Continue only semantic checks whose shapes are already known.
        if (
            isinstance(document, dict)
            and document.get("purpose") == "candidate"
            and not document.get("baseline_result_ids")
        ):
            errors.append("baseline_result_ids: candidate comparison requires exact baseline IDs")
        return sorted(errors)
    purpose = document["purpose"]
    families = [item["family"] for item in document["contenders"]]
    if purpose == "candidate":
        if not document["baseline_result_ids"]:
            errors.append("baseline_result_ids: candidate comparison requires exact baseline IDs")
        if any(family in {"nothing", "superpowers"} for family in families):
            errors.append("contenders: candidate-only requests must not schedule baseline families")
    if purpose == "baseline" and document["baseline_result_ids"]:
        errors.append("baseline_result_ids: baseline establishment must not reuse baselines")
    if purpose == "baseline" and not {"nothing", "superpowers"}.issubset(families):
        errors.append("contenders: baseline establishment requires Nothing and Superpowers")
    if document["first_version"] == bool(document["predecessor_result_ids"]):
        errors.append("predecessor_result_ids: supply a predecessor or declare first_version")
    conditions, limits = document["conditions"], document["limits"]
    if (
        "provider_recovery_seconds" in conditions
        and type(conditions["provider_recovery_seconds"]) is not int
    ):
        errors.append("conditions.provider_recovery_seconds: an integer is required")
    if (
        conditions.get("provider_recovery_seconds", 0)
        and conditions["kickoff"]["provider"] != "codex"
    ):
        errors.append("conditions.provider_recovery_seconds: recovery requires the Codex protocol")
    if conditions["task_variant"] == "deepswe" and (
        purpose != "diagnostic" or conditions["task_ids"] != ["quill-shared-toolbar-focus"]
    ):
        errors.append("conditions: DeepSWE support is limited to the queued Quill diagnostic task")
    if purpose != "diagnostic" and conditions["task_variant"] != "comparison":
        errors.append(
            "conditions.task_variant: primary comparison requires neutral development tasks"
        )
    if conditions["concurrency"] != 1:
        errors.append("conditions.concurrency: comparison scheduling requires concurrency 1")
    sessions = len(families) * len(conditions["task_ids"]) * conditions["attempts"]
    if sessions > limits["max_sessions"]:
        errors.append(f"limits.max_sessions: {sessions} scheduled task trials exceed the limit")
    if limits["billing_mode"] == "subscription" and limits["max_budget_usd"] != 0:
        errors.append(
            "limits.max_budget_usd: subscription billing requires zero incremental budget"
        )
    if limits["billing_mode"] == "api" and limits["max_budget_usd"] <= 0:
        errors.append("limits.max_budget_usd: API billing requires a positive budget")
    for index, contender in enumerate(document["contenders"]):
        prefix = f"contenders.{index}"
        if contender["family"] == "nothing" and (
            contender["sources"]
            or contender["startup_paths"]
            or contender["rubric"]["mode"] != "disabled"
        ):
            errors.append(f"{prefix}: Nothing must have no added harness inputs")
        if (
            contender["family"] != "nothing"
            and not contender["sources"]
            and not contender["startup_paths"]
        ):
            errors.append(f"{prefix}: an added harness requires sources or startup_paths")
        rubric = contender["rubric"]
        if (rubric["mode"] == "enabled") != bool(rubric["path"]):
            errors.append(
                f"{prefix}.rubric: enabled requires a snapshot path; disabled requires null"
            )
    return sorted(errors)


def comparison_mismatches(left: dict, right: dict) -> list[str]:
    """Return sorted differing condition field paths; callers pass conditions only."""
    differences = []

    def visit(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                child = f"{path}.{key}" if path else key
                if key not in a or key not in b:
                    differences.append(child)
                else:
                    visit(a[key], b[key], child)
        elif type(a) is not type(b) or a != b:
            differences.append(path)

    visit(left, right, "")
    return differences


def resolve_reference_reports(request: dict, reports: list[dict]) -> list[dict]:
    """Resolve exact content identities and compatible complete reference coverage."""
    from harness_testing.Run_Reports import run_report_id

    baseline_ids = request["baseline_result_ids"]
    predecessor_ids = request["predecessor_result_ids"]
    wanted = list(dict.fromkeys(baseline_ids + predecessor_ids))
    selected = []
    for identity in wanted:
        matches = [report for report in reports if report.get("report_id") == identity]
        if not matches:
            raise ValueError(f"missing reference: {identity}")
        if len(matches) != 1 or run_report_id(matches[0]) != identity:
            raise ValueError(f"reference identity is ambiguous or invalid: {identity}")
        report = matches[0]
        experiment = report.get("experiment")
        if not isinstance(experiment, dict):
            raise ValueError(f"reference is historical, not a full comparison: {identity}")
        if experiment.get("purpose") == "diagnostic":
            raise ValueError(f"diagnostic reference cannot support a comparison: {identity}")
        differences = comparison_mismatches(request["conditions"], experiment["conditions"])
        if differences:
            raise ValueError("incompatible reference conditions: " + ", ".join(differences))
        selected.append(report)
    baselines = [report for report in selected if report["report_id"] in baseline_ids]
    for family in ("nothing", "superpowers") if baseline_ids else ():
        choices = [
            (report, contender)
            for report in baselines
            for contender in report["experiment"]["contenders"]
            if contender["family"] == family
        ]
        if len(choices) != 1:
            raise ValueError(f"reference family {family} requires exactly one selected result")
        _require_coverage(request["conditions"], *choices[0])
    for report in selected:
        if report["report_id"] in predecessor_ids:
            candidates = [
                contender
                for contender in report["experiment"]["contenders"]
                if contender["family"] in {item["family"] for item in request["contenders"]}
            ]
            if len(candidates) != 1:
                raise ValueError("predecessor must identify one candidate version per report")
            _require_coverage(request["conditions"], report, candidates[0])
    return selected


def _require_coverage(conditions: dict, report: dict, contender: dict) -> None:
    expected = Counter(
        (task, attempt)
        for task in conditions["task_ids"]
        for attempt in range(1, conditions["attempts"] + 1)
    )
    trials = [
        trial
        for trial in report["experiment"]["trials"]
        if trial["contender_id"] == contender["id"]
    ]
    actual = Counter((trial["task_id"], trial["attempt"]) for trial in trials)
    if actual != expected or any(
        trial["status"] not in {"completed", "agent_failed", "timeout"} for trial in trials
    ):
        raise ValueError(f"reference coverage incomplete for {contender['family']}")


def available_reference_reports(root: Path) -> list[dict]:
    """Load retained report revisions, deduplicating exact copies only."""
    from harness_testing.Run_Reports import load_run_report

    paths = list((root / "dashboard-data/reports").glob("*.json"))
    paths += list((root / "runs/generated").glob("*/Run_Report.json"))
    paths += [
        path
        for path in (root / "runs/evidence").glob("*.json")
        if len(path.stem) == 64 and all(character in "0123456789abcdef" for character in path.stem)
    ]
    reports = {}
    for path in sorted(paths):
        report = load_run_report(root, path)
        if report.get("report_id"):
            reports[report["report_id"]] = report
    return list(reports.values())


def runtime_image_digests(root: Path, images) -> dict[str, str]:
    """Freeze actual image contents, including their platform, not just build recipes."""
    from harness_testing.Materialize import (
        _inspect_image_id,
        image_reference,
        require_current_image,
    )

    result = {}
    for image in sorted(images):
        require_current_image(root, image)
        identity = _inspect_image_id(image_reference(root, image))
        if identity is None:
            raise ValueError(f"cannot freeze runtime image identity: {image}")
        result[image] = identity
    return result


def plan_experiment(
    root: Path, document: dict, *, reports: list[dict] | None = None, native_cli: bool = True
):
    """Freeze a request and feed only its selected contenders to the existing compiler."""
    import copy
    from decimal import Decimal

    from harness_testing.Comparison_Tasks import (
        materialize_comparison_tasks,
        research_scripted_user_policy,
    )
    from harness_testing.Config import load_versions
    from harness_testing.Contenders import materialize_contender
    from harness_testing.Materialize import _file_digests, load_deepswe_dataset
    from harness_testing.Runs import RunCell, _agent_adapter_digests, _tree_digest, compile_run

    errors = validate_experiment_request(document)
    if errors:
        raise ValueError("invalid experiment request:\n" + "\n".join(errors))
    request = copy.deepcopy(document)
    conditions, limits = request["conditions"], request["limits"]
    conditions.setdefault(
        "provider_recovery_seconds", 600 if conditions["kickoff"]["provider"] == "codex" else 0
    )
    if limits.get("budget_enforcement") == "hard-stop":
        raise ValueError(
            "tree_budget_hard_stop_unsupported: native providers do not guarantee "
            "an aggregate cross-provider dollar ceiling"
        )
    kickoff = conditions["kickoff"]
    packages = {
        row["name"]: row["version"] for row in load_versions(root / "Versions.toml")["packages"]
    }
    package = "@openai/codex" if kickoff["provider"] == "codex" else "@anthropic-ai/claude-code"
    if kickoff["runtime_version"] != packages[package]:
        raise ValueError("kickoff runtime version must match the pinned task image")
    if conditions["task_variant"] == "comparison":
        dataset = materialize_comparison_tasks(root, conditions["task_ids"])
        task_digests = {task: _tree_digest(dataset / task) for task in conditions["task_ids"]}
        scripted = {
            task: json.loads((dataset / task / "Scripted User.json").read_text())
            | {"interaction_limit": limits["interaction_limit"]}
            for task in conditions["task_ids"]
        }
        images = {"verifier"} | {
            "rust" if task.startswith("rust-") else "node" for task in conditions["task_ids"]
        }
        evaluator = {
            task: _file_digests(dataset / task / "tests") for task in conditions["task_ids"]
        }
        image_digests = runtime_image_digests(root, images)
        authority_scope = "local-development-task"
    else:
        dataset = load_deepswe_dataset(root, task_ids=conditions["task_ids"])
        task_digests = {
            task: _tree_digest(dataset.tasks_path / task) for task in conditions["task_ids"]
        }
        scripted = research_scripted_user_policy(conditions["task_ids"]) | {
            "interaction_limit": limits["interaction_limit"]
        }
        records = {
            record["task_id"]: record
            for record in json.loads(dataset.provenance_path.read_text())["tasks"]
        }
        evaluator = {
            task: records[task]["verifier_dockerfile_digest"] for task in conditions["task_ids"]
        }
        image_digests = {
            f"{task}:agent": records[task]["derived_image_digest"]
            for task in conditions["task_ids"]
        } | {
            f"{task}:verifier": records[task]["verifier_image_digest"]
            for task in conditions["task_ids"]
        }
        authority_scope = "deepswe-task"
    derived = {
        "task_digests": task_digests,
        "evaluator_digest": contender_identity(evaluator),
        "image_digests": image_digests,
        "scripted_user_digest": contender_identity(scripted),
        "authority_digest": contender_identity(
            {
                "scope": authority_scope,
                "executors": conditions["executor_inventory"],
                "resources": conditions["resources"],
            }
        ),
        "adapter_digest": contender_identity(_agent_adapter_digests(root)),
    }
    for key, value in derived.items():
        if key in conditions and conditions[key] != value:
            raise ValueError(f"conditions.{key}: frozen input does not match repository inputs")
        conditions[key] = value
    references = resolve_reference_reports(
        request, available_reference_reports(root) if reports is None else reports
    )
    cells, public = [], []
    changes = []
    for definition in request["contenders"]:
        bundle, contender = materialize_contender(
            root, kickoff["provider"], definition, native_cli=native_cli
        )
        public.append(contender)
        role = "baseline" if contender["family"] in {"nothing", "superpowers"} else "candidate"
        cells.append(
            RunCell(
                label=f"{kickoff['provider']}-{bundle.arm}-{role}",
                provider=kickoff["provider"],
                arm=bundle.arm,
                role=role,
                model=kickoff["model"],
                effort=kickoff["effort"],
                harness_commit=None,
                bundle_digest=bundle.digest,
                contender=contender,
            )
        )
        current = json.loads((bundle.path / "Provenance.json").read_text())
        predecessor = [
            c
            for report in references
            if report["report_id"] in request["predecessor_result_ids"]
            for c in report["experiment"]["contenders"]
            if c["family"] == contender["family"]
        ]
        old_files = {}
        if predecessor:
            found = []
            for path in (root / "arms/materialized").glob("*/*/*/Provenance.json"):
                previous = json.loads(path.read_text())
                if previous.get("contender", {}).get("id") == predecessor[0]["id"]:
                    found.append(previous["generated_file_digests"])
            if not found:
                raise ValueError(
                    "predecessor snapshot missing: materialize the exact previous version "
                    "to verify its source/configuration diff"
                )
            old_files = found[0]
            if predecessor[0]["id"] == contender["id"] and not request["change"]["rerun_reason"]:
                raise ValueError("unchanged contender requires an explicit rerun_reason")
        files = current["generated_file_digests"]
        changes.append(
            {
                "contender_id": contender["id"],
                "files": [
                    {"path": name, "before": old_files.get(name), "after": files.get(name)}
                    for name in sorted(files.keys() | old_files.keys())
                    if files.get(name) != old_files.get(name)
                ],
            }
        )
    request["change"]["diff_digest"] = contender_identity({"changes": changes})
    request["contenders"] = public
    request.pop("request_id", None)
    request["request_id"] = contender_identity(request)
    manifest = compile_run(
        root,
        profile="research" if conditions["task_variant"] == "deepswe" else "calibration",
        billing_mode=limits["billing_mode"],
        cells=tuple(cells),
        task_ids=tuple(conditions["task_ids"]),
        max_sessions=limits["max_sessions"],
        max_budget_usd=Decimal(str(limits["max_budget_usd"])),
        attempts=conditions["attempts"],
        concurrency=conditions["concurrency"],
        agent_timeout_seconds=conditions["timeout_seconds"],
        publish_report=request["publication"]["mode"] == "configured",
        experiment=request,
    )
    (manifest.path.parent / "Verified Changes.json").write_text(
        json.dumps(changes, indent=2) + "\n"
    )
    reference_dir = root / "runs/evidence"
    reference_dir.mkdir(parents=True, exist_ok=True)
    for report in references:
        path = reference_dir / (report["report_id"].removeprefix("sha256:") + ".json")
        contents = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if path.exists() and json.loads(path.read_text()) != report:
            raise ValueError("immutable reference evidence conflicts with retained content")
        path.write_text(contents)
    return manifest
