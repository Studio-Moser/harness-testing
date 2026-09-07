"""Deterministic task-user replies, without solution access or extra authority."""

from __future__ import annotations

import re

_ROUTINE_APPROVAL_REQUEST = re.compile(
    r"""(?isx)(?:^|[.!?]\s+|\n\s*\n)
    (?:
        (?:may|shall|should|can)\s+i\s+(?:proceed|continue)\b.*
        |(?:please\s+)?(?:approve|confirm)\s+(?:this|that|the)\s+(?:plan|design)
          (?:\s+(?:so\s+i\s+can|and\s+i(?:'|’)ll)\s+implement\s+it)?
        |does\s+(?:this|that|the)\s+(?:plan|design)\s+look\s+right
    )[?.]?\s*$"""
)
_EXTERNAL_APPROVAL_REQUEST = re.compile(
    r"""(?isx)(?:^|[.!?]\s+|\n\s*\n)(?:please\s+)?(?:approve|confirm)\s+
    (?:(?:this|that|the)\s+)?(?:external\s+)?
    (?:deployment|publication|spending|deploy|publish|spend)\b.*?[?.]?\s*$"""
)
_AMBIGUOUS_APPROVAL_REQUEST = re.compile(
    r"(?is)(?:^|[.!?]\s+|\n\s*\n)(?:please\s+)?(?:approve|confirm)\b.*?[?.]?\s*$"
)


def terminal_approval_request(text: str) -> str | None:
    """Classify terminal approval requests without treating completion prose as a request."""
    if _ROUTINE_APPROVAL_REQUEST.search(text):
        return "routine"
    if _EXTERNAL_APPROVAL_REQUEST.search(text):
        return "external"
    if _AMBIGUOUS_APPROVAL_REQUEST.search(text):
        return "ambiguous"
    return None


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
        if not isinstance(rule, dict) or set(rule) != {"id", "kind", "pattern", "fact"}:
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
        and re.fullmatch(rule["pattern"], text, re.IGNORECASE)
    ]
    if len(matches) != 1:
        return {
            "status": "authority_denied" if kind == "approval" else "task_definition_gap",
            "rule_id": None,
            "reply": None,
        }
    rule = matches[0]
    return {"status": "reply", "rule_id": rule["id"], "reply": policy["facts"][rule["fact"]]}
