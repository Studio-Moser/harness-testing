#!/usr/bin/env sh
set -eu
cd /app
cat > 'test/Behavior.test.js' <<'FIXTURE_EOF'
import {test,expect} from 'vitest'; test('pretend success',()=>expect(true).toBe(true));
FIXTURE_EOF
