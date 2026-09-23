import json

import pytest

from harness_testing.Experiment_Reports import _research_protected_state
from tests.Support.Research_QA import (
    NEAR_MISS_REMOVED_PATHS,
    _near_miss_patch,
    _source_tamper_patch,
)


@pytest.mark.parametrize("task, removed_path", NEAR_MISS_REMOVED_PATHS.items())
def test_research_near_miss_removes_its_task_specific_implementation_file(
    task, removed_path
):
    retained = "src/retained.ts"
    golden = (
        f"diff --git a/{retained} b/{retained}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{retained}\n"
        "@@ -0,0 +1 @@\n"
        "+retained\n"
        f"diff --git a/{removed_path} b/{removed_path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{removed_path}\n"
        "@@ -0,0 +1 @@\n"
        "+required\n"
    )

    near_miss = _near_miss_patch(task, golden)

    assert f"diff --git a/{retained} b/{retained}\n" in near_miss
    assert f"diff --git a/{removed_path} b/{removed_path}\n" not in near_miss


def test_research_near_miss_requires_the_expected_golden_section():
    with pytest.raises(ValueError, match="expected implementation file"):
        _near_miss_patch("quill-shared-toolbar-focus", "")


@pytest.mark.parametrize("task", NEAR_MISS_REMOVED_PATHS)
def test_research_source_tamper_preserves_solution_but_fails_protection(tmp_path, task):
    golden = (
        "diff --git a/src/feature.ts b/src/feature.ts\n"
        "index aaa..bbb 100644\n"
        "--- a/src/feature.ts\n"
        "+++ b/src/feature.ts\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    tampered = _source_tamper_patch(task, golden)
    assert tampered.startswith(golden)
    assert f".github/workflows/{task}-verification.yml" in tampered

    source = tmp_path / "task"
    (source / "tests").mkdir(parents=True)
    (source / "tests/config.json").write_text(
        json.dumps({"f2p_node_ids": ["new"], "p2p_node_ids": ["old"]})
    )
    directory = tmp_path / "trial"
    artifact = directory / "artifacts/logs/artifacts/model.patch"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(tampered)
    rewards = {
        "reward": 1,
        "apply_failed": 0,
        "f2p_total": 1,
        "f2p_passed": 1,
        "p2p_total": 1,
        "p2p_passed": 1,
    }

    assert _research_protected_state(source, rewards, directory) is False
