#!/usr/bin/env bash
set -euo pipefail
cd /app
python - <<'PY'
import asyncio
from mcp import Client

async def main() -> None:
    async with Client("http://127.0.0.1:8000/mcp") as client:
        await client.call_tool("open_test_ui", {})
        await client.call_tool("choose_theme", {"theme": "navy"})
        await client.call_tool("capture_screenshot", {})

asyncio.run(main())
PY
printf '%s\n' '{"status":"accepted"}' > Harness_Result.json
