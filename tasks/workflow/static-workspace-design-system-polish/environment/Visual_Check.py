"""Protected multi-route rendered and interaction matrix; visual taste is separate."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
    contrast = Path("Visual_Contrast.js").read_text()
    output = Path(os.environ.get("VISUAL_OUTPUT_DIRECTORY", "/tmp/visual-proof"))
    output.mkdir(parents=True, exist_ok=True)
    views = json.loads(Path("Visual Views.json").read_text())
    measurements = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Capture every screen first, even if the first assertion fails.
        for view in views:
            for width in (320, 768, 1440):
                page = browser.new_page(viewport={"width":width,"height":1000})
                page.route("http://**/*", lambda r:r.abort())
                page.route("https://**/*", lambda r:r.abort())
                page.goto(Path(view+".html").resolve().as_uri())
                page.screenshot(path=str(output/f"{view}-{width}.png"), full_page=True)
                page.close()
        for view in views:
            for width in (320, 768, 1440):
                page = browser.new_page(viewport={"width":width,"height":1000})
                page.route("http://**/*", lambda r:r.abort())
                page.route("https://**/*", lambda r:r.abort())
                page.goto(Path(view+".html").resolve().as_uri())
                m=page.evaluate(r"""() => {
                  const box=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};};
                  const group=selector=>[...document.querySelectorAll(selector)].map(box);
                  return {overflow:document.documentElement.scrollWidth>innerWidth,body:parseFloat(getComputedStyle(document.body).fontSize),heading:parseFloat(getComputedStyle(document.querySelector('h1')).fontSize),padding:parseFloat(getComputedStyle(document.querySelector('main')).paddingLeft),controls:group('nav a,button,input,select'),cards:group('.cards article'),fields:group('.fields label'),split:group('.split > *'),panels:[...document.querySelectorAll('.panel,.cards article')].map(e=>parseFloat(getComputedStyle(e).paddingLeft)),gaps:[...document.querySelectorAll('.cards,.fields,.split')].map(e=>parseFloat(getComputedStyle(e).gap))};
                }""")
                measurements.append({"view":view,"width":width,**m})
                assert not m["overflow"], (view,width,"page overflow")
                assert m["body"]>=16 and m["heading"]>=28 and m["padding"]>=16
                assert min(page.evaluate(contrast, 'h1,h2,h3,p:not(:empty),a,button,td,th,label,input,select'))>=4.5, (view,width,"contrast")
                assert all(c["h"]>=44 and c["w"]>=44 for c in m["controls"]), (view,width,"targets")
                assert all(v>=16 for v in m["panels"]+m["gaps"])
                for key in ("cards","fields","split"):
                    boxes=m[key]
                    if width==320 and boxes:
                        assert all(b["y"]>=a["y"]+a["h"]+16 for a,b in zip(boxes,boxes[1:])), (view,key,"stacking")
                    if width==1440 and key in ("cards","split") and boxes:
                        assert len({round(b["y"]) for b in boxes})==1, (view,key,"desktop columns")
                    if width==1440 and key=="fields" and boxes:
                        assert len({round(b["x"]) for b in boxes})==2
                assert page.locator("nav a[aria-current=page]").count()==1
                # Exercise the complete keyboard order and every focusable control.
                controls=page.locator("a,button,input,select,[tabindex='0']")
                for index in range(controls.count()):
                    page.keyboard.press("Tab")
                    control=controls.nth(index)
                    assert control.is_visible() and control.evaluate("(e)=>e===document.activeElement"), (view,"keyboard routing")
                    assert control.evaluate("(e)=>getComputedStyle(e).outlineStyle!=='none' && parseFloat(getComputedStyle(e).outlineWidth)>=2"), (view,"focus")
                if view=="projects":
                    region=page.locator(".table-scroll")
                    if region.evaluate("(e)=>e.scrollWidth>e.clientWidth"):
                        assert region.evaluate("(e)=>['auto','scroll'].includes(getComputedStyle(e).overflowX)")
                        region.focus()
                        region.press("ArrowRight")
                        page.wait_for_function("document.querySelector('.table-scroll').scrollLeft > 0", timeout=1000)
                    page.locator("#filter").select_option("active")
                    assert page.locator("tbody tr:visible").count()==2
                    page.locator("#filter").select_option("all")
                    assert page.locator("tbody tr:visible").count()==3
                if view=="settings":
                    page.locator("input").first.fill("Updated workspace")
                    page.locator("#action").click()
                    assert page.locator("#status").inner_text()=="Settings saved"
                elif view!="overview":
                    page.locator("#action").click()
                    assert page.locator("#status").inner_text()=="Action completed"
                if view!="overview":
                    assert min(page.evaluate(contrast, '#status'))>=4.5, (view,width,"status contrast")
                # Actual navigation, not merely the presence of an href.
                for target in views:
                    page.locator(f"nav a[href='{target}.html']").click()
                    assert page.url.endswith("/"+target+".html")
                page.close()
        browser.close()
    (output/"Measurements.json").write_text(json.dumps(measurements,indent=2)+"\n")
    print("All four routes passed layout, contrast, focus, controls and navigation at all three widths.")
if __name__=="__main__":
    main()
