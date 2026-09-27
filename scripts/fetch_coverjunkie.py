#!/usr/bin/env python
"""Fetch New York Times Magazine covers from Coverjunkie's public catalogue
(coverjunkie.com -- the same anonymous API its website uses), ~2008 to the present.

  .venv/bin/python scripts/fetch_coverjunkie.py [--limit N] [--remote r2:bucket]

Coverjunkie's cover_date is when they posted it, not the issue date, so the printed
date under the masthead ("August 16, 2020") is OCR'd when the image is large enough;
otherwise the posting date is kept and the entry is marked approximate.
"""
import argparse, datetime, io, json, re, sys, time, urllib.parse
import requests
from PIL import Image
import extract_ia as E
import curate as C
import numpy as np

SUPABASE = 'https://vadwevdvhdurlagmjput.supabase.co'
MAGAZINE = 'New York Times Magazine'
MONTHS = {m: i for i, m in enumerate(['january','february','march','april','may','june','july','august','september','october','november','december'], 1)}
DATE_RX = re.compile(r'\b(' + '|'.join(MONTHS) + r')\.?\s*(\d{1,2})\s*,?\s*((?:19|20)\d\d)\b', re.I)

def anon_key():
    html = requests.get('https://coverjunkie.com/', headers={'User-Agent': 'Mozilla/5.0'}, timeout=60).text
    js = re.search(r'src="(/assets/index-[^"]+\.js)"', html).group(1)
    bundle = requests.get('https://coverjunkie.com' + js, headers={'User-Agent': 'Mozilla/5.0'}, timeout=60).text
    return re.search(r'(eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,})', bundle).group(1)

def catalogue(key):
    h = {'apikey': key, 'Authorization': 'Bearer ' + key, 'User-Agent': 'Mozilla/5.0'}
    url = f'{SUPABASE}/rest/v1/covers?select=id,slug,title,cover_date,image_url,thumbnail_url&magazine=eq.{urllib.parse.quote(MAGAZINE)}&order=cover_date.asc&limit=5000'
    return requests.get(url, headers=h, timeout=60).json()

def printed_date(jpeg):
    """Issue date printed on the cover (small type under the masthead, sometimes at the
    foot). Each strip is upscaled to 2400px wide before OCR so the small line resolves."""
    im = Image.open(io.BytesIO(jpeg)).convert('RGB'); W, H = im.size
    for y0, y1 in ((0, 0.28), (0.72, 1.0), (0.28, 0.72)):
        strip = im.crop((0, int(H * y0), W, int(H * y1)))
        strip = strip.resize((2400, round(strip.height * 2400 / W)), Image.LANCZOS)
        buf = io.BytesIO(); strip.save(buf, 'JPEG', quality=95)
        for text, _ in E.ocr_top(buf.getvalue(), frac=1.0):
            m = DATE_RX.search(text)
            if m:
                try: return datetime.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
                except ValueError: pass
    return None

def nearest_sunday(d):
    off = (6 - d.weekday()) % 7          # days forward to Sunday
    return d + datetime.timedelta(days=off) if off <= 3 else d - datetime.timedelta(days=7 - off)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--limit', type=int); ap.add_argument('--remote'); a = ap.parse_args()
    if a.remote: E.REMOTE = a.remote
    STATE = E.ROOT / 'state_cj.json'; ia_state = json.loads(E.STATE.read_text()) if E.STATE.exists() else {}
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    done_ids = {v.get('cj_id') for v in state.values() if v.get('source') == 'coverjunkie'}
    rows = catalogue(anon_key()); E.log(f'coverjunkie: {len(rows)} {MAGAZINE} covers listed')
    hashes = {p.stem: np.unpackbits(C.dhash(p)) for p in E.THUMBS.glob('*/*.jpg')}   # for duplicate detection
    n = 0
    for r in rows:
        if r['id'] in done_ids or not r.get('image_url'): continue
        img = E.get(r['image_url'])
        if not img: E.log(f"cj {r['cover_date']}: download failed"); continue
        posted = datetime.date.fromisoformat(r['cover_date'][:10])
        try: Image.open(io.BytesIO(img.content)).verify()
        except Exception: E.log(f"cj {r['cover_date'][:10]}: unreadable image, skipped ({r['image_url'][-40:]})"); continue
        skip = None
        if C.color_share(io.BytesIO(img.content)) < C.COLOR_MIN: skip = 'black-and-white'
        else:
            h = np.unpackbits(C.dhash(io.BytesIO(img.content)))
            dup = next((k for k, hk in hashes.items() if (h != hk).sum() <= C.HAMMING_MAX), None)
            if dup: skip = f'duplicate of {dup}'
        if skip:
            state[f'cj:{r["id"]}'] = {'status': 'skipped', 'source': 'coverjunkie', 'cj_id': r['id'], 'reason': skip}
            STATE.write_text(json.dumps(state, indent=1, sort_keys=True)); E.log(f"cj {r['cover_date'][:10]}: skipped, {skip}"); continue
        d = printed_date(img.content); how = 'printed date'
        if not d or not (-7 <= (posted - d).days <= 400):    # OCR hit something else, or a date after posting
            d, how = posted, 'post date (approx)'
        key = str(d); suffix = ''
        if key in ia_state: continue                           # the IA scan of that issue is better
        while key + suffix in state:                           # second cover for the same issue
            suffix = f'-{int(suffix[1:] or 1) + 1}'
        dst = E.COVERS / str(d.year) / f'{key}{suffix}.jpg'; dst.parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(io.BytesIO(img.content)); im = im.convert('RGB'); im.save(dst, quality=90, optimize=True)
        E.make_thumb(dst, key + suffix)
        if E.REMOTE:
            E.upload(dst, f'covers/{d.year}/{key}{suffix}.jpg'); E.upload(E.THUMBS / str(d.year) / f'{key}{suffix}.jpg', f'thumb/{d.year}/{key}{suffix}.jpg', keep=True)
        state[key + suffix] = {'status': 'ok', 'source': 'coverjunkie', 'cj_id': r['id'], 'cj_date': r['cover_date'][:10], 'dated_by': how, 'px': im.size}
        STATE.write_text(json.dumps(state, indent=1, sort_keys=True))
        hashes[key + suffix] = np.unpackbits(C.dhash(dst))
        E.log(f'cj {key}{suffix} ({how}; posted {posted}) {im.size[0]}x{im.size[1]}')
        n += 1; time.sleep(0.6)
        if a.limit and n >= a.limit: break
    E.build_index()

if __name__ == '__main__': main()
