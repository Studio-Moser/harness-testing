#!/usr/bin/env bash
set -euo pipefail

cd /app
perl -0pi -e "s/  void value\n  return 'all'/  return value === 'active' || value === 'archived' ? value : 'all'/" \
  src/domain/Saved_View.ts
npm run test:view-filter
