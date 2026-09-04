from harness_testing.Public_Safety import public_safety_errors


def test_public_safety_rejects_private_keys_and_values():
    assert public_safety_errors({"prompt": "private"}) == (
        "forbidden public field: $.prompt",
    )
    assert public_safety_errors({"model": "/Users/example/model"}) == (
        "sensitive or local-only string: $.model",
    )


def test_public_safety_accepts_allowlisted_summary_values():
    assert public_safety_errors(
        {
            "provider": "codex",
            "dimensions": {"correctness": 1.0},
            "limitations": ["partial-run"],
        }
    ) == ()
