from harness_testing.Collaboration_Quality import calculate_communication_metrics


def contract():
    return {
        "schema_version": "1",
        "scenario": "small_clear_change",
        "expectations": {
            "initial_update": "required",
            "progress_updates": {"minimum": 1, "maximum": 2, "require_new_information": True},
            "questions": {"minimum": 0, "maximum": 0},
            "approval_requests": {"minimum": 0, "maximum": 0},
            "final_answer_words": {"minimum": 1, "maximum": 8},
            "prompt_restatement": False,
        },
        "rubric": ["directness"],
    }


def transcript():
    return [
        {
            "ordinal": 1,
            "role": "user",
            "kind": "user",
            "content": "Change blue to purple.",
            "elapsed_seconds": 0.0,
        },
        {
            "ordinal": 2,
            "role": "assistant",
            "kind": "progress",
            "content": "I found the source value.",
            "elapsed_seconds": 2.0,
        },
        {
            "ordinal": 3,
            "role": "assistant",
            "kind": "progress",
            "content": "Please approve this plan?",
            "elapsed_seconds": 8.0,
        },
        {
            "ordinal": 4,
            "role": "user",
            "kind": "user",
            "content": "Proceed.",
            "elapsed_seconds": 9.0,
        },
        {
            "ordinal": 5,
            "role": "assistant",
            "kind": "final",
            "content": "Change blue to purple. Change blue to purple.",
            "elapsed_seconds": 12.0,
        },
    ]


def test_metrics_are_reproducible_and_keep_exact_violation_turns():
    first = calculate_communication_metrics(
        transcript(), contract(), task_text="Change blue to purple.", model_output_tokens=200
    )
    second = calculate_communication_metrics(
        transcript(), contract(), task_text="Change blue to purple.", model_output_tokens=200
    )
    assert first == second
    assert first["policy_version"] == "communication-metrics-v1"
    assert first["assistant_message_count"] == 3
    assert first["progress_update_count"] == 2
    assert first["average_progress_words"] == 4.5
    assert first["maximum_progress_words"] == 5
    assert first["final_answer_words"] == 8
    assert first["question_count"] == 1
    assert first["approval_request_count"] == 1
    assert first["unnecessary_question_count"] == 1
    assert first["unnecessary_approval_request_count"] == 1
    assert first["prompt_restatement"] is True
    assert first["repeated_sentence_count"] == 1
    assert first["useful_progress_update_count"] == 1
    assert first["useful_progress_update_rate"] == 0.5
    assert first["average_update_gap_seconds"] == 5.0
    assert first["maximum_update_gap_seconds"] == 6.0
    assert first["communication_to_model_output_ratio"] > 0
    assert {row["ordinal"] for row in first["violations"]} == {3, 5}


def test_unknown_timing_and_model_usage_remain_unknown():
    rows = transcript()
    rows[1].pop("elapsed_seconds")
    result = calculate_communication_metrics(
        rows, contract(), task_text="Different", model_output_tokens=None
    )
    assert result["average_update_gap_seconds"] is None
    assert result["maximum_update_gap_seconds"] is None
    assert result["communication_to_model_output_ratio"] is None


def test_slop_and_formatting_are_measured_separately_from_quality():
    rows = [
        {"ordinal": 1, "role": "user", "kind": "user", "content": "Answer.", "elapsed_seconds": 0},
        {
            "ordinal": 2,
            "role": "assistant",
            "kind": "final",
            "content": "## Bottom line\n\n- It’s worth noting we can leverage this.",
            "elapsed_seconds": 1,
        },
    ]
    result = calculate_communication_metrics(
        rows, contract(), task_text="Answer.", model_output_tokens=20
    )
    assert result["heading_count"] == 1
    assert result["bullet_count"] == 1
    assert result["slop_phrase_count"] == 3
    assert result["formatting_density"] > 0
