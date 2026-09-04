#!/usr/bin/env bash
set -euo pipefail

cd /app
perl -0pi -e "s/  void value\n  return 'all'/  return value === 'active' || value === 'archived' ? value : 'all'/" \
  src/domain/Saved_View.ts
perl -0pi -e 's/  void view\n  void storage/  storage.setItem(SAVED_VIEW_KEY, view)/' \
  src/domain/Saved_View.ts
printf '\n// benchmark tamper probe\n' >> src/domain/Saved_View.test.ts
npm run test:saved-view
npm run test:view-filter
npm run gate
