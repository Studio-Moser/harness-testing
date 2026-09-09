"""Deterministic task-user replies, without solution access or extra authority."""

from __future__ import annotations

import re

_LOCAL_DEVELOPMENT_APPROVAL = re.compile(
    r"""(?isx)
    (?:
        \b(?:may|shall|should|can)\s+i\s+(?:proceed|continue|implement)\b
        |\b(?:please\s+)?(?:approve|confirm)\s+(?:this|that|the)\s+
          (?:plan|design|approach)\b
        |\bdoes\s+(?:this|that|the)\s+(?:plan|design)\s+look\s+right\b
    )"""
)
_TERMINAL_DIRECT_REQUEST = re.compile(
    r"""(?isx)(?:^|[.!?]\s+|\n\s*\n)
    (?P<request>
        (?:
            (?:may|shall|should|can)\s+i\s+(?:proceed|continue|implement)\b
            |(?:please\s+)?(?:approve|confirm)\b
            |does\s+(?:this|that|the)\s+(?:plan|design)\s+look\s+right\b
        )
        (?:(?![.!?]\s+).)*
    )
    [?.]?\s*$"""
)
_BROADER_AUTHORITY = re.compile(
    r"\b(?:deploy(?:ment|ing)?|publish(?:ing)?|publication|push(?:ing)?|"
    r"spend(?:ing)?|pay(?:ing)?|purchas(?:e|ing)|send(?:ing)?|upload(?:ing)?|"
    r"production|credentials?)\b",
    re.I,
)
_SCOPE_EXPANSION = re.compile(
    r"\b(?:additional|extra|broader)\s+(?:permissions?|authority)\b"
    r"|\boutside\s+(?:the\s+)?original\s+scope\b",
    re.I,
)
_COMPLETED_OR_NEGATED_APPROVAL = re.compile(
    r"""(?isx)
    \b(?:implemented|completed)\s+(?:the\s+)?(?:approved\s+)?(?:plan|design|approach)\b
    |\bi\s+(?:no\s+longer|do\s+not|don't|did\s+not|didn't)\s+need\s+you\s+to\s+
      (?:approve|confirm)\b
    """
)
_AMBIGUOUS_APPROVAL_REQUEST = re.compile(
    r"(?is)(?:^|[.!?]\s+|\n\s*\n)(?:please\s+)?(?:approve|confirm)\b.*?[?.]?\s*$"
)


def _terminal_request_clause(text: str) -> str | None:
    match = _TERMINAL_DIRECT_REQUEST.search(text)
    return match["request"].strip() if match else None


def _local_development_approval(text: str) -> bool:
    request = _terminal_request_clause(text)
    return bool(
        request
        and _LOCAL_DEVELOPMENT_APPROVAL.match(request)
        and not _BROADER_AUTHORITY.search(request)
        and not _SCOPE_EXPANSION.search(request)
        and not _COMPLETED_OR_NEGATED_APPROVAL.search(request)
    )


def terminal_approval_request(text: str) -> str | None:
    """Classify terminal approval requests without treating completion prose as a request."""
    request = _terminal_request_clause(text)
    if request is None or _COMPLETED_OR_NEGATED_APPROVAL.search(request):
        return None
    if _BROADER_AUTHORITY.search(request) or _SCOPE_EXPANSION.search(request):
        return "external"
    if _local_development_approval(text):
        return "routine"
    if _AMBIGUOUS_APPROVAL_REQUEST.search(request):
        return "ambiguous"
    return None


def _local_branch_handoff(text: str) -> bool:
    # ponytail: explicit completed branch menus; replay new forms before extending this matcher.
    menu = re.search(
        r"(?im)^(?:implementation|work|task) (?:is )?complete[.!][ \t]*"
        r"(?:what would you like to do\?)?[ \t]*\n"
        r"(?P<options>(?:[ \t]*\n|[ \t]*\d+[.)][ \t]+[^\n]+\n)+)"
        r"[ \t]*(?:which option(?: would you like)?|what would you like to do)\?[ \t]*\Z",
        text,
    )
    if menu is None:
        return False
    return any(
        re.fullmatch(
            r"\s*\d+[.)]\s+Keep the branch as[- ]is"
            r"(?:\s+\(I['’]ll handle it later\))?[.!]?\s*",
            line,
            re.I,
        )
        for line in menu["options"].splitlines()
    )


_MATCHERS = {
    "local-development-approval": ("approval", _local_development_approval),
    "local-branch-handoff": ("clarification", _local_branch_handoff),
}


def validate_policy(policy: dict) -> None:
    if not isinstance(policy, dict) or set(policy) != {
        "schema_version",
        "interaction_limit",
        "facts",
        "rules",
    }:
        raise ValueError("scripted user policy requires version, limit, facts and rules only")
    if (
        policy["schema_version"] != "1"
        or type(policy["interaction_limit"]) is not int
        or not 1 <= policy["interaction_limit"] <= 100
    ):
        raise ValueError("invalid scripted user version or interaction limit")
    facts, rules = policy["facts"], policy["rules"]
    if not isinstance(facts, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v for k, v in facts.items()
    ):
        raise ValueError("scripted facts must be nonempty text")
    if not isinstance(rules, list):
        raise ValueError("scripted rules must be a list")
    ids = set()
    for rule in rules:
        base = {"id", "kind", "fact"}
        if not isinstance(rule, dict) or set(rule) not in (
            base | {"pattern"},
            base | {"matcher"},
        ):
            raise ValueError("invalid scripted response rule")
        if not all(isinstance(value, str) for value in rule.values()):
            raise ValueError("scripted rule values must be strings")
        if (
            not rule["id"]
            or rule["id"] in ids
            or rule["fact"] not in facts
            or rule["kind"] not in {"clarification", "approval"}
        ):
            raise ValueError("invalid response identity, kind or fact reference")
        ids.add(rule["id"])
        if "matcher" in rule and (
            rule["matcher"] not in _MATCHERS or rule["kind"] != _MATCHERS[rule["matcher"]][0]
        ):
            raise ValueError("invalid scripted response matcher")
        if "pattern" in rule:
            try:
                re.compile(rule["pattern"])
            except re.error as error:
                raise ValueError("invalid scripted response pattern") from error


def select_reply(request: dict, policy: dict, interactions: int) -> dict:
    """Resolve a normalized runtime request only against frozen authored rules."""
    validate_policy(policy)
    if type(interactions) is not int or interactions < 0:
        raise ValueError("invalid interaction count")
    if interactions >= policy["interaction_limit"]:
        return {"status": "interaction_limit", "rule_id": None, "reply": None}
    if not isinstance(request, dict) or not isinstance(request.get("text"), str):
        raise ValueError("runtime request requires text")
    kind = request.get("kind")
    text = request["text"].strip()
    if kind == "complete":
        return {"status": "complete", "rule_id": None, "reply": None}
    # Rules can approve an ordinary conversation gate, never grant tool actions.
    if request.get("actions"):
        return {"status": "authority_denied", "rule_id": None, "reply": None}
    matches = [
        rule
        for rule in policy["rules"]
        if len(text) <= 8192
        and rule["kind"] == kind
        and (
            _MATCHERS[rule["matcher"]][1](text)
            if "matcher" in rule
            else re.fullmatch(rule["pattern"], text, re.IGNORECASE)
        )
    ]
    if len(matches) != 1:
        return {
            "status": "authority_denied" if kind == "approval" else "task_definition_gap",
            "rule_id": None,
            "reply": None,
        }
    rule = matches[0]
    return {"status": "reply", "rule_id": rule["id"], "reply": policy["facts"][rule["fact"]]}
