# The New York Times Magazine — Covers

An infinite, draggable archive of *New York Times Magazine* covers, collected
automatically from public online sources and curated to **colour covers only, no
duplicates** — a reference for the magazine's cover design.

**Site:** https://nyt-magazine-covers.vercel.app

**520 covers**, one per issue, 1948–2026.

## The gallery

`web/` holds a WebGL grid: a rigid lattice where one offset drives every cell,
so row alignment and uniform spacing are structural rather than tuned.
Covers are drawn with `contain()`, never `cover()`, so **no cover is ever
cropped** — the cell is sized to the archive's own median proportion
(0.8215) and the 93% of covers inside the 0.78–0.87 band fill it exactly,
while outliers letterbox instead of losing artwork.

Click a cover for a right-hand pane (a bottom sheet on mobile) showing the
cover, the issue date, and whatever credits the scan carries. The pane
background is tinted with the cover's own dominant colour. Rows appear only
when they have a value: 166 of 520 covers name who made the cover image, so
the other 354 show no credit row rather than an empty heading.

`web/verify-grid.mjs` is the invariant harness. It reads `PARALLAX_SPAN`,
`PARALLAX_PERIOD` and `ROW_SPARE` out of `main.js` so it cannot drift from
the source, and checks 1,440 scroll positions across 10 viewports.

### Building

```bash
python3 scripts/build_webgl_index.py   # covers.json + meta.json into web/public/
.venv/bin/python scripts/make_favicon.py
npm --prefix web install && npm --prefix web run build
node web/verify-grid.mjs
```

`build_webgl_index.py` also **collapses repeat scans of the same issue**,
keeping the largest: the archive holds 658 scans but only 520 distinct issue
dates, and one date had been scanned 16 times. A chronological grid that
steps through 16 copies of one cover is a stall, and the perceptual-hash
dedup could not catch these because separate physical copies of an issue
differ in paper tone and crop.

## Where the covers come from

## Where the covers come from

| Era | Source | How |
|---|---|---|
| 1896–1930 | Public-domain Sunday issues on the [Internet Archive](https://archive.org/details/pub_new-york-times-magazine) | `scripts/extract_ia.py` OCRs the top of every page of each Sunday scan (macOS Vision) and keeps the page whose big subtitle says MAGAZINE. These are black-and-white microfilm scans, so they are **excluded from the curated archive**; the extractor is kept for anyone who wants them. |
| 2008–today | [Coverjunkie](https://coverjunkie.com/magazines/new-york-times-magazine/)'s public catalogue | `scripts/fetch_coverjunkie.py`. Coverjunkie records when a cover was *posted*, not the issue date; the date printed on the cover is OCR'd when legible, otherwise the posting date is kept and the cover is marked ≈ approximate. Credits and descriptions come with the record. |
| 1931–2007 | — | Only in the NYT's own TimesMachine; nothing public carries them systematically. |

## Curation

`scripts/curate.py` measures each cover's colour (share of saturated pixels) and a
perceptual hash of its thumbnail. Black-and-white covers and near-duplicate posts are
removed; the decisions are recorded in `data/curation.json`. The Coverjunkie fetcher
applies the same two filters as it downloads.

## Layout

```
index.html          the gallery (infinite grid, detail panel)
covers.json         index with per-cover details, built by scripts/build_index.py
covers/YYYY/        full-size covers
thumb/YYYY/         600px thumbnails used by the grid
scripts/            fetchers + index builder (Python, see .venv setup below)
state.json          Internet Archive extraction bookkeeping
state_cj.json       Coverjunkie bookkeeping
```

The site on Vercel contains only `index.html` and `covers.json`; images are served from
this repository through the jsDelivr CDN.

## Running the fetchers

```bash
python3 -m venv .venv && .venv/bin/pip install pillow numpy requests pyobjc-framework-Vision pyobjc-framework-Quartz
.venv/bin/python scripts/extract_ia.py            # 1896–1930 (macOS only: uses Vision OCR)
.venv/bin/python scripts/fetch_coverjunkie.py     # 2008–today
.venv/bin/python scripts/curate.py --apply        # drop black-and-white + duplicate covers
.venv/bin/python scripts/build_index.py           # rebuild covers.json
```

## Gallery

Drag in any direction, scroll, or use the arrow keys; the grid wraps infinitely and is laid
out chronologically. Click a cover for the full-size image, date, era, source, credits and
links to the original scan or Coverjunkie entry. Mechanics after Codrops'
[Infinite Layers Grid](https://tympanus.net/Tutorials/InfiniteLayersGrid/) and layout after
[Elastic Grid Scroll](https://tympanus.net/Tutorials/ElasticGridScroll/index2.html).

Covers are © The New York Times Company and are collected here for design reference.
