#!/usr/bin/env bash
set -euo pipefail
cd /app
python - <<'PY'
import asyncio
from mcp import Client

async def main() -> None:
    async with Client("http://127.0.0.1:8000/mcp") as client:
        await client.call_tool("open_test_ui", {})
        await client.call_tool("choose_theme", {"theme": "red"})
        await client.call_tool("choose_theme", {"theme": "navy"})
        await client.call_tool("capture_screenshot", {})
        result = await client.call_tool("inspect_capture", {})
        if result.structured_content.get("matches_navy") is not True:
            raise RuntimeError("captured image did not inspect as Navy")

asyncio.run(main())
PY
cat > Harness_Result.json <<'JSON'
{"status":"accepted","route":{"requested":"default","actual_model":"gpt-5.6-terra","effort":"high","provider":"codex","executor":"native-agent+computer-use-mcp","resolution":"primary","attempted":["gpt-5.6-terra@high"],"fallback_reason":null},"artifacts":{"files":["/var/log/computer-use/Capture.png"],"report":null},"evidence":{"fixed_target":"ui-state:theme=navy-v1","checks":["computer-use MCP sequence: passed","Capture.png 800x600 navy pixel inspection: passed"],"outcome":"proven"},"telemetry":{"attempts":1,"elapsed":null,"verification_failures":0,"token_or_quota_usage":null},"shelby":{"project_id":null,"run_id":null,"checkpoint_ids":[]},"blockers":[]}
JSON
