#!/usr/bin/env bash
set -euo pipefail

cd /app
cargo test unquoted_value_parses
