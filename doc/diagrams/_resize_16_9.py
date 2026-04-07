from PIL import Image, ImageChops, ImageDraw, ImageFont
import os

os.chdir(r"c:\SynologyDrive\LTIMindtree\Projects\東森\sensengo\doc\diagrams")
TARGET_W, TARGET_H = 3840, 2160
PAD = 60

# Regenerate from mermaid at high res
os.system("mmdc -i architecture.mmd -o _tmp_arch.png -w 4000 -b white --scale 3")
os.system("mmdc -i sales-recommendation-flow.mmd -o _tmp_flow.png -w 5000 -b white --scale 3")

for src, dst in [("_tmp_arch.png", "architecture.png"), ("_tmp_flow.png", "sales-recommendation-flow.png")]:
    img = Image.open(src).convert("RGB")
    w, h = img.size
    print(f"{dst}: raw {w}x{h}")

    # Auto-crop whitespace
    white = Image.new("RGB", img.size, (255, 255, 255))
    diff = ImageChops.difference(img, white)
    bbox = diff.convert("L").getbbox()
    if bbox:
        b = 20
        bbox = (max(0, bbox[0]-b), max(0, bbox[1]-b),
                min(w, bbox[2]+b), min(h, bbox[3]+b))
        cropped = img.crop(bbox)
    else:
        cropped = img
    cw, ch = cropped.size
    ratio = cw / ch
    print(f"  cropped: {cw}x{ch}, ratio: {ratio:.2f}")

    # Scale to fill available area
    avail_w = TARGET_W - 2 * PAD
    avail_h = TARGET_H - 2 * PAD
    scale = min(avail_w / cw, avail_h / ch)
    new_w = int(cw * scale)
    new_h = int(ch * scale)
    resized = cropped.resize((new_w, new_h), Image.LANCZOS)

    # Place on white 16:9 canvas (centered)
    canvas = Image.new("RGB", (TARGET_W, TARGET_H), (255, 255, 255))
    px = (TARGET_W - new_w) // 2
    py = (TARGET_H - new_h) // 2
    canvas.paste(resized, (px, py))
    canvas.save(dst, dpi=(300, 300))
    fsize = os.path.getsize(dst) / 1024
    print(f"  -> {TARGET_W}x{TARGET_H} ({fsize:.0f} KB)")

# Cleanup
for f in ["_tmp_arch.png", "_tmp_flow.png"]:
    if os.path.exists(f):
        os.remove(f)

print("All done!")
