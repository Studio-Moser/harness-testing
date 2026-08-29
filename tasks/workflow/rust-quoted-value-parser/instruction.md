Fix `parse_line` so this input preserves the complete quoted value:

```rust
parse_line(r#"token="a=b""#)
```

The parsed value must be `a=b`, not `a`.

Run `cargo test quoted_value_preserves_embedded_equals` for the regression, then run
`cargo test -p config_line` once as the final package check.
