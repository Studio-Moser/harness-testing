#!/usr/bin/env bash
set -euo pipefail

cd /app

cat > src/App.tsx <<'EOF'
import './App.css'

export default function App() {
  return <h2>No projects yet</h2>
}
EOF
sed -i 's/--accent: #2563eb/--accent: #6d28d9/' src/index.css
sed -i 's/--card-gap: 20px/--card-gap: 12px/' src/index.css

npm run gate
