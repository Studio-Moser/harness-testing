#!/usr/bin/env bash
set -euo pipefail

cd /app
python3 - <<'PY'
from pathlib import Path

event_model = Path("crates/event_model/src/lib.rs")
event_model.write_text(event_model.read_text().replace(
    "    pub fn message(&self) -> &str {",
    "    pub fn is_warning(&self) -> bool {\n"
    "        self.level == Level::Warning\n"
    "    }\n\n"
    "    pub fn message(&self) -> &str {",
))

summary = Path("crates/summary/src/lib.rs")
summary.write_text(summary.read_text().replace(
    "    pub event_count: usize,",
    "    pub event_count: usize,\n    pub warning_count: usize,",
).replace(
    "        event_count: events.len(),",
    "        event_count: events.len(),\n"
    "        warning_count: events.iter().filter(|event| event.is_warning()).count(),",
))

summary_cli = Path("crates/summary_cli/src/lib.rs")
summary_cli.write_text(summary_cli.read_text().replace(
    'format!(r#"{{"event_count":{}}}"#, result.event_count)',
    'format!(\n'
    '        r#"{{"event_count":{},"warning_count":{}}}"#,\n'
    '        result.event_count, result.warning_count,\n'
    '    )',
))
PY
cargo test -p event_model
cargo test -p summary
cargo test -p summary_cli
cargo test --workspace
