"""Isolated local computer-use MCP server for the deterministic benchmark."""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from playwright.async_api import Browser, Page, async_playwright
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

EVENTS = Path("/var/log/computer-use/Events.jsonl")
CAPTURE = Path("/var/log/computer-use/Capture.png")
UI_URL = "http://127.0.0.1:8000/ui"
EVENTS_LOCK = threading.Lock()

browser: Browser | None = None
page: Page | None = None
playwright_runtime: Any = None


def record(action: object, payload: object, *, matched: bool = True) -> None:
    with EVENTS_LOCK:
        prior = EVENTS.read_text().splitlines() if EVENTS.exists() else []
        event = {
            "sequence": len(prior) + 1,
            "action": action,
            "payload": payload,
            "matched": matched,
        }
        with EVENTS.open("a") as handle:
            handle.write(
                json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
            )


def _failed_tool_result(result: object) -> bool:
    return getattr(result, "is_error", False) is True or (
        isinstance(result, dict) and result.get("isError") is True
    )


def _raw_tool_call(context: Any) -> tuple[object, object]:
    params = context.params if isinstance(context.params, Mapping) else {}
    return params.get("name"), params.get("arguments")


class AttemptRecorder:
    async def __call__(self, context: Any, call_next: Any) -> object:
        if context.method != "tools/call":
            return await call_next(context)
        try:
            result = await call_next(context)
        except Exception:
            record(*_raw_tool_call(context), matched=False)
            raise
        if _failed_tool_result(result):
            record(*_raw_tool_call(context), matched=False)
        return result


mcp = MCPServer("harness-computer-use", middleware=[AttemptRecorder()])


async def active_page() -> Page:
    if page is None:
        raise RuntimeError("open_test_ui must be called first")
    return page


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    del request
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/ui", methods=["GET"])
async def ui(request: Request) -> HTMLResponse:
    del request
    return HTMLResponse(
        """<!doctype html>
<html><head><meta charset="utf-8"><style>
html,body{margin:0;width:100%;height:100%;font-family:system-ui;background:#f8fafc;color:#0f172a}
html[data-theme="navy"] body{background:#0f172a;color:#f8fafc}
main{padding:48px}button{font:inherit;padding:12px 18px}
#theme-status{margin-top:24px;font-size:24px}
</style></head><body><main><h1>Theme Lab</h1><button id="theme-navy">Use Navy</button>
<p id="theme-status">Default theme active</p></main><script>
document.querySelector('#theme-navy').addEventListener('click',()=>{
  document.documentElement.dataset.theme='navy';
  document.querySelector('#theme-status').textContent='Navy theme active';
});
</script></body></html>"""
    )


@mcp.tool()
async def open_test_ui() -> dict[str, object]:
    """Open the isolated benchmark UI in a real browser."""
    global browser, page, playwright_runtime
    playwright_runtime = await async_playwright().start()
    browser = await playwright_runtime.chromium.launch(
        headless=True, args=["--no-sandbox"]
    )
    page = await browser.new_page(viewport={"width": 800, "height": 600})
    await page.goto(UI_URL)
    record("open_test_ui", {"url": UI_URL})
    return {"opened": True, "url": UI_URL}


@mcp.tool()
async def choose_theme(theme: str) -> dict[str, object]:
    """Choose the requested theme through the rendered UI."""
    if theme != "navy":
        raise ValueError("only the requested navy state is available")
    current = await active_page()
    await current.locator("#theme-navy").click()
    status = await current.locator("#theme-status").inner_text()
    record("choose_theme", {"status": status, "theme": theme})
    return {"status": status}


@mcp.tool()
async def capture_screenshot() -> dict[str, object]:
    """Capture fresh visual evidence from the current browser page."""
    current = await active_page()
    await current.screenshot(path=str(CAPTURE), animations="disabled")
    record("capture_screenshot", {"height": 600, "path": str(CAPTURE), "width": 800})
    return {"height": 600, "path": str(CAPTURE), "width": 800}


@mcp.tool()
async def inspect_capture() -> dict[str, object]:
    """Inspect the captured PNG itself and report its observed background pixel."""
    if browser is None or not CAPTURE.is_file():
        raise RuntimeError("capture_screenshot must be called first")
    data_url = "data:image/png;base64," + base64.b64encode(CAPTURE.read_bytes()).decode()
    inspector = await browser.new_page(viewport={"width": 800, "height": 600})
    await inspector.set_content(f'<img id="capture" src="{data_url}">')
    await inspector.locator("#capture").wait_for(state="visible")
    observed = await inspector.evaluate(
        """() => {
          const image = document.querySelector('#capture');
          const canvas = document.createElement('canvas');
          canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
          canvas.getContext('2d').drawImage(image, 0, 0);
          return Array.from(canvas.getContext('2d').getImageData(5, 5, 1, 1).data);
        }"""
    )
    await inspector.close()
    payload = {"height": 600, "observed_rgb": observed, "width": 800}
    record("inspect_capture", payload)
    return {**payload, "matches_navy": observed == [15, 23, 42, 255]}


if __name__ == "__main__":
    EVENTS.write_text("")
    security = TransportSecuritySettings(
        allowed_hosts=["computer-use", "computer-use:*", "127.0.0.1:*", "localhost:*"],
        allowed_origins=[],
    )
    mcp.run(
        "streamable-http",
        host="0.0.0.0",
        port=8000,
        json_response=True,
        stateless_http=True,
        transport_security=security,
    )
