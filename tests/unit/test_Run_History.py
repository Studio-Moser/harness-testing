import hashlib
import json
import shutil
from pathlib import Path

import pytest

from harness_testing.Run_History import backfill_run_reports
from harness_testing.Run_Reports import load_run_report

REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURES = REPOSITORY_ROOT / "tests" / "Fixtures" / "Run_History"


def _digest(contents: bytes) -> str:
    return f"sha256:{hashlib.sha256(contents).hexdigest()}"


def _manifest_digest(document: dict[str, object]) -> str:
    unsigned = dict(document)
    unsigned.pop("digest", None)
    return _digest(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    )


def _job_yaml(job_name: str) -> str:
    return (
        f"job_name: {job_name}\n"
        "n_attempts: 1\n"
        "agents:\n"
        "  - import_path: harness_testing.Codex_Agent:HarnessCodex\n"
        "    model_name: openai/gpt-5.6-terra\n"
        "    kwargs:\n"
        "      version: 0.150.1\n"
    )


@pytest.fixture
def history_root(tmp_path: Path) -> Path:
    policy = tmp_path / "policy"
    policy.mkdir()
    shutil.copyfile(
        REPOSITORY_ROOT / "policy" / "Run_Report.schema.json",
        policy / "Run_Report.schema.json",
    )
    (tmp_path / "Versions.toml").write_text(
        '[repository]\nschema_version = "0.3.0"\n'
    )
    archive = tmp_path / "archive"
    document = json.loads((FIXTURES / "Identified_Manifest.json").read_text())
    manifest_staging = archive / "manifest-staging"
    jobs = manifest_staging / "jobs"
    jobs.mkdir(parents=True)
    config_digests: dict[str, str] = {}
    for relative_path, label in zip(
        document["harbor_config_paths"],
        ("codex-A0-baseline", "codex-A2-candidate"),
        strict=True,
    ):
        job_name = f"run-11111111111111111111-{label}-react-saved-view-feature"
        contents = _job_yaml(job_name)
        destination = manifest_staging / relative_path
        destination.write_text(contents)
        config_digests[relative_path] = _digest(contents.encode())
        result = archive / "jobs" / "raw" / job_name / "result.json"
        result.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURES / "Identified_Result.json", result)
    document["provenance"]["harbor_config_digests"] = config_digests
    document["digest"] = _manifest_digest(document)
    manifest_root = (
        archive
        / "runs"
        / "generated"
        / document["digest"].removeprefix("sha256:")
    )
    manifest_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(manifest_staging, manifest_root)
    (manifest_root / "Manifest.json").write_text(json.dumps(document) + "\n")
    (tmp_path / "Empty_Mapping.toml").write_text("")
    mapping = (FIXTURES / "Legacy_Mapping.toml").read_text().replace(
        "sha256:" + "f" * 64,
        document["digest"],
    )
    (tmp_path / "Legacy_Mapping.toml").write_text(mapping)
    legacy_result = (
        archive
        / "jobs"
        / "raw"
        / "Legacy"
        / "run-11111111111111111111-codex-A0-baseline-react-saved-view-feature"
        / "result.json"
    )
    legacy_result.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "Identified_Result.json", legacy_result)
    trial = archive / "jobs" / "raw" / "ignored" / "trial-1"
    trial.mkdir(parents=True)
    (trial / "trajectory.json").write_text("private\n")
    return tmp_path


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


def test_backfill_labels_partial_identified_runs(history_root: Path):
    result_paths = sorted(
        (history_root / "archive" / "jobs" / "raw").glob(
            "run-11111111111111111111-*/result.json"
        )
    )
    result_paths[-1].unlink()

    paths = backfill_run_reports(
        history_root,
        (history_root / "archive",),
        history_root / "Empty_Mapping.toml",
        history_root / "runs" / "history",
    )
    report = load_run_report(history_root, paths[0], published=True)

    assert report["status"] == "failed"
    assert report["pending_jobs"] == 1
    assert report["evidence"]["limitations"] == ["partial-run", "failed-run"]


def test_backfill_rejects_duplicate_sources_and_external_output(history_root: Path):
    source = history_root / "archive"
    with pytest.raises(ValueError, match="present and unique"):
        backfill_run_reports(
            history_root,
            (source, source),
            history_root / "Empty_Mapping.toml",
            history_root / "runs" / "history",
        )
    with pytest.raises(ValueError, match="runs/history"):
        backfill_run_reports(
            history_root,
            (source,),
            history_root / "Empty_Mapping.toml",
            history_root / "outside",
        )


def test_backfill_never_opens_trial_artifacts(
    history_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    real_read = Path.read_text

    def guarded_read(file_path: Path, *args: object, **kwargs: object) -> str:
        assert "trajectory" not in file_path.name.lower()
        assert "trial.log" not in file_path.name
        return real_read(file_path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    backfill_run_reports(
        history_root,
        (history_root / "archive",),
        history_root / "Empty_Mapping.toml",
        history_root / "runs" / "history",
    )
