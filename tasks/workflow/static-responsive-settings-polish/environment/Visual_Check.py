"""Rendered acceptance checks; passing is not a subjective design endorsement."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
    contrast = Path("Visual_Contrast.js").read_text()
    output = Path(os.environ.get("VISUAL_OUTPUT_DIRECTORY", "/tmp/visual-proof"))
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Retain every view even when the first layout assertion fails below.
        for width in (320, 768, 1440):
            page = browser.new_page(viewport={"width": width, "height": 1000}, device_scale_factor=1)
            page.route("http://**/*", lambda route: route.abort())
            page.route("https://**/*", lambda route: route.abort())
            page.goto(Path("index.html").resolve().as_uri())
            page.screenshot(path=str(output / f"settings-{width}.png"), full_page=True)
            page.close()
        for width in (320, 768, 1440):
            page = browser.new_page(viewport={"width": width, "height": 1000}, device_scale_factor=1)
            page.route("http://**/*", lambda route: route.abort())
            page.route("https://**/*", lambda route: route.abort())
            page.goto(Path("index.html").resolve().as_uri())
            measurements = page.evaluate(r"""() => {
              const boxes=[...document.querySelectorAll('article')].map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};});
              const buttons=[...document.querySelectorAll('button')].map(e=>{const r=e.getBoundingClientRect();return {w:r.width,h:r.height};});
              return {overflow:document.documentElement.scrollWidth>innerWidth,boxes,buttons,heading:parseFloat(getComputedStyle(document.querySelector('h1')).fontSize),body:parseFloat(getComputedStyle(document.body).fontSize),gap:parseFloat(getComputedStyle(document.querySelector('.cards')).gap)};
            }""")
            results.append({"width":width,**measurements})
            assert not measurements['overflow'], 'horizontal overflow'
            assert measurements['body'] >= 16 and measurements['heading'] >= measurements['body'] * 1.5, 'readability/hierarchy'
            assert measurements['gap'] >= 16, 'crowded cards'
            assert min(page.evaluate(contrast, 'h1,h2,p:not(:empty),button')) >= 4.5, 'insufficient text contrast'
            assert all(b['h'] >= 44 and b['w'] >= 44 for b in measurements['buttons']), 'small targets'
            boxes=measurements['boxes']
            assert len(boxes)==3
            if width==320:
                assert all(boxes[i+1]['y']>=boxes[i]['y']+boxes[i]['h']+16 for i in (0,1)), 'mobile stacking'
            if width==1440:
                assert len({round(b['y']) for b in boxes})==1, 'desktop alignment'
            for index in range(3):
                page.keyboard.press('Tab')
                assert page.locator('button').nth(index).evaluate('(e)=>e===document.activeElement'), 'keyboard order'
                style=page.locator('button').nth(index).evaluate('(e)=>({style:getComputedStyle(e).outlineStyle,width:parseFloat(getComputedStyle(e).outlineWidth)})')
                assert style['style']!='none' and style['width']>=2, 'missing visible focus'
            page.locator('button').first.click()
            assert page.locator('#status').inner_text()=='Update profile selected', 'interaction regression'
            assert min(page.evaluate(contrast, '#status')) >= 4.5, 'status contrast'
            page.close()
        browser.close()
    (output/'Measurements.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Rendered acceptance passed at 320, 768 and 1440 pixels. Visual review remains separate.')

if __name__=='__main__':
    main()
