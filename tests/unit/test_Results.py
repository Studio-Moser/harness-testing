import copy
import json
import subprocess
from pathlib import Path

import pytest

import harness_testing.CLI as CLI
from harness_testing.CLI import main
from harness_testing.Results import (
    compatibility_key,
    construct_public_result,
    public_result_id,
    regrade_job,
    sanitize_public_result,
    trend_series_key,
    validate_public_result,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "Fixtures" / "Public_Results"


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / name).read_text())


def _result_root(path: Path) -> Path:
    policy = path / "policy"
    policy.mkdir(parents=True, exist_ok=True)
    (policy / "Public_Result.schema.json").write_bytes(
        (REPOSITORY_ROOT / "policy" / "Public_Result.schema.json").read_bytes()
    )
    (path / "Versions.toml").write_text(
        '[repository]\nschema_version = "0.1.0"\n'
    )
    return path


def _refresh_identity(document: dict[str, object]) -> None:
    compatibility = document["compatibility"]
    assert isinstance(compatibility, dict)
    compatibility["key"] = compatibility_key(document)
    document["result_id"] = public_result_id(document)


def _source_job(root: Path) -> tuple[Path, Path]:
    source = root / "jobs" / "source-job"
    trial = source / "task__trial"
    (trial / "artifacts" / "workspace").mkdir(parents=True)
    (trial / "artifacts" / "workspace" / "result.txt").write_text("immutable\n")
    (trial / "artifacts" / "trajectory.json").write_text('{"steps": []}\n')
    (source / "config.json").write_text("{}\n")
    (source / "result.json").write_text(
        json.dumps({"id": "11111111-1111-4111-8111-111111111111"})
    )
    (trial / "config.json").write_text("{}\n")
    (trial / "result.json").write_text(
        json.dumps({"id": "22222222-2222-4222-8222-222222222222"})
    )
    (trial / "artifacts" / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "source": "/app",
                    "destination": "artifacts/workspace",
                    "type": "directory",
                    "status": "ok",
                    "service": None,
                },
                {
                    "source": "/logs/agent/trajectory.json",
                    "destination": "artifacts/trajectory.json",
                    "type": "file",
                    "status": "ok",
                    "service": None,
                },
            ]
        )
    )
    tasks = root / "tasks" / "workflow"
    tasks.mkdir(parents=True)
    (tasks / "task.toml").write_text('schema_version = "1.4"\n')
    return source, tasks


def test_regrade_uses_the_exact_harbor_command_and_preserves_the_source(
    tmp_path: Path,
):
    source, tasks = _source_job(tmp_path)
    before = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    calls: list[tuple[str, ...]] = []

    def runner(arguments: tuple[str, ...], **kwargs: object):
        calls.append(arguments)
        assert kwargs == {
            "cwd": tmp_path,
            "check": True,
            "capture_output": True,
            "text": True,
        }
        regraded = tmp_path / "jobs" / "regraded-job"
        regraded.mkdir()
        (regraded / "config.json").write_text("{}\n")
        (regraded / "result.json").write_text("{}\n")
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout="New job directory: jobs/regraded-job\n",
            stderr="",
        )

    record = regrade_job(tmp_path, source, tasks, runner=runner)

    assert calls == [
        (
            "harbor",
            "job",
            "regrade",
            str(source.resolve()),
            "-p",
            str(tasks.resolve()),
            "-e",
            "docker",
        )
    ]
    assert record.source_job_id == "11111111-1111-4111-8111-111111111111"
    assert record.source_job_path == source.resolve()
    assert record.regrade_job_path == (tmp_path / "jobs" / "regraded-job").resolve()
    assert record.source_job_digest.startswith("sha256:")
    receipt = json.loads((record.regrade_job_path / "Regrade.json").read_text())
    assert receipt["source_job_digest"] == record.source_job_digest
    assert receipt["command"] == list(calls[0])
    after = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("missing_source", ["/app", "/logs/agent/trajectory.json"])
def test_regrade_rejects_missing_required_artifacts_before_harbor(
    tmp_path: Path, missing_source: str
):
    source, tasks = _source_job(tmp_path)
    manifest_path = next(source.rglob("artifacts/manifest.json"))
    manifest = json.loads(manifest_path.read_text())
    manifest_path.write_text(
        json.dumps([item for item in manifest if item["source"] != missing_source])
    )
    called = False

    def runner(*args: object, **kwargs: object):
        nonlocal called
        called = True
        raise AssertionError("Harbor must not run")

    with pytest.raises(ValueError, match="required artifact"):
        regrade_job(tmp_path, source, tasks, runner=runner)
    assert called is False


def test_regrade_detects_any_source_job_mutation(tmp_path: Path):
    source, tasks = _source_job(tmp_path)

    def runner(arguments: tuple[str, ...], **kwargs: object):
        del kwargs
        (source / "config.json").write_text('{"changed": true}\n')
        regraded = tmp_path / "jobs" / "regraded-job"
        regraded.mkdir()
        (regraded / "config.json").write_text("{}\n")
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout="New job directory: jobs/regraded-job\n",
            stderr="",
        )

    with pytest.raises(ValueError, match="source job changed"):
        regrade_job(tmp_path, source, tasks, runner=runner)


def test_regrade_reports_harbor_failure_without_changing_the_source(tmp_path: Path):
    source, tasks = _source_job(tmp_path)
    before = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }

    def runner(arguments: tuple[str, ...], **kwargs: object):
        del kwargs
        raise subprocess.CalledProcessError(7, arguments, stderr="private output")

    with pytest.raises(ValueError, match="Harbor regrade failed with exit code 7"):
        regrade_job(tmp_path, source, tasks, runner=runner)

    after = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_valid_public_result_is_constructed_from_only_allowlisted_fields(
    tmp_path: Path,
):
    source = _load("Valid.json")

    public = construct_public_result(REPOSITORY_ROOT, source)

    assert public == source
    assert public["efficiency"]["reasoning_tokens"] is None
    assert public["efficiency"]["test_seconds"] is None
    assert validate_public_result(REPOSITORY_ROOT, public) == ()
    root = _result_root(tmp_path)
    output = root / "runs" / "generated" / "sanitized.json"
    written = sanitize_public_result(root, FIXTURE_ROOT / "Valid.json", output)
    assert json.loads(output.read_text()) == written
    assert set(written) == {
        "schema_version",
        "result_id",
        "run",
        "review",
        "provider",
        "arm",
        "task",
        "dataset",
        "provenance",
        "compatibility",
        "dimensions",
        "efficiency",
        "infrastructure",
        "source_links",
    }


@pytest.mark.parametrize("name", ["Raw_Harbor_Job.json", "Secret_Path.json"])
def test_raw_or_sensitive_documents_fail_closed(tmp_path: Path, name: str):
    root = _result_root(tmp_path)
    output = root / "runs" / "generated" / "should-not-exist.json"

    with pytest.raises(ValueError):
        sanitize_public_result(root, FIXTURE_ROOT / name, output)

    assert not output.exists()


def test_result_sanitize_cli_rejects_raw_harbor_input_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    root = _result_root(tmp_path)
    output = root / "runs" / "generated" / "should-not-publish.json"
    monkeypatch.setattr(CLI, "_repository_root", lambda: root)

    assert (
        main(
            [
                "result",
                "sanitize",
                "--job",
                str(FIXTURE_ROOT / "Raw_Harbor_Job.json"),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert "forbidden public field" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize(
    "field",
    ["trajectory", "reasoning", "command_output", "tool_output", "env", "extra"],
)
def test_private_raw_fields_are_rejected_instead_of_filtered(field: str):
    document = _load("Valid.json")
    document[field] = {"value": "private"}

    with pytest.raises(ValueError, match="forbidden public field|public result schema"):
        construct_public_result(REPOSITORY_ROOT, document)


def test_unknown_telemetry_is_rejected_instead_of_published():
    document = _load("Valid.json")
    document["efficiency"]["new_provider_metric"] = 12

    with pytest.raises(ValueError, match="Additional properties are not allowed"):
        construct_public_result(REPOSITORY_ROOT, document)


@pytest.mark.parametrize(
    "value",
    [
        "file:///Users/example/private/job.json",
        "/home/example/private/job.json",
        "OPENAI_API_KEY=sk-example-secret-value",
        "Authorization: Bearer private-token",
    ],
)
def test_sensitive_strings_are_rejected_even_in_an_allowlisted_field(value: str):
    document = _load("Valid.json")
    document["infrastructure"]["detail"] = value
    _refresh_identity(document)

    with pytest.raises(ValueError, match="sensitive or local-only string"):
        construct_public_result(REPOSITORY_ROOT, document)


def test_methodology_changes_split_trends_without_a_reviewed_mapping():
    original = _load("Valid.json")
    changed = copy.deepcopy(original)
    changed["provenance"]["methodology_schema"] = "2"

    with pytest.raises(ValueError, match="compatibility key"):
        construct_public_result(REPOSITORY_ROOT, changed)

    old_key = original["compatibility"]["key"]
    _refresh_identity(changed)
    changed_result = construct_public_result(REPOSITORY_ROOT, changed)
    assert trend_series_key(changed_result) == changed["compatibility"]["key"]
    assert trend_series_key(changed_result) != old_key

    changed["compatibility"]["reviewed_mapping"] = {
        "compatible_with": old_key,
        "review_id": "methodology-v2-reviewed",
        "reviewed_at": "2026-08-29T06:00:00Z",
        "rationale": "Schema-only rename with identical scoring semantics.",
    }
    _refresh_identity(changed)
    mapped_result = construct_public_result(REPOSITORY_ROOT, changed)
    assert trend_series_key(mapped_result) == old_key


def test_finalization_requires_both_reviews_and_a_complete_run(tmp_path: Path):
    for field in ("task_reviewed", "infrastructure_reviewed"):
        document = _load("Valid.json")
        document["review"][field] = False
        _refresh_identity(document)
        with pytest.raises(ValueError, match="finalized result"):
            construct_public_result(REPOSITORY_ROOT, document)

    partial = _load("Valid.json")
    partial["review"]["partial"] = True
    _refresh_identity(partial)
    with pytest.raises(ValueError, match="finalized result"):
        construct_public_result(REPOSITORY_ROOT, partial)

    local = _load("Valid.json")
    local["run"]["finalized"] = False
    local["review"]["partial"] = True
    _refresh_identity(local)
    root = _result_root(tmp_path)
    source = root / "candidate.json"
    source.write_text(json.dumps(local))
    with pytest.raises(ValueError, match="results/ accepts only finalized"):
        sanitize_public_result(root, source, root / "results" / "partial.json")
