#!/usr/bin/env sh
set -eu
cd /app
cat > 'src/Release_Notes.js' <<'FIXTURE_EOF'
export const releaseNotes = [
  { version: '2.0.0', highlights: ['Tasks can be archived', 'Search is faster on large lists'] },
  { version: '1.4.0', highlights: ['Tasks can be filtered by label'] },
];
FIXTURE_EOF
npm test
npm run release-status
