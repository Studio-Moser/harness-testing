#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i 's/{\"event_count\":{}}/{\"event_count\":{},\"warning_count\":0}/' crates/summary_cli/src/lib.rs
cargo test -p event_model
