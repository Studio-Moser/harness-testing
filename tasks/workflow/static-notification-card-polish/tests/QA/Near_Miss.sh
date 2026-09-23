#!/usr/bin/env sh
set -eu
cd /app
cat > Styles.css <<'FIXTURE_EOF'
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.6 system-ui,sans-serif; color: #1c2b3a; background: #f4f6f8; }
main { padding: 32px 20px; }
.card { max-width: 640px; margin: auto; padding: 24px; background: #fff; border: 1px solid #cbd5df; border-radius: 12px; }
h1 { font-size: 28px; line-height: 1.2; margin: 0 0 16px; } p { margin: 0 0 16px; }
button { min-width: 44px; min-height: 44px; padding: 10px 16px; background: #234361; color: #fff; border: 0; border-radius: 6px; font: inherit; }
button:focus-visible { outline: 3px solid #986900; outline-offset: 3px; }

.card { min-width: 640px; }
FIXTURE_EOF
