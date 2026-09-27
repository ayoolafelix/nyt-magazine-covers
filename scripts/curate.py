#!/usr/bin/env python
"""Curate the archive: drop black-and-white covers and near-duplicate covers.

  .venv/bin/python scripts/curate.py            # report only
  .venv/bin/python scripts/curate.py --apply    # delete the files, record in data/curation.json

Colour: share of pixels with HSV saturation > 0.18 (and not near-black); below
COLOR_MIN the cover is treated as black-and-white. Duplicates: 16x16 difference
hash of the thumbnail; pairs within HAMMING_MAX bits are the same cover, and the
larger image (then the better-dated one) is kept.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
COLOR_MIN, HAMMING_MAX = 0.032, 44
# photographs of old physical issues: yellowed paper reads as colour, but the printed cover is B&W
MANUAL_BW = ['1898-10-08', '1943-08-16', '1944-06-13', '1944-06-13-2', '1945-04-15', '1945-06-13', '1948-02-19',
             '1948-02-22', '1948-04-18', '1952-04-14', '1991-06-17']

def color_share(path):
    im = Image.open(path).convert('RGB'); im.thumbnail((200, 300))
    hsv = np.asarray(im.convert('HSV'), dtype=np.float32) / 255
    s, v = hsv[..., 1], hsv[..., 2]
    return float(((s > 0.18) & (v > 0.12)).mean())

def dhash(path, n=16):
    im = Image.open(path).convert('L').resize((n + 1, n), Image.LANCZOS)
    a = np.asarray(im, dtype=np.int16)
    return np.packbits((a[:, 1:] > a[:, :-1]).ravel())

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--apply', action='store_true'); a = ap.parse_args()
    state = {}
    for f in sorted(ROOT.glob('state*.json')): state.update(json.loads(f.read_text()))
    thumbs = sorted(p for p in ROOT.glob('thumb/*/*.jpg'))
    info = {}
    for p in thumbs:
        k = p.stem; st = state.get(k, {})
        info[k] = {'color': color_share(p), 'hash': dhash(p), 'px': (st.get('px') or [0, 0])[0], 'exact': 'printed' in st.get('dated_by', ''), 'src': st.get('source')}
    bw = sorted(k for k, v in info.items() if v['color'] < COLOR_MIN or k in MANUAL_BW)
    keys = [k for k in info if k not in set(bw)]
    H = np.stack([np.unpackbits(info[k]['hash']) for k in keys]) if keys else np.zeros((0, 256))
    dupes = {}                                             # removed -> kept
    for i in range(len(keys)):
        if keys[i] in dupes: continue
        d = (H[i] != H[i + 1:]).sum(axis=1)
        for j in np.nonzero(d <= HAMMING_MAX)[0]:
            kj = keys[i + 1 + j]
            if kj in dupes: continue
            a_, b_ = info[keys[i]], info[kj]
            keep_i = (a_['px'], a_['exact']) >= (b_['px'], b_['exact'])
            loser, winner = (kj, keys[i]) if keep_i else (keys[i], kj)
            dupes[loser] = winner
            if not keep_i: break
    print(f'{len(info)} covers: {len(bw)} black-and-white, {len(dupes)} duplicates -> {len(info) - len(bw) - len(dupes)} remain')
    print('b&w by decade:', {d: sum(k.startswith(d) for k in bw) for d in sorted({k[:3] for k in bw})})
    border = sorted((v['color'], k) for k, v in info.items() if COLOR_MIN * 0.6 < v['color'] < COLOR_MIN * 2.5)
    print('borderline colour (share, id):', [(round(c, 3), k) for c, k in border[:24]])
    print('duplicate pairs (removed -> kept):', list(dupes.items())[:30])
    (ROOT / 'data').mkdir(exist_ok=True); cf = ROOT / 'data' / 'curation.json'
    prev = json.loads(cf.read_text()) if cf.exists() else {}
    rec = {'black_and_white': sorted(set(prev.get('black_and_white', [])) | set(bw)),
           'duplicates': {**prev.get('duplicates', {}), **dupes},
           'color_share': {**prev.get('color_share', {}), **{k: round(v['color'], 4) for k, v in info.items()}}}
    if a.apply: cf.write_text(json.dumps(rec, indent=1))
    if a.apply:
        for k in bw + list(dupes):
            for d in ('covers', 'thumb'): (ROOT / d / k[:4] / f'{k}.jpg').unlink(missing_ok=True)
        print('removed', len(bw) + len(dupes), 'covers')

if __name__ == '__main__': main()
