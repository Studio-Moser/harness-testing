#!/usr/bin/env sh
set -eu
cd /app
cat > 'src/Pagination.js' <<'FIXTURE_EOF'
export function pageOf(rows, page, size) {
  if (!Number.isInteger(page) || page < 1 || !Number.isInteger(size) || size < 1 || size > 100) throw new RangeError('invalid pagination');
  return {items: rows.slice(page*size,(page+1)*size),total: rows.length,pages: Math.ceil(rows.length/size)};
}
FIXTURE_EOF
