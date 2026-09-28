#!/usr/bin/env python3
"""Pad every grid texture to the grid's cell aspect, using the cover's own edge.

The grid draws with contain(), so any texture whose aspect differs from the
cell's gets letterboxed: a band of bare canvas above and below, or either side.
Measured across the archive that band is invisible on 87% of covers (under 2%)
but reaches 43% on the worst, and those are the tiles that read as broken.

Two different things were causing it, and only one is a defect:

  - Some scans are of a bound volume, so the printed cover sits inside the
    photographed page with the spine and paper edges around it. Those are
    legitimate covers; the padding is the scan's own border.
  - A few scans hold more than one cover, or a square layout, where no amount
    of padding makes them portrait.

Padding here extends the cover's outermost pixels outward, edge-to-edge, so
the texture lands on exactly the cell aspect and contain() becomes an exact
fit. Nothing is cropped, the full cover is still shown, and the bar disappears
because it is now a continuation of the artwork's own edge rather than bare
canvas. Deterministic and idempotent: re-running reproduces the same file.
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRID = os.path.join(ROOT, "web", "public", "grid")
WIDTH = int(sys.argv[1]) if len(sys.argv) > 1 else 420
# must match COVER_AR in web/src/main.js
AR = 0.8215
JOBS = 8


def edge_fill(im, target_ar):
    """Grow an image to target_ar by replicating its border outwards."""
    w, h = im.size
    cur = w / h
    if abs(cur - target_ar) < 0.0015:
        return im, False
    if cur < target_ar:
        # too narrow: add columns, taking each new column from the nearest edge
        need = int(round(h * target_ar)) - w
        if need <= 0:
            # within a pixel of the target already; round() cannot improve it
            return im, False
        left = need // 2
        right = need - left
        arr = np.asarray(im)
        lcol = np.repeat(arr[:, :1], left, axis=1)
        rcol = np.repeat(arr[:, -1:], right, axis=1)
        out = np.concatenate([lcol, arr, rcol], axis=1)
    else:
        # too wide: add rows the same way
        need = int(round(w / target_ar)) - h
        if need <= 0:
            return im, False
        top = need // 2
        bottom = need - top
        arr = np.asarray(im)
        trow = np.repeat(arr[:1, :], top, axis=0)
        brow = np.repeat(arr[-1:, :], bottom, axis=0)
        out = np.concatenate([trow, arr, brow], axis=0)
    return Image.fromarray(out), True


def convert(job):
    src, dst = job
    if not os.path.exists(src):
        return dst, 0, False, "no-source"
    im = Image.open(src).convert("RGB")
    if im.width > WIDTH:
        h = round(im.height * WIDTH / im.width)
        im = im.resize((WIDTH, h), Image.LANCZOS)
    padded, changed = edge_fill(im, AR)
    if not changed:
        return dst, 0, False, "exact"
    tmp = dst + ".tmp.png"
    padded.save(tmp)
    out = dst + ".tmp.webp"
    r = subprocess.run(["cwebp", "-quiet", "-m", "4", "-q", "68",
                        "-sharp_yuv", tmp, "-o", out],
                       capture_output=True)
    ok = r.returncode == 0 and os.path.exists(out)
    if ok:
        os.replace(out, dst)
    for f in (tmp, out):
        if os.path.exists(f):
            os.remove(f)
    if not ok:
        return dst, os.path.getsize(dst) if os.path.exists(dst) else 0, False, \
            f"cwebp: {r.stderr.decode()[:60]}"
    return dst, os.path.getsize(dst), True, "padded"


def main():
    covers = json.load(open(os.path.join(ROOT, "web", "public", "covers.json")))
    jobs = []
    for c in covers:
        src = os.path.join(ROOT, "thumb", c["d"][:4], f"{c['d']}.jpg")
        dst = os.path.join(GRID, c["d"][:4], f"{c['d']}.webp")
        if os.path.exists(src) and os.path.exists(dst):
            jobs.append((src, dst))
    print(f"checking {len(jobs)} grid textures against cell aspect {AR}")

    padded = exact = other = 0
    total = 0
    with cf.ThreadPoolExecutor(JOBS) as ex:
        for dst, size, was_padded, note in ex.map(convert, jobs):
            if was_padded:
                padded += 1
                total += size
            elif note == "exact":
                exact += 1
            else:
                other += 1
                print(f"    skipped {os.path.basename(dst)}: {note}")
    print(f"  padded to aspect : {padded}")
    print(f"  already exact    : {exact}")
    print(f"  skipped          : {other}")
    if total:
        print(f"  mean padded size : {total/padded:.0f} KB")


if __name__ == "__main__":
    main()
