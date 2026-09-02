import subprocess

import harness_testing.Credentials as Credentials


def test_load_claude_subscription_token_prefers_environment_without_keychain_call(
    monkeypatch,
):
    def unexpected_keychain_call(*arguments, **keywords):
        raise AssertionError("environment precedence must not query Keychain")

    monkeypatch.setattr(Credentials.subprocess, "run", unexpected_keychain_call)

    assert Credentials.load_claude_subscription_token(
        {"CLAUDE_CODE_OAUTH_TOKEN": "present"}
    ) == "present"


def test_load_claude_subscription_token_reads_trimmed_macos_keychain_value(
    monkeypatch,
):
    calls = []

    def fake_run(arguments, **keywords):
        calls.append((arguments, keywords))
        return subprocess.CompletedProcess(arguments, 0, " saved \n", "")

    monkeypatch.setattr(Credentials.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(Credentials.subprocess, "run", fake_run)

    assert Credentials.load_claude_subscription_token({}) == "saved"
    assert calls == [
        (
            (
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                "com.studiomoser.harness-testing",
                "-a",
                "claude-code-oauth-token",
                "-w",
            ),
            {"capture_output": True, "text": True, "check": True},
        )
    ]


def test_load_claude_subscription_token_fails_closed_on_keychain_error(monkeypatch):
    def fake_run(arguments, **keywords):
        raise subprocess.CalledProcessError(1, arguments, output="unexpected detail")

    monkeypatch.setattr(Credentials.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(Credentials.subprocess, "run", fake_run)

    assert Credentials.load_claude_subscription_token({}) == ""


def test_store_claude_subscription_token_uses_prompt_only_keychain_storage(
    monkeypatch,
):
    calls = []

    def fake_run(arguments, **keywords):
        calls.append((arguments, keywords))
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(Credentials.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(Credentials.subprocess, "run", fake_run)

    Credentials.store_claude_subscription_token()

    arguments, keywords = calls[0]
    assert arguments[-1] == "-w"
    assert arguments == (
        "/usr/bin/security",
        "add-generic-password",
        "-U",
        "-s",
        "com.studiomoser.harness-testing",
        "-a",
        "claude-code-oauth-token",
        "-w",
    )
    assert keywords == {
        "check": True,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
