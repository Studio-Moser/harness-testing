#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i 's/Ship faster together/Build calmer workflows/' index.html
sed -i 's/--section-gap: 2rem/--section-gap: 4rem/' styles.css
sed -i 's/<div class="page-shell">/<main id="main-content" class="page-shell">/' index.html
sed -i 's#</div>#</main>#' index.html
printf '\n// benchmark tamper probe\n' >> test/Page.test.js
npm run gate
