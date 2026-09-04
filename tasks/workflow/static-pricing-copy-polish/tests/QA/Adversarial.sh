#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i 's/Everything your team needs to work\./Everything your team needs to ship./' index.html
sed -i 's/--pricing-card-gap: 1rem/--pricing-card-gap: 1.5rem/' styles.css
printf '\n// benchmark tamper probe\n' >> test/Pricing_Card.test.js
npm run check:pricing-card
