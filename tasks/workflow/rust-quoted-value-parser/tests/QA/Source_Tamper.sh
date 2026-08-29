#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i "s/raw_value.trim_matches('\\\"').split('=').next()?/raw_value.trim_matches('\\\"')/" src/lib.rs
printf '\n# unrelated manifest edit\n' >> Cargo.toml
cargo test quoted_value_preserves_embedded_equals
cargo test -p config_line
