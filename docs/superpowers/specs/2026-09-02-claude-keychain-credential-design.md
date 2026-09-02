# Claude Keychain Credential Design

**Status:** Approved
**Date:** 2026-09-02
**Scope:** Persist the Claude subscription credential used by local Harness Testing runs without writing it to a repository, manifest, log, shell profile, or process argument.

## Context

Claude Code is still authenticated to the developer's Max subscription, but
Harness Testing cannot pass that macOS Keychain login through Harbor's isolated
Claude session. The runner therefore requires the inference-only token produced
by `claude setup-token`. Supplying that token only through
`CLAUDE_CODE_OAUTH_TOKEN` made it disappear after the launching environment or
macOS login session ended.

## Design

Harness Testing will use one generic-password item in the developer's default
macOS Keychain. The service is `com.studiomoser.harness-testing` and the account
is `claude-code-oauth-token`.

`uv run harness-test auth claude` will invoke `/usr/bin/security
add-generic-password` with `-w` as the final argument, causing the native tool to
prompt for the token instead of placing it in the command line. The command will
replace an existing item and print only a success or failure message.

For a subscription run containing a Claude cell, execution will resolve the
credential in this order:

1. A non-empty `CLAUDE_CODE_OAUTH_TOKEN` from the caller, preserving portable CI
   and ephemeral overrides.
2. The named Keychain item on macOS.
3. The existing fail-closed "Claude subscription credential is missing" error.

The resolved token exists only in the runner's in-memory child environment sent
to Harbor. It is never written into the approved manifest, generated job YAML,
public results, documentation, or logs. API-key variables remain forbidden in
subscription mode. Non-macOS systems keep the environment-variable path and do
not gain a new credential store.

## Error handling

A missing item, denied Keychain access, unavailable `security` executable, or
blank stored value behaves exactly like a missing credential. Storage failures
return a concise error without echoing subprocess output. The run must fail
before Harbor starts if no credential resolves.

## Verification

Focused tests will cover environment precedence, Keychain fallback, failure
closure, prompt-only storage, CLI redaction, and propagation into only the
Harbor child environment. The full Python suite and Ruff run once at the commit
checkpoint. No provider model session is part of this change.
