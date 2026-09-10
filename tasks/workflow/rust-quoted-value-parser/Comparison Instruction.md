Work in `/app` and fix `parse_line` so `parse_line(r#"token="a=b""#)` preserves the complete quoted value. The parsed value must be `a=b`, not `a`.

Preserve existing project tests, package metadata, build configuration, and check scripts. Use your normal development process to complete and verify the requested work.
