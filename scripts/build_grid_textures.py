#!/usr/bin/env python3
"""Build grid textures sized to what the grid actually draws.

The grid never draws a cover wider than about 750px, and on most viewports
much narrower, so the 600px JPEGs were being decoded and uploaded as
textures several times larger than any cell. Re-encoding to 420px WebP at a
moderate quality cuts the bytes roughly fourfold, which is the difference
between a first paint that arrives and one that does not.

Full-resolution scans are left alone. They are only fetched one at a time,
when a cover is clicked, so their size never affects how fast the grid
appears.
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIDTH = int(sys.argv[1]) if len(sys.argv) > 1 else 420
QUALITY = int(sys.argv[2]) if len(sys.argv) > 2 else 68
JOBS = 8


def convert(job):
    src, dst = job
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst, os.path.getsize(dst), True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    r = subprocess.run(
        ["cwebp", "-quiet", "-m", "4", "-q", str(QUALITY),
         "-resize", str(WIDTH), "0", "-sharp_yuv", src, "-o", dst],
        capture_output=True)
    if r.returncode == 0 and os.path.exists(dst):
        return dst, os.path.getsize(dst), False
    if os.path.exists(dst):
        os.remove(dst)
    return dst, 0, False


def main():
    covers = json.load(open(os.path.join(ROOT, "web", "public", "covers.json")))
    jobs = []
    for c in covers:
        cid = c["d"]
        y = cid[:4]
        src = os.path.join(ROOT, "thumb", y, f"{cid}.jpg")
        if not os.path.exists(src):
            print(f"  MISSING source for {cid}")
            continue
        jobs.append((src, os.path.join(ROOT, "web", "public", "grid", y, f"{cid}.webp")))

    print(f"converting {len(jobs)} textures to {WIDTH}px WebP q{QUALITY} on {JOBS} workers")
    done = cached = failed = 0
    total = 0
    with cf.ThreadPoolExecutor(JOBS) as ex:
        for dst, size, was_cached in ex.map(convert, jobs):
            done += 1
            if was_cached:
                cached += 1
            elif size == 0:
                failed += 1
            else:
                total += size
            if done % 100 == 0:
                print(f"  {done}/{len(jobs)}  converted {(done-cached-failed)}  cached {cached}  failed {failed}", flush=True)

    out_dir = os.path.join(ROOT, "web", "public", "grid")
    disk = subprocess.run(["du", "-sh", out_dir], capture_output=True, text=True).stdout.split()[0]
    n = sum(len(fs) for _, _, fs in os.walk(out_dir))
    print(f"\n  {n} textures, {disk} on disk ({done-cached-failed} newly written, {cached} reused, {failed} failed)")
    if total:
        print(f"  mean new texture {total/(done-cached):.0f} KB")


if __name__ == "__main__":
    main()
