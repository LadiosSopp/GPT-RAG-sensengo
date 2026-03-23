"""Download mermaid.min.js and render both diagrams to PNG."""
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

DOC = Path(r"c:\SynologyDrive\LTIMindtree\Projects\東森\sensengo\doc")
MERMAID_JS = DOC / "tools" / "mermaid.min.js"

# Download mermaid.js if not present
if not MERMAID_JS.exists():
    print("Downloading mermaid.min.js...")
    urllib.request.urlretrieve(
        "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js",
        str(MERMAID_JS),
    )
    print(f"Downloaded: {MERMAID_JS.stat().st_size / 1024:.0f} KB")

mermaid_code = MERMAID_JS.read_text(encoding="utf-8")


def render(mmd_path: Path, png_path: Path):
    code = mmd_path.read_text(encoding="utf-8")
    # Use file:// URL for the local mermaid.js with ESM import
    mermaid_url = MERMAID_JS.as_uri()
    html = f"""<!DOCTYPE html><html><head>
<style>body{{margin:0;padding:20px;background:white}}#c{{display:inline-block}}</style>
</head><body><div id="c"><pre class="mermaid">{code}</pre></div>
<script type="module">
import mermaid from '{mermaid_url}';
mermaid.initialize({{startOnLoad:true,theme:"default",securityLevel:"loose"}});
</script>
</body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 2400, "height": 2000}, device_scale_factor=2
        )
        page.set_content(html, wait_until="networkidle")
        page.wait_for_selector("svg", timeout=15000)
        page.wait_for_timeout(2000)
        c = page.query_selector("#c")
        box = c.bounding_box()
        print(f"  Box: w={box['width']:.0f} h={box['height']:.0f}")
        page.screenshot(
            path=str(png_path),
            clip={
                "x": 0,
                "y": 0,
                "width": box["width"] + 40,
                "height": box["height"] + 40,
            },
        )
        browser.close()
    size = png_path.stat().st_size
    print(f"  OK: {png_path.name} ({size / 1024:.1f} KB)")


print("=== Architecture ===")
render(DOC / "architecture" / "architecture.mmd", DOC / "diagrams" / "architecture.png")
print("=== Flow ===")
render(DOC / "architecture" / "flow.mmd", DOC / "diagrams" / "flow.png")
