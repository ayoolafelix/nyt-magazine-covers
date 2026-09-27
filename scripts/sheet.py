"""Contact sheet of every page in an IA item: sheet.py <identifier> <out.png>"""
import sys, io, requests
from PIL import Image, ImageDraw
from concurrent.futures import ThreadPoolExecutor
id, out = sys.argv[1], sys.argv[2]
N = int(requests.get(f'https://archive.org/metadata/{id}').json()['metadata']['imagecount'])
s = requests.Session(); s.headers['User-Agent'] = 'nyt-magazine-covers/1.0 (personal research)'
def get(n):
    for _ in range(3):
        try:
            r = s.get(f'https://archive.org/download/{id}/page/n{n}_w200.jpg', timeout=60)
            if r.ok: return n, r.content
        except Exception: pass
    return n, None
with ThreadPoolExecutor(8) as ex: res = dict(ex.map(get, range(N)))
W, H, cols = 120, 172, 16; rows = (N + cols - 1) // cols
sheet = Image.new('L', (cols * W, rows * H), 255); d = ImageDraw.Draw(sheet)
for n in range(N):
    if not res[n]: continue
    x, y = (n % cols) * W, (n // cols) * H
    sheet.paste(Image.open(io.BytesIO(res[n])).convert('L').resize((W, H)), (x, y))
    d.rectangle([x, y, x + 28, y + 11], fill=0); d.text((x + 2, y), str(n), fill=255)
sheet.save(out); print(id, 'pages:', N, '->', out)
