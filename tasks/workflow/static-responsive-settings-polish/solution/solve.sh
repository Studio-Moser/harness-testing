#!/usr/bin/env sh
set -eu
cd /app
cat > 'Styles.css' <<'FIXTURE_EOF'
* { box-sizing: border-box; }
body { margin: 0; color: #172536; background: #f5f7f9; font: 16px/1.6 system-ui, sans-serif; }
main { width: min(1120px, 100%); margin: auto; padding: 48px 24px; }
header { max-width: 640px; margin-bottom: 32px; } h1 { margin: 0 0 8px; font-size: 36px; line-height: 1.2; letter-spacing: -.03em; }
p { margin: 0; } .cards { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 24px; }
article { display: flex; flex-direction: column; align-items: flex-start; gap: 16px; background: #fff; padding: 24px; border: 1px solid #d6dfe8; border-radius: 12px; }
h2 { margin: 0; font-size: 20px; line-height: 1.3; } article p { flex: 1; }
button { min-height: 44px; padding: 10px 16px; border: 1px solid #294766; border-radius: 6px; background: #294766; color: white; font: inherit; cursor: pointer; }
button:focus-visible { outline: 3px solid #835a12; outline-offset: 3px; } #status { margin-top: 24px; }
@media(max-width: 700px) { main { padding: 32px 20px; } h1 { font-size: 30px; } .cards { grid-template-columns: 1fr; } }
FIXTURE_EOF
python Visual_Check.py
