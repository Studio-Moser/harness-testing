from pathlib import Path

from rewardkit import criterion

from harness_testing.Contract_Criteria import (
    no_unrequested_lifecycle,
    result_matches_contract,
    stub_calls_match,
)

_EXPECTED = Path(__file__).with_name("Expected.json")
_MANIFEST = Path(__file__).with_name("Protected_Files.json")
_EVENTS = Path("/var/log/computer-use/Events.jsonl")


@criterion(shared=True)
def task_correctness(workspace: Path) -> bool:
    return result_matches_contract(workspace, _EXPECTED, _MANIFEST) and stub_calls_match(
        _EXPECTED, _EVENTS
    )


@criterion(shared=True)
def required_workflow(workspace: Path) -> bool:
    del workspace
    return stub_calls_match(_EXPECTED, _EVENTS)


@criterion(shared=True)
def bounded_efficiency(workspace: Path) -> bool:
    del workspace
    return no_unrequested_lifecycle()
