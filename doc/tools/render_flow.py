"""Render flow.mmd to flow.png using sync Playwright."""
from pathlib import Path
from playwright.sync_api import sync_playwright

code = Path(r"c:\SynologyDrive\LTIMindtree\Projects\東森\sensengo\doc\architecture\flow.mmd").read_text(encoding="utf-8")
html = f"""<!DOCTYPE html><html><head>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>body{{margin:0;padding:20px;background:white}}#c{{display:inline-block}}</style>
</head><body><div id="c"><pre class="mermaid">{code}</pre></div>
<script>mermaid.initialize({{startOnLoad:true,theme:"default",securityLevel:"loose"}});</script>
</body></html>"""

out_path = r"c:\SynologyDrive\LTIMindtree\Projects\東森\sensengo\doc\diagrams\flow.png"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 2400, "height": 2000}, device_scale_factor=2)
    page.set_content(html)
    page.wait_for_selector("svg", timeout=15000)
    page.wait_for_timeout(2000)
    c = page.query_selector("#c")
    box = c.bounding_box()
    print(f"Bounding box: {box}")
    page.screenshot(
        path=out_path,
        clip={"x": 0, "y": 0, "width": box["width"] + 40, "height": box["height"] + 40},
    )
    browser.close()
    size = Path(out_path).stat().st_size
    print(f"OK: flow.png ({size/1024:.1f} KB)")
