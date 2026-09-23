"""Rendered checks for a bounded card; visual taste is reviewed separately."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
    contrast = Path("Visual_Contrast.js").read_text()
    output = Path(os.environ.get("VISUAL_OUTPUT_DIRECTORY", "/tmp/visual-proof"))
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pages = []
        for width in (320, 768, 1440):
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page.route("http://**/*", lambda r: r.abort())
            page.route("https://**/*", lambda r: r.abort())
            page.goto(Path("index.html").resolve().as_uri())
            page.screenshot(path=str(output / f"card-{width}.png"), full_page=True)
            pages.append(page)
        for page in pages:
            m = page.evaluate("""() => {
              const card=document.querySelector('.card'), button=document.querySelector('button');
              const c=card.getBoundingClientRect(), b=button.getBoundingClientRect();
              return {overflow:document.documentElement.scrollWidth>innerWidth,width:c.width,x:c.x,button:[b.width,b.height],body:parseFloat(getComputedStyle(document.body).fontSize),heading:parseFloat(getComputedStyle(document.querySelector('h1')).fontSize),padding:parseFloat(getComputedStyle(card).paddingLeft)};
            }""")
            assert not m["overflow"] and 200 <= m["width"] <= 640 and m["x"] >= 0
            assert m["body"] >= 16 and m["heading"] >= 24 and m["padding"] >= 16
            assert min(page.evaluate(contrast, 'h1,p:not(:empty),button')) >= 4.5
            assert min(m["button"]) >= 44
            assert page.locator("h1").is_visible() and page.locator("button").is_visible()
            page.keyboard.press("Tab")
            assert page.locator("button").evaluate("(e)=>e===document.activeElement")
            assert page.locator("button").evaluate("(e)=>getComputedStyle(e).outlineStyle!=='none' && parseFloat(getComputedStyle(e).outlineWidth)>=2")
            page.keyboard.press("Enter")
            assert page.locator("#status").inner_text() == "Preferences saved"
            assert min(page.evaluate(contrast, '#status')) >= 4.5
        browser.close()
    print("Card layout, contrast, keyboard and behavior checks passed at all three widths.")
if __name__ == "__main__":
    main()
