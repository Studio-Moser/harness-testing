from pathlib import Path

import pytest

from harness_testing.Report_Publication import (
    PublicationTarget,
    load_publication_target,
    publication_manifest_record,
)

REPOSITORY_ROOT = Path(__file__).parents[2]


def test_publication_policy_loads_one_fixed_target():
    target = load_publication_target(REPOSITORY_ROOT)

    assert target == PublicationTarget(
        repository="Studio-Moser/harness-testing",
        data_branch="dashboard-data",
        workflow="Publish_Pages.yml",
        code_ref="main",
    )
    assert publication_manifest_record(target) == {
        "mode": "public",
        "repository": "Studio-Moser/harness-testing",
        "data_branch": "dashboard-data",
        "workflow": "Publish_Pages.yml",
        "code_ref": "main",
    }


@pytest.mark.parametrize(
    "replacement",
    [
        'repository = "not-a-repository"',
        'data_branch = "../dashboard-data"',
        'workflow = "../Publish_Pages.yml"',
        'code_ref = "feature/public-run-history"',
        'extra = "not-allowed"',
    ],
)
def test_publication_policy_rejects_untrusted_targets(
    tmp_path: Path,
    replacement: str,
):
    policy = tmp_path / "policy"
    policy.mkdir()
    text = (REPOSITORY_ROOT / "policy" / "Dashboard_Publication.toml").read_text()
    key = replacement.split(" =", 1)[0]
    if key == "extra":
        text += replacement + "\n"
    else:
        text = "\n".join(
            replacement if line.startswith(f"{key} =") else line
            for line in text.splitlines()
        )
    (policy / "Dashboard_Publication.toml").write_text(text + "\n")

    with pytest.raises(ValueError, match="publication policy"):
        load_publication_target(tmp_path)
