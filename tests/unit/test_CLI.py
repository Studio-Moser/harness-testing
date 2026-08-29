import pytest


def test_version_reports_repository_schema(capsys):
    from harness_testing.CLI import main

    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == "harness-test 0.1.0\n"
