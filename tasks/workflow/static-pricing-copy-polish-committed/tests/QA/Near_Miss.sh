#!/usr/bin/env bash
set -euo pipefail

cd /app
git checkout -b style/pricing-card-copy
sed -i 's/Everything your team needs to work\./Everything your team needs to ship./' index.html
sed -i 's/--pricing-card-gap: 1rem/--pricing-card-gap: 1.5rem/' styles.css
cat > 'NOTES.md' <<'FIXTURE_EOF'
# Pricing Card Notes

The pricing card sentence now ends in "ship" and `--pricing-card-gap` is `1.5rem`.
FIXTURE_EOF
npm run check:pricing-card
git add index.html styles.css NOTES.md && git commit -m "style: refresh the pricing card copy and spacing"
