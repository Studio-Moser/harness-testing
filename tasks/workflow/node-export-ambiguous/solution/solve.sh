#!/usr/bin/env sh
set -eu
cd /app
cat > 'src/Export.js' <<'FIXTURE_EOF'
import {serializeCsv} from './Serializer.js';
export function exportRows(rows) {
  return serializeCsv([['id','title'], ...rows.filter(row=>row.visible).map(row=>[row.id,row.title])]);
}
FIXTURE_EOF
npm test
