#!/usr/bin/env python3
"""Compose the favicon from a cover's masthead band.

A square crop of the whole cover is mush at 32px. The New York Times
Magazine masthead is the one element that stays readable when reduced, but it
is a wide strip, so the strip is pasted onto a square paper-coloured field
rather than stretched: stretching would distort the blackletter, and cropping
the strip square would cut the ascenders off.
"""
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "public")
PAPER = (247, 245, 240)


def main():
    cover_id = sys.argv[1] if len(sys.argv) > 1 else "2026-09-08"
    src_path = os.path.join(ROOT, "covers", cover_id[:4], f"{cover_id}.jpg")
    if not os.path.exists(src_path):
        cand = sorted(os.listdir(os.path.join(ROOT, "covers", cover_id[:4])))
        src_path = os.path.join(ROOT, "covers", cover_id[:4], cand[0])
        print(f"  {cover_id} not found, using {os.path.basename(src_path)}")

    src = Image.open(src_path).convert("RGB")
    W, H = src.size

    y0, y1 = int(H * 0.018), int(H * 0.135)
    band = src.crop((0, y0, W, y1))
    bw, bh = band.size

    S = max(bw, int(bh * 1.9))
    canvas = Image.new("RGB", (S, S), PAPER)
    canvas.paste(band, ((S - bw) // 2, (S - bh) // 2))

    os.makedirs(OUT, exist_ok=True)
    canvas.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "icon-512.png"))
    canvas.resize((192, 192), Image.LANCZOS).save(os.path.join(OUT, "apple-touch-icon.png"))
    canvas.resize((32, 32), Image.LANCZOS).save(os.path.join(OUT, "favicon-32x32.png"))

    import base64
    b64 = base64.b64encode(open(os.path.join(OUT, "icon-512.png"), "rb").read()).decode()
    with open(os.path.join(OUT, "favicon.svg"), "w") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
                f'<image width="512" height="512" href="data:image/png;base64,{b64}"/>'
                '</svg>')

    print(f"  source {W}x{H}; masthead band {bw}x{bh}; field {S}x{S}")
    for f in ("favicon-32x32.png", "apple-touch-icon.png", "icon-512.png", "favicon.svg"):
        p = os.path.join(OUT, f)
        print(f"    {f:24} {os.path.getsize(p):>7} B")


if __name__ == "__main__":
    main()
