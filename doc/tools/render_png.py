"""Render Mermaid diagrams to PNG via local HTTP server + Playwright."""
import threading
import http.server
import functools
from pathlib import Path
from playwright.sync_api import sync_playwright

DOC = Path(r"c:\SynologyDrive\LTIMindtree\Projects\東森\sensengo\doc")
PORT = 18765


def start_server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DOC))
    srv = http.server.HTTPServer(("127.0.0.1", PORT), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def build_html(mmd_code: str) -> str:
    return f"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<script src="./tools/mermaid.min.js"></script>
<style>
body{{margin:0;padding:20px;background:white;overflow:visible;font-family:"Microsoft JhengHei","微軟正黑體","Noto Sans TC",sans-serif}}
#c{{display:inline-block;overflow:visible}}
#c svg{{max-width:none !important}}
#c svg text,#c svg .nodeLabel,#c svg .edgeLabel,#c svg .label{{font-family:"Microsoft JhengHei","微軟正黑體","Noto Sans TC",sans-serif !important}}
</style>
</head><body><div id="c"><pre class="mermaid">{mmd_code}</pre></div>
<script>
mermaid.initialize({{startOnLoad:true,theme:"default",securityLevel:"loose",flowchart:{{useMaxWidth:false,htmlLabels:true}},sequence:{{useMaxWidth:false}},themeVariables:{{fontFamily:'"Microsoft JhengHei","微軟正黑體","Noto Sans TC",sans-serif'}}}});
</script>
</body></html>"""


def render(page, mmd_path: Path, png_path: Path):
    code = mmd_path.read_text(encoding="utf-8")
    html_path = DOC / "_temp.html"
    html_path.write_text(build_html(code), encoding="utf-8")
    
    # Capture console errors
    errors = []
    page.on("console", lambda msg: errors.append(f"[{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)
    page.on("pageerror", lambda err: errors.append(f"[pageerror] {err}"))
    
    page.goto(f"http://127.0.0.1:{PORT}/_temp.html", wait_until="networkidle")
    page.wait_for_timeout(5000)
    
    if errors:
        for e in errors:
            print(f"  JS: {e[:200]}")
    
    # Check what's actually in the page
    html_content = page.query_selector("#c").inner_html()
    print(f"  Container inner HTML length: {len(html_content)}")
    print(f"  Has SVG: {'<svg' in html_content}")
    
    # Get SVG actual dimensions via JS
    dims = page.evaluate("""() => {
        const svg = document.querySelector('svg');
        if (!svg) return null;
        const rect = svg.getBoundingClientRect();
        return {width: rect.width, height: rect.height, svgWidth: svg.getAttribute('width'), viewBox: svg.getAttribute('viewBox')};
    }""")
    print(f"  SVG dims: {dims}")
    
    # Set page viewport to fit the SVG
    if dims and dims.get("viewBox"):
        vb = dims["viewBox"].split()
        w = float(vb[2]) if len(vb) >= 3 else dims["width"]
        h = float(vb[3]) if len(vb) >= 4 else dims["height"]
        # Resize viewport to fit
        page.set_viewport_size({"width": int(w) + 60, "height": int(h) + 60})
        page.wait_for_timeout(1000)
    
    svg_el = page.query_selector("svg")
    box = svg_el.bounding_box() if svg_el else page.query_selector("#c").bounding_box()
    print(f"  Box: w={box['width']:.0f} h={box['height']:.0f}")
    page.screenshot(
        path=str(png_path),
        clip={"x": 0, "y": 0, "width": box["width"] + 40, "height": box["height"] + 40},
    )
    size = png_path.stat().st_size
    print(f"  OK: {png_path.name} ({size / 1024:.1f} KB)")
    html_path.unlink(missing_ok=True)


def main():
    srv = start_server()
    print(f"Server on port {PORT}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 2400, "height": 2000}, device_scale_factor=2
        )
        
        print("=== Architecture ===")
        render(page, DOC / "architecture" / "architecture.mmd", DOC / "diagrams" / "architecture.png")
        
        print("=== Flow ===")
        render(page, DOC / "architecture" / "flow.mmd", DOC / "diagrams" / "flow.png")
        
        browser.close()
    srv.shutdown()
    print("Done!")


if __name__ == "__main__":
    main()
