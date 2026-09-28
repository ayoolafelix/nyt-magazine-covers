#!/usr/bin/env python3
"""Find scan pages that hold more than one cover.

The grid draws every page it is given, and a handful of the Coverjunkie scans
are not a single cover. Some are contact sheets or magazine pages carrying four
covers at once, which show up in the grid as one tile with a masthead repeated
inside it. Those cannot be fixed by changing the cell aspect: there is no one
cover in the image to frame.

A single cover has one masthead, in its top band. This scores each page by how
much the top strip resembles the other strips: a page made of stacked covers
repeats itself, so its bands correlate, while a single cover photograph does
not. Combined with the width test, a page has to be both narrow for its height
and self-similar to be called multi-up, which keeps real covers that merely
happen to be tall.
"""
import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANDS = 4
STRIP_H = 10
STRIP_W = 24


def profile(path, bands=BANDS):
    """Mean luminance of each horizontal band, plus a coarse thumbnail."""
    im = Image.open(path).convert("L")
    W, H = im.size
    means = []
    for i in range(bands):
        top = int(H * i / bands)
        bot = max(top + 1, int(H * (i + 1) / bands))
        st = im.crop((0, top, W, bot)).resize((STRIP_W, STRIP_H), Image.LANCZOS)
        a = np.asarray(st, dtype=np.float64)
        means.append(float(a.mean()))
    thumb = np.asarray(
        im.convert("L").resize((12, 16), Image.LANCZOS), dtype=np.float64)
    return np.array(means), thumb


def similarity(path):
    """How much the page's own bands resemble one another, 0 = unlike, 1 = same."""
    means, thumb = profile(path)
    m = means - means.mean()
    denom = float(np.sqrt((m ** 2).sum()))
    band_sim = 1.0 - (denom / 255.0) if denom else 0.0

    # A page of stacked covers repeats its composition, so the upper and lower
    # halves of a downsampled thumbnail correlate. A single photograph does not.
    half = thumb.shape[0] // 2
    top_v = thumb[:half].reshape(-1)
    bot_v = thumb[half:].reshape(-1)
    a = top_v - top_v.mean()
    b = bot_v - bot_v.mean()
    den = float(np.sqrt((a ** 2).sum() * (b ** 2).sum()))
    half_corr = float((a * b).sum() / den) if den else 0.0
    return band_sim, half_corr


def main():
    covers = json.load(open(os.path.join(ROOT, "web", "public", "covers.json")))
    px_by_id = {c["id"]: c.get("px") for c in
                json.load(open(os.path.join(ROOT, "covers.json")))["covers"]}
    # The cell aspect the grid draws at; anything much narrower is a candidate.
    AR = 0.8215
    width_cut = 0.85

    scored = []
    for c in covers:
        px = px_by_id.get(c["d"])
        if not px or len(px) != 2 or not px[1]:
            continue
        ar = px[0] / px[1]
        if ar >= width_cut:
            continue
        path = os.path.join(ROOT, "thumb", c["d"][:4], f"{c['d']}.jpg")
        if not os.path.exists(path):
            continue
        band_sim, half_corr = similarity(path)
        scored.append((half_corr, band_sim, ar, c["d"], px))

    scored.sort(reverse=True)
    print(f"  covers narrower than {width_cut}: {len(scored)}")
    print(f"  {'half-corr':>9} {'band-sim':>9} {'ar':>6}  id             px")
    for hc, bs, ar, d, px in scored[:22]:
        flag = "  <-- self-similar" if hc > 0.72 else ""
        print(f"  {hc:9.3f} {bs:9.3f} {ar:6.3f}  {d}  {px}{flag}")

    cut = float(os.environ.get("SELF_SIM_CUT", "0.72"))
    flagged = [s for s in scored if s[0] > cut]
    print(f"\n  self-similar above {cut}: {len(flagged)} covers")
    print("  " + " ".join(s[3] for s in flagged))


if __name__ == "__main__":
    main()
