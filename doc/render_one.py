"""Render a single Mermaid .mmd file to PNG."""
import asyncio, sys
from pathlib import Path
from playwright.async_api import async_playwright

HTML_TEMPLATE = """<!DOCTYPE html>
<html><head>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
  body {{ margin: 0; padding: 20px; background: white; }}
  #container {{ display: inline-block; }}
</style>
</head><body>
<div id="container">
  <pre class="mermaid">{code}</pre>
</div>
<script>
  mermaid.initialize({{ startOnLoad: true, theme: 'default', securityLevel: 'loose' }});
</script>
</body></html>"""

async def render(mmd_path: str, png_path: str):
    code = Path(mmd_path).read_text(encoding="utf-8")
    html = HTML_TEMPLATE.format(code=code)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": 2400, "height": 1600},
            device_scale_factor=2,
        )
        await page.set_content(html)
        await page.wait_for_selector("svg", timeout=15000)
        await asyncio.sleep(2)
        container = await page.query_selector("#container")
        box = await container.bounding_box()
        await page.screenshot(
            path=png_path,
            clip={"x": 0, "y": 0, "width": box["width"] + 40, "height": box["height"] + 40},
        )
        size = Path(png_path).stat().st_size
        await browser.close()
        print(f"OK: {png_path} ({size/1024:.1f} KB)")

if __name__ == "__main__":
    mmd = sys.argv[1]
    png = sys.argv[2]
    asyncio.run(render(mmd, png))
