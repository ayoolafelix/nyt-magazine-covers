#!/usr/bin/env python
"""Build covers.json for the gallery from the thumbnails on disk plus the fetchers'
state files. Coverjunkie credits/descriptions are fetched once and cached in
data/cj_meta.json.   .venv/bin/python scripts/build_index.py"""
import html, json, re, sys, time, urllib.parse
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
import fetch_coverjunkie as F

ROOT = Path(__file__).resolve().parent.parent
def era(d):
    if d < '1897': return 'Sunday Magazine Supplement'
    if d < '1901': return 'Illustrated Magazine Supplement'
    if d < '1928': return 'Magazine Section'
    return 'The New York Times Magazine'

def cj_meta():
    cache = ROOT / 'data' / 'cj_meta.json'; cache.parent.mkdir(exist_ok=True)
    meta = json.loads(cache.read_text()) if cache.exists() else {}
    try:
        key = F.anon_key(); h = {'apikey': key, 'Authorization': 'Bearer ' + key, 'User-Agent': 'Mozilla/5.0'}
        rows = requests.get(f"{F.SUPABASE}/rest/v1/covers?select=id,slug,description,image_url&magazine=eq.{urllib.parse.quote(F.MAGAZINE)}&limit=5000", headers=h, timeout=60).json()
        for r in rows:
            d = html.unescape(re.sub(r'<[^>]+>', ' ', r.get('description') or ''))
            d = re.sub(r'\s+', ' ', d).strip()
            meta[r['id']] = {'slug': r['slug'], 'desc': d[:700], 'url': r['image_url']}
        cache.write_text(json.dumps(meta, indent=0))
    except Exception as e: print('coverjunkie metadata not refreshed:', e)
    return meta

def main():
    state = {}
    for f in sorted(ROOT.glob('state*.json')): state.update(json.loads(f.read_text()))
    meta = cj_meta()
    out = []
    for p in sorted(ROOT.glob('thumb/*/*.jpg')):
        key = p.stem
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(-\d+)?', key): continue
        st = state.get(key, {}); src = st.get('source', 'added')
        row = {'id': key, 'date': key[:10], 'era': era(key), 'source': src}
        if 'approx' in st.get('dated_by', ''): row['approx'] = True
        if src == 'ia':
            row['ia'] = {'item': st['id'], 'page': st.get('page'), 'url': f"https://archive.org/details/{st['id']}/page/n{st.get('page', 0)}"}
        elif src == 'coverjunkie':
            m = meta.get(st.get('cj_id'), {})
            row['cj'] = {'url': f"https://coverjunkie.com/cover/{m['slug']}" if m.get('slug') else 'https://coverjunkie.com/magazines/new-york-times-magazine/', 'posted': st.get('cj_date')}
            if m.get('desc'): row['desc'] = m['desc']
            if st.get('px'): row['px'] = st['px']
        out.append(row)
    (ROOT / 'covers.json').write_text(json.dumps({'generated': time.strftime('%Y-%m-%d %H:%M'), 'covers': out}, ensure_ascii=False))
    print(f'covers.json: {len(out)} covers ({sum(r["source"]=="ia" for r in out)} IA, {sum(r["source"]=="coverjunkie" for r in out)} Coverjunkie)')

if __name__ == '__main__': main()
