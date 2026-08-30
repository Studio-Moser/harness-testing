Add `warning_count` across this Rust workspace:

- Preserve the warning signal exposed by `event_model`.
- Include `warning_count` in the `summary::Summary` result.
- Include it in the JSON printed by `summary_cli`.

The regression tests are already provided and immutable; do not add or edit project tests.
Use focused crate tests while working (`event_model`, `summary`, and `summary_cli`), then
run `cargo test --workspace` exactly once after the workspace is complete.
