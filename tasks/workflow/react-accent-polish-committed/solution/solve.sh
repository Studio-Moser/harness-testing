#!/usr/bin/env bash
set -euo pipefail

cd /app
git checkout -b style/cta-accent
sed -i 's/--cta-background: #2563eb/--cta-background: #6d28d9/' src/index.css
cat > 'Accent_Notes.md' <<'FIXTURE_EOF'
# Accent Notes

`--cta-background` changed from `#2563eb` to `#6d28d9`. Component logic is unchanged.
FIXTURE_EOF
npm run check:cta
git add src/index.css Accent_Notes.md && git commit -m "style: switch the CTA background to violet"
