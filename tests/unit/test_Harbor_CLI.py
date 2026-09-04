import sys

from harness_testing.Harbor_CLI import harbor_command


def test_harbor_command_uses_the_current_python_environment():
    assert harbor_command("run", "--config", "Job.yaml") == (
        sys.executable,
        "-m",
        "harbor.cli.main",
        "run",
        "--config",
        "Job.yaml",
    )
