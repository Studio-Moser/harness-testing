#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i 's/--cta-background: #2563eb/--cta-background: #7c3aed/' src/index.css
