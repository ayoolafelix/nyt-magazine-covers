#!/usr/bin/env python
"""Extract New York Times Magazine covers from public-domain Sunday issues on the
Internet Archive (collection pub_new-york-times-magazine, 1896-1930).

  .venv/bin/python scripts/extract_ia.py                      # all Sundays from 1896-09-06 (first Magazine)
  .venv/bin/python scripts/extract_ia.py --from 1913 --to 1920
  .venv/bin/python scripts/extract_ia.py --ids <identifier> ...
  .venv/bin/python scripts/extract_ia.py --retry               # re-attempt issues marked unresolved

How a cover is found inside an issue of ~40-100 pages: fetch a 400px image of
every page, OCR the top fifth of each with macOS Vision, and take the page whose
largest line of text says MAGAZINE ("ILLUSTRATED MAGAZINE SUPPLEMENT",
"MAGAZINE SECTION", ...). At that size inner-page running heads are too small
to be read, so only the cover's big subtitle registers.

Results go to covers/YYYY/YYYY-MM-DD.jpg + thumb/, bookkeeping in state.json.
With --remote r2:bucket (or REMOTE in the environment) each full-size cover is
moved to that rclone remote right after it is saved, so only thumbnails stay local.
"""
import argparse, datetime, io, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent      # repo root
COVERS, THUMBS, STATE = ROOT / 'covers', ROOT / 'thumb', ROOT / 'state.json'
LOG = ROOT / 'logs' / 'extract.log'
COLLECTION = 'pub_new-york-times-magazine'
FIRST_MAGAZINE = datetime.date(1896, 9, 6)
FULL_WIDTH = 1600            # requested width of the saved cover
THUMB_W, OCR_W = 600, 400    # gallery thumb width; page width used for OCR
MIN_HEIGHT = 0.05            # subtitle must be >= 5% of the OCR'd strip's height

S = requests.Session(); S.headers['User-Agent'] = 'nyt-magazine-covers/1.0 (personal research archive)'

def log(*a):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + ' '.join(str(x) for x in a)
    print(line, flush=True); LOG.parent.mkdir(exist_ok=True); LOG.open('a').write(line + '\n')

def get(url, **kw):
    for attempt in range(4):
        try:
            r = S.get(url, timeout=kw.pop('timeout', 90), **kw)
            if r.status_code == 200: return r
            if r.status_code == 404: return None
        except requests.RequestException: pass
        time.sleep(3 * (attempt + 1))
    return None

def page_url(id, n, w): return f'https://archive.org/download/{id}/page/n{n}_w{w}.jpg'

def list_sundays(d0, d1):
    r = S.get('https://archive.org/advancedsearch.php', params={
        'q': f'collection:{COLLECTION}', 'fl[]': 'identifier', 'rows': 20000, 'output': 'json'}).json()
    out = []
    for d in r['response']['docs']:
        m = re.search(r'_(\d{4})-(\d{2})-(\d{2})_', d['identifier'])
        if not m: continue
        try: date = datetime.date(*map(int, m.groups()))
        except ValueError: continue
        if date.weekday() == 6 and d0 <= date <= d1: out.append((date, d['identifier']))
    return sorted(out)

# ---------- detection ----------
_vision = None
def ocr_top(jpeg_bytes, frac=0.22):
    """(text, box height as fraction of the strip) for each line in the top `frac` of the page."""
    global _vision
    if _vision is None:
        import Vision, Quartz; _vision = (Vision, Quartz)
    Vision, Quartz = _vision
    data = Quartz.CFDataCreate(None, jpeg_bytes, len(jpeg_bytes))
    src = Quartz.CGImageSourceCreateWithData(data, None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if img is None: return []
    w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    crop = Quartz.CGImageCreateWithImageInRect(img, Quartz.CGRectMake(0, 0, w, int(h * frac)))
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(crop, None).performRequests_error_([req], None)
    out = []
    for r in req.results():
        c = r.topCandidates_(1)
        if c: out.append((c[0].string(), float(r.boundingBox().size.height)))
    return out

MAG = re.compile(r'MAGA[ZS]IN|MAGAZ|MACAZINE|MAGAINE', re.I)
def magazine_size(lines):
    """Height of the largest MAGAZINE line on the page, 0 if none."""
    return max((h for t, h in lines if MAG.search(t)), default=0.0)

def orientations(jpeg_bytes):
    """[(rotation, jpeg bytes)] to try: upright pages as-is; landscape pages (tabloid
    sections were often scanned sideways) rotated both ways."""
    im = Image.open(io.BytesIO(jpeg_bytes))
    if im.width <= im.height: return [(0, jpeg_bytes)]
    out = []
    for rot in (90, 270):
        buf = io.BytesIO(); im.rotate(rot, expand=True).save(buf, 'JPEG', quality=85); out.append((rot, buf.getvalue()))
    return out

def find_cover(id, n_pages):
    """Return (page index, rotation, note). Every page after the front page is OCR'd;
    the one with the biggest MAGAZINE subtitle is the cover."""
    with ThreadPoolExecutor(8) as ex:
        pages = dict(ex.map(lambda n: (n, getattr(get(page_url(id, n, OCR_W)), 'content', None)), range(1, n_pages)))
    sizes, rots = {}, {}
    for n, b in pages.items():
        if not b: continue
        for rot, bb in orientations(b):
            v = magazine_size(ocr_top(bb))
            if v > sizes.get(n, -1): sizes[n], rots[n] = v, rot
    missing = n_pages - 1 - len(sizes)
    if not sizes: return None, 0, 'no pages fetched'
    best = max(sizes, key=sizes.get)
    if sizes[best] < MIN_HEIGHT:
        return None, 0, f'no MAGAZINE subtitle (best {best}:{sizes[best]:.3f}, {missing} pages missing)'
    runners = sorted(((round(v, 3), n) for n, v in sizes.items() if n != best and v >= MIN_HEIGHT), reverse=True)[:3]
    note = f'subtitle {sizes[best]:.3f}' + (f' rot{rots[best]}' if rots[best] else '') + (f', also {runners}' if runners else '') + (f', {missing} pages missing' if missing else '')
    return best, rots[best], note

# ---------- saving ----------
def save_cover(id, n, date, rot=0):
    r = get(page_url(id, n, FULL_WIDTH))
    if not r: return False
    dst = COVERS / str(date.year) / f'{date}.jpg'; dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(io.BytesIO(r.content)).convert('L')
    if rot: im = im.rotate(rot, expand=True)
    im = ImageOps.autocontrast(im, cutoff=1)          # microfilm scans vary wildly in density
    im.save(dst, quality=88, optimize=True); make_thumb(dst, date)
    if REMOTE: upload(dst, f'covers/{date.year}/{date}.jpg'); upload(THUMBS / str(date.year) / f'{date}.jpg', f'thumb/{date.year}/{date}.jpg', keep=True)
    return True

REMOTE = os.environ.get('REMOTE', '')
def upload(src, key, keep=False):
    """Upload to R2: REMOTE='r2' uses ./r2.sh (wrangler, OAuth); anything else is an
    rclone remote. The local full-size copy is removed unless keep."""
    if REMOTE == 'r2':
        cmd = [str(ROOT / 'r2.sh'), 'put', str(src), key] + (['--keep'] if keep else [])
    else:
        cmd = ['rclone', 'copyto' if keep else 'moveto', str(src), f'{REMOTE.rstrip("/")}/{key}']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: log(f'upload failed {key}: {(r.stderr or r.stdout).strip()[:200]}')

def make_thumb(src, date):
    dst = THUMBS / str(date)[:4] / f'{date}.jpg'; dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src); im.thumbnail((THUMB_W, THUMB_W * 3)); im.convert('L' if im.mode == 'L' else 'RGB').save(dst, quality=78, optimize=True)

def build_index():
    dates = sorted({p.stem for p in THUMBS.glob('*/*.jpg') if re.fullmatch(r'\d{4}-\d{2}-\d{2}(-\d+)?', p.stem)}, reverse=True)
    state = {}
    for f in sorted(ROOT.glob('state*.json')):                  # state.json (IA) + state_cj.json etc.
        state.update(json.loads(f.read_text()))
    rows = [{'date': d, 'source': state.get(d, {}).get('source', 'added'), **({'approx': True} if 'approx' in state.get(d, {}).get('dated_by', '') else {})} for d in dates]
    (ROOT / 'covers.js').write_text(f'// generated {time.strftime("%Y-%m-%d %H:%M")}\nwindow.COVERS = {json.dumps(rows)};\n')
    log(f'index: {len(rows)} covers')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='d0', default=str(FIRST_MAGAZINE)); ap.add_argument('--to', dest='d1', default='1930-12-31')
    ap.add_argument('--ids', nargs='*'); ap.add_argument('--retry', action='store_true'); ap.add_argument('--limit', type=int)
    ap.add_argument('--remote', help='rclone destination, e.g. r2:nyt-magazine-covers')
    a = ap.parse_args()
    global REMOTE
    if a.remote: REMOTE = a.remote
    parse = lambda s: datetime.date.fromisoformat(s if len(s) > 4 else s + '-01-01')
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if a.ids:
        items = [(datetime.date(*map(int, re.search(r'_(\d{4})-(\d{2})-(\d{2})_', i).groups())), i) for i in a.ids]
    else:
        items = list_sundays(max(parse(a.d0), FIRST_MAGAZINE), parse(a.d1))
    log(f'{len(items)} Sunday issues to consider')
    done = 0
    for date, id in items:
        key = str(date); st = state.get(key, {})
        if st.get('status') == 'ok' or (COVERS / str(date.year) / f'{date}.jpg').exists(): continue
        if st.get('status') == 'unresolved' and not a.retry: continue
        meta = get(f'https://archive.org/metadata/{id}')
        n_pages = int(meta.json().get('metadata', {}).get('imagecount', 0)) if meta else 0
        if not n_pages: log(f'{date} {id}: no metadata'); continue
        t = time.time(); page, rot, how = find_cover(id, n_pages)
        if page is not None and save_cover(id, page, date, rot):
            state[key] = {'status': 'ok', 'source': 'ia', 'id': id, 'page': page, 'rot': rot, 'how': how}
            log(f'{date} page {page}/{n_pages} ({how}) {time.time() - t:.0f}s')
        else:
            state[key] = {'status': 'unresolved', 'id': id, 'pages': n_pages, 'how': how}
            log(f'{date} UNRESOLVED ({how}) {time.time() - t:.0f}s')
        STATE.write_text(json.dumps(state, indent=1, sort_keys=True))
        done += 1
        if a.limit and done >= a.limit: break
    build_index()

if __name__ == '__main__': main()
