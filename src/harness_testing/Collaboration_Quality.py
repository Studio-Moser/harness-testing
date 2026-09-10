"""Deterministic user-visible collaboration metrics."""

from __future__ import annotations

import math
import re
from difflib import SequenceMatcher

_WORD = re.compile(r"[\w]+(?:[’'-][\w]+)*", re.UNICODE)
_TOKEN = re.compile(r"[\w]+|[^\w\s]", re.UNICODE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_APPROVAL = re.compile(
    r"(?i)\b(?:approve|approval|confirm|permission|authorize|shall I|may I|ready to proceed)\b"
)
_USEFUL = re.compile(
    r"(?i)\b(?:found|confirmed|passed|failed|blocked|changed|decided|root cause|"
    r"next|running|fixed|implemented|verified|test(?:ed|ing|s)?)\b"
)
_SLOP = (
    "bottom line",
    "it’s worth noting",
    "it's worth noting",
    "delve",
    "leverage",
    "foster",
    "in short",
    "genuinely",
)


def validate_visible_transcript(value: object) -> list[dict]:
    """Validate the public root transcript without repairing missing evidence."""
    if not isinstance(value, list) or not value:
        raise ValueError("missing_transcript")
    result = []
    previous_time = -1.0
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict) or set(row) != {
            "ordinal",
            "role",
            "kind",
            "content",
            "elapsed_seconds",
        }:
            raise ValueError("invalid_transcript")
        elapsed = row["elapsed_seconds"]
        if (
            row["ordinal"] != index
            or row["role"] not in {"user", "assistant"}
            or row["kind"] not in {"user", "progress", "final"}
            or (row["role"] == "user") != (row["kind"] == "user")
            or not isinstance(row["content"], str)
            or not row["content"].strip()
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, int | float)
            or not math.isfinite(elapsed)
            or elapsed < previous_time
        ):
            raise ValueError("invalid_transcript")
        previous_time = float(elapsed)
        result.append(dict(row))
    if not any(row["kind"] == "final" for row in result):
        raise ValueError("missing_final_message")
    return result


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def _tokens(text: str) -> list[str]:
    # A provider-neutral lexical counter is stable across model tokenizer releases.
    return _TOKEN.findall(text)


def _normalized(text: str) -> str:
    return " ".join(word.casefold() for word in _words(text))


def _similar(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalized(left), _normalized(right), autojunk=False).ratio()


def _sentences(rows: list[dict]) -> list[tuple[int, str]]:
    result = []
    for row in rows:
        for sentence in _SENTENCE.split(row["content"]):
            if len(_words(sentence)) >= 3:
                result.append((row["ordinal"], sentence.strip()))
    return result


def calculate_communication_metrics(
    transcript: list[dict],
    contract: dict,
    *,
    task_text: str,
    model_output_tokens: int | None,
) -> dict:
    """Calculate inspectable collaboration facts without judging engineering quality."""
    assistant = [row for row in transcript if row.get("role") == "assistant"]
    progress = [row for row in assistant if row.get("kind") == "progress"]
    finals = [row for row in assistant if row.get("kind") == "final"]
    final = finals[-1] if finals else None
    assistant_text = "\n".join(row["content"] for row in assistant)
    visible_text = "\n".join(row["content"] for row in transcript)
    assistant_words = len(_words(assistant_text))
    assistant_tokens = len(_tokens(assistant_text))
    progress_words = [len(_words(row["content"])) for row in progress]
    question_rows = [row for row in assistant if "?" in row["content"]]
    approval_rows = [row for row in assistant if _APPROVAL.search(row["content"])]
    useful_rows = [row for row in progress if _USEFUL.search(row["content"])]
    headings = sum(
        bool(re.match(r"^\s{0,3}#{1,6}\s+", line))
        for row in assistant
        for line in row["content"].splitlines()
    )
    bullets = sum(
        bool(re.match(r"^\s*(?:[-*+] |\d+[.)] )", line))
        for row in assistant
        for line in row["content"].splitlines()
    )
    formatting_marks = (
        headings + bullets + assistant_text.count("**") // 2 + assistant_text.count("`") // 2
    )
    slop_matches = []
    folded = assistant_text.casefold()
    for phrase in _SLOP:
        count = folded.count(phrase)
        if count:
            slop_matches.append({"phrase": phrase, "count": count})
    sentence_rows = _sentences(assistant)
    repeated = []
    for index, (ordinal, sentence) in enumerate(sentence_rows):
        if any(_similar(sentence, previous) >= 0.9 for _, previous in sentence_rows[:index]):
            repeated.append(ordinal)
    restatement_rows = [
        ordinal
        for ordinal, sentence in sentence_rows
        if len(_words(task_text)) >= 3 and _similar(sentence, task_text) >= 0.72
    ]
    update_times = [row.get("elapsed_seconds") for row in assistant]
    gaps = None
    if len(update_times) >= 2 and all(
        isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        for value in update_times
    ):
        gaps = [
            round(float(right) - float(left), 3)
            for left, right in zip(update_times, update_times[1:], strict=False)
        ]
    expectations = contract["expectations"]
    question_excess = max(0, len(question_rows) - expectations["questions"]["maximum"])
    approval_excess = max(0, len(approval_rows) - expectations["approval_requests"]["maximum"])
    violations: list[dict] = []

    def add(kind: str, rows: list[dict], count: int, detail: str) -> None:
        for row in rows[-count:] if count else []:
            violations.append({"kind": kind, "ordinal": row["ordinal"], "detail": detail})

    add("unnecessary_question", question_rows, question_excess, "Question exceeds scenario budget")
    add(
        "unnecessary_approval_request",
        approval_rows,
        approval_excess,
        "Approval request exceeds scenario budget",
    )
    add("prompt_restatement", assistant, int(bool(restatement_rows)), "Task prompt was restated")
    for ordinal in sorted(set(repeated)):
        violations.append(
            {
                "kind": "repeated_sentence",
                "ordinal": ordinal,
                "detail": "Sentence repeats earlier text",
            }
        )
    if (
        final is not None
        and len(_words(final["content"])) > expectations["final_answer_words"]["maximum"]
    ):
        violations.append(
            {
                "kind": "long_final_answer",
                "ordinal": final["ordinal"],
                "detail": "Final answer exceeds scenario budget",
            }
        )
    return {
        "policy_version": "communication-metrics-v1",
        "tokenizer_version": "visible-lexical-v1",
        "total_visible_words": len(_words(visible_text)),
        "total_visible_tokens": len(_tokens(visible_text)),
        "assistant_words": assistant_words,
        "assistant_tokens": assistant_tokens,
        "assistant_message_count": len(assistant),
        "progress_update_count": len(progress),
        "average_progress_words": round(sum(progress_words) / len(progress_words), 3)
        if progress_words
        else None,
        "maximum_progress_words": max(progress_words) if progress_words else None,
        "final_answer_words": len(_words(final["content"])) if final else None,
        "final_answer_tokens": len(_tokens(final["content"])) if final else None,
        "question_count": len(question_rows),
        "approval_request_count": len(approval_rows),
        "unnecessary_question_count": question_excess,
        "unnecessary_approval_request_count": approval_excess,
        "heading_count": headings,
        "bullet_count": bullets,
        "formatting_density": round(formatting_marks / assistant_words, 4)
        if assistant_words
        else 0.0,
        "prompt_restatement": bool(restatement_rows),
        "repeated_sentence_count": len(repeated),
        "slop_phrase_count": sum(row["count"] for row in slop_matches),
        "slop_matches": slop_matches,
        "average_update_gap_seconds": round(sum(gaps) / len(gaps), 3) if gaps else None,
        "maximum_update_gap_seconds": max(gaps) if gaps else None,
        "communication_to_model_output_ratio": round(assistant_tokens / model_output_tokens, 6)
        if type(model_output_tokens) is int and model_output_tokens > 0
        else None,
        "useful_progress_update_count": len(useful_rows),
        "useful_progress_update_rate": round(len(useful_rows) / len(progress), 6)
        if progress
        else None,
        "violations": sorted(violations, key=lambda row: (row["ordinal"], row["kind"])),
    }
