from pathlib import Path

import pytest
from harbor.models.job.config import JobConfig
from harbor.models.task.config import TaskConfig
from harbor.models.trajectories import Trajectory

from harness_testing.Config import load_job, load_task, load_trajectory

FIXTURES = Path(__file__).parents[1] / "Fixtures" / "ATIF"

VALID_TASK = '''
version = "1.4"

[[artifacts]]
source = "/app"
destination = "workspace"
exclude = [".git", "node_modules", "target"]

[[artifacts]]
source = "/logs/agent/trajectory.json"
destination = "trajectory.json"

[task]
name = "studio-moser/sample-task"
version = "1.0.0"

[environment]
network_mode = "no-network"

[agent]
network_mode = "allowlist"
allowed_hosts = []

[verifier]
environment_mode = "separate"
network_mode = "no-network"
'''

VALID_JOB = '''
job_name: fixture
jobs_dir: jobs/raw
n_attempts: 1
n_concurrent_trials: 1
quiet: false
retry:
  max_retries: 1
  include_exceptions:
    - NetworkConnectionError
    - UnknownApiError
environment:
  type: docker
  force_build: false
  delete: true
  mounts: []
agents:
  - name: claude-code
    model_name: anthropic/claude-sonnet-4-6
    extra_allowed_hosts:
      - api.anthropic.com
    skills: []
    kwargs:
      version: 2.1.236
      reasoning_effort: high
      config: {}
    env: {}
datasets:
  - path: tasks/workflow
    task_names:
      - react-grouped-ui-updates
'''


def test_task_loader_returns_harbor_task_model(tmp_path):
    task_path = tmp_path / "task.toml"
    task_path.write_text(VALID_TASK)

    task = load_task(task_path, expected_schema="1.4")

    assert isinstance(task, TaskConfig)
    assert task.task is not None
    assert task.task.name == "studio-moser/sample-task"


def test_task_loader_rejects_wrong_schema_version(tmp_path):
    task_path = tmp_path / "task.toml"
    task_path.write_text(VALID_TASK.replace('version = "1.4"', 'version = "1.3"', 1))

    with pytest.raises(ValueError, match="expected schema 1.4"):
        load_task(task_path, expected_schema="1.4")


def test_task_loader_rejects_deprecated_orchestrator_field(tmp_path):
    task_path = tmp_path / "task.toml"
    task_path.write_text('orchestrator = "legacy"\n' + VALID_TASK)

    with pytest.raises(ValueError, match="orchestrator"):
        load_task(task_path, expected_schema="1.4")


def test_job_loader_returns_harbor_job_model(tmp_path):
    job_path = tmp_path / "job.yml"
    job_path.write_text(VALID_JOB)

    job = load_job(job_path)

    assert isinstance(job, JobConfig)
    assert job.n_concurrent_trials == 1


def test_job_loader_rejects_deprecated_orchestrator_field(tmp_path):
    job_path = tmp_path / "job.yml"
    job_path.write_text("orchestrator: legacy\n" + VALID_JOB)

    with pytest.raises(ValueError, match="orchestrator"):
        load_job(job_path)


@pytest.mark.parametrize("fixture_name", ["Valid_Claude.json", "Valid_Codex.json"])
def test_trajectory_loader_uses_harbor_atif_model(fixture_name):
    trajectory = load_trajectory(FIXTURES / fixture_name)

    assert isinstance(trajectory, Trajectory)
    assert trajectory.schema_version == "ATIF-v1.7"


def test_trajectory_loader_rejects_unknown_atif_field():
    with pytest.raises(ValueError, match="unknown_root_field"):
        load_trajectory(FIXTURES / "Invalid_Unknown_Field.json")
