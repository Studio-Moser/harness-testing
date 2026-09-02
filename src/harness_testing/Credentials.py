"""Load and store local credentials for provider subscription runs."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Mapping

_CLAUDE_SERVICE = "com.studiomoser.harness-testing"
_CLAUDE_ACCOUNT = "claude-code-oauth-token"


def load_claude_subscription_token(environment: Mapping[str, str]) -> str:
    """Return an environment override or the local macOS Keychain token."""

    token = environment.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if token.strip():
        return token
    if platform.system() != "Darwin":
        return ""
    try:
        result = subprocess.run(
            (
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                _CLAUDE_SERVICE,
                "-a",
                _CLAUDE_ACCOUNT,
                "-w",
            ),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def store_claude_subscription_token() -> None:
    """Prompt for and store the Claude subscription token in macOS Keychain."""

    if platform.system() != "Darwin":
        raise ValueError("Claude credential storage is only supported on macOS")
    try:
        subprocess.run(
            (
                "/usr/bin/security",
                "add-generic-password",
                "-U",
                "-s",
                _CLAUDE_SERVICE,
                "-a",
                _CLAUDE_ACCOUNT,
                "-w",
            ),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Claude credential storage failed") from None
