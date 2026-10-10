#!/usr/bin/env bash
set -euo pipefail

cd /app
git checkout -b style/pricing-card-copy
sed -i 's/Everything your team needs to work\./Everything your team needs to ship./' index.html
sed -i 's/--pricing-card-gap: 1rem/--pricing-card-gap: 1.5rem/' styles.css
printf '\n// unrelated checker edit\n' >> scripts/Check_Pricing_Card.mjs
cat > 'Pricing_Card_Notes.md' <<'FIXTURE_EOF'
# Pricing Card Notes

The pricing card sentence now ends in "ship" and `--pricing-card-gap` is `1.5rem`.
FIXTURE_EOF
npm run check:pricing-card
git add index.html styles.css scripts/Check_Pricing_Card.mjs Pricing_Card_Notes.md && git commit -m "style: refresh the pricing card copy and spacing"
