#!/usr/bin/env python3
"""Convert the curated archive into the shape the WebGL grid expects.

The gallery in index.html is a DOM grid built for a flat list. The WebGL
build wants three things the old index never had to think about:

  covers.json  [{d, t, thumb, full, src}]     one entry per cover, chronological
  meta.json    {d: {credit, credits, approx}}  per-cover credits, sparse by nature
  the median cover proportion                  so cellH = cellW / AR leaves no letterbox

Credits come from the Coverjunkie description line, which is free text written
by whoever posted the scan, not a structured field. It is parsed for the
handful of roles that actually appear, and anything unmatched is left out
rather than guessed: a pane row is hidden when its value is empty, so a cover
with no parseable credit simply shows no credit row.

Image URLs stay on the jsDelivr CDN, which fronts the public GitHub repo.
"""
import collections
import json
import os
import re
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CDN = "https://cdn.jsdelivr.net/gh/ayoolafelix/nyt-magazine-covers@main/"

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# Roles that identify who made the cover image. Ordered by how directly the
# role names the artist: a photographer or illustrator is the cover credit,
# where an art director is not.
MAKER = [
    ("cover",      r"cover (?:artwork|art|image|illustration)\s*(?:by)?\s*[:@]?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
    ("artwork",    r"artwork\s*[:@]?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
    ("illustrat",  r"illustration by\s*[:@]?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
    ("photograph", r"photographs?\s+by\s*[:@]?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
    ("painting",   r"paintings?\s+by\s*[:@]?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
    ("cover",      r"cover by\s*[:@]?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
]

# Roles that belong in the wider credit block.
CREW = [
    ("Art Director",       r"art\s*director\s*:?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
    ("Deputy Art Director", r"deputy\s+art\s*director\s*:?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
    ("Design Director",    r"design\s*director\s*:?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
    ("Creative Director",  r"creative\s*director\s*:?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
    ("Photo Director",     r"(?:director|photography)\s+of\s+photography\s*:?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
    ("Editor in Chief",    r"editor\s+in\s+chief\s*:?\s*@?([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"),
]

# Words that are structure in this text rather than part of a name. The
# description runs "Photography by Tom Schierlitz Art Director: ...", so a
# capture that allows up to three capitalised tokens reaches past the end of
# the name and into the next role. These are trimmed off either end.
# Matched as whole tokens, so "Newman" and "K hearty" are never touched.
STRUCTURAL = {
    "new", "york", "times", "magazine", "nyt", "cover", "covers", "issue",
    "art", "arts", "artwork", "design", "photo", "photos", "photography",
    "illustration", "illustrations", "layout", "director", "directors",
    "editor", "editors", "deputy", "creative", "staff", "the", "this", "that",
    "and", "for", "with", "of", "on", "at", "in", "a", "an", "weekend",
    "weekends", "featuring", "about", "by", "its", "our", "their", "his",
    "her", "who", "what", "when", "where", "why", "how", "special",
}

# Captures that are a phrase, not a person. The description is written by
# whoever posted the scan, so it contains asides ("this weekends cover") that
# match the credit patterns without naming anyone.
NOT_A_NAME = re.compile(
    r"\b(cover|weekend|issue|magazine|edition|front|single|first|double|"
    r"anniversary|special|exclusive|new|best|top|last|read|see|check|"
    r"subscribe|buy|order|available|out now|coming)\b", re.I)


def clean_name(raw):
    """Trim a captured credit back to something that reads as a person."""
    s = re.sub(r"\s+", " ", raw or "").strip(" .,:;@·-—")
    if not s:
        return ""

    # trim structure off both ends, repeatedly
    toks = s.split(" ")
    while toks and toks[0].strip(".,").lower() in STRUCTURAL:
        toks.pop(0)
    while toks and toks[-1].strip(".,").lower() in STRUCTURAL:
        toks.pop()
    s = " ".join(toks).strip(" .,:;@·-—")

    if len(s) < 3 or len(s) > 44 or len(s.split()) > 4:
        return ""
    # a name is mostly letters; punctuation or digits mean the capture ran off
    if sum(1 for ch in s if ch.isalpha()) < max(3, len(s) * 0.75):
        return ""
    if NOT_A_NAME.search(s):
        return ""
    return s


def parse_credits(desc):
    """Return (credit, credits) for one cover description line."""
    desc = re.sub(r"\s+", " ", desc or "").strip()
    credit = ""
    for role, pat in MAKER:
        m = re.search(pat, desc, re.I)
        if m:
            name = clean_name(m.group(1))
            if name:
                # "Photography by X" reads better in full than a bare "X"
                lead = {"photograph": "Photography", "illustrat": "Illustration",
                        "painting": "Painting", "cover": "Cover"}.get(role, "Cover")
                credit = f"{lead} by {name}" if role in ("photograph", "illustrat",
                                                         "painting", "cover") else name
                break
    crew = []
    seen = set()
    for label, pat in CREW:
        m = re.search(pat, desc, re.I)
        if m:
            name = clean_name(m.group(1))
            if name and name.lower() not in seen:
                seen.add(name.lower())
                crew.append((label, name))
    return credit, crew


def display_date(cid, approx):
    """Format a cover id for display.

    Ids are not always a bare date: when two scans share an issue date the
    second gets a -2 suffix, so 2026-09-08-2 is a distinct file but the same
    issue. Only the leading y-m-d is the date.
    """
    parts = cid.split("-")[:3]
    y, m, d = parts
    return f"{'≈ ' if approx else ''}{MONTHS[int(m) - 1]} {int(d)}, {y}"


def pixels(c):
    px = c.get("px") or []
    return px[0] * px[1] if len(px) == 2 and px[0] and px[1] else 0


def main():
    data = json.load(open(os.path.join(ROOT, "covers.json")))
    raw = sorted(data["covers"], key=lambda c: c["id"])

    # One cover per issue. The archive keeps every scan it found, so an issue
    # that was scanned more than once appears up to 16 times over; a
    # chronological grid that steps through 16 copies of the same cover is
    # just a stall. dhash could not catch these because separate physical
    # copies of one issue differ slightly in paper tone and crop. Keep the
    # largest scan of each date, which is also the best one to show full size.
    best = {}
    for c in raw:
        key = "-".join(c["id"].split("-")[:3])
        cur = best.get(key)
        if cur is None or pixels(c) > pixels(cur):
            best[key] = c
    covers = sorted(best.values(), key=lambda c: c["id"])
    dropped = len(raw) - len(covers)

    out, meta = [], {}
    aspects, hit_credit, hit_crew = [], 0, 0

    for c in covers:
        cid = c["id"]
        y = cid[:4]
        credit, crew = parse_credits(c.get("desc"))
        if credit:
            hit_credit += 1
        if crew:
            hit_crew += 1
        if credit or crew:
            entry = {}
            if credit:
                entry["credit"] = credit
            if crew:
                entry["credits"] = crew
            if c.get("approx"):
                entry["approx"] = True
            meta[cid] = entry

        px = c.get("px") or []
        if len(px) == 2 and px[0] and px[1]:
            aspects.append(px[0] / px[1])

        out.append({
            "d": cid,
            "t": display_date(cid, bool(c.get("approx"))),
            # `grid` is a 420px WebP served by Vercel alongside the site: it is
            # what the WebGL texture loader requests, and it is the only image
            # the page fetches in bulk. `thumb` stays on the CDN because the
            # colour sampler falls back to it for covers whose grid texture
            # has not been built yet. `full` is fetched one at a time on click.
            "grid": f"grid/{y}/{cid}.webp",
            "thumb": f"{CDN}thumb/{y}/{cid}.jpg",
            "full": f"{CDN}covers/{y}/{cid}.jpg",
            "src": (c.get("cj") or {}).get("url", ""),
            # The issue date was not legible on many scans, so the poster's
            # upload date stands in. Carried as a flag so the pane can say so
            # rather than leaving a bare tilde for the reader to decode.
            "a": bool(c.get("approx")),
        })

    ar = round(statistics.median(aspects), 4) if aspects else 0.8215
    spread = (min(aspects), max(aspects)) if aspects else (0, 0)

    json.dump(out, open(os.path.join(ROOT, "web", "public", "covers.json"), "w"),
              separators=(",", ":"))
    json.dump(meta, open(os.path.join(ROOT, "web", "public", "meta.json"), "w"),
              separators=(",", ":"))

    n = len(out)
    print(f"covers.json : {n} entries, {os.path.getsize(os.path.join(ROOT, 'web', 'covers.json'))/1024:.0f} KB")
    print(f"              (deduplicated from {len(raw)}: {dropped} repeat scans of an issue already held)")
    print(f"meta.json   : {len(meta)} entries, {os.path.getsize(os.path.join(ROOT, 'web', 'meta.json'))/1024:.0f} KB")
    print(f"cover credit: {hit_credit}/{n} ({100*hit_credit/n:.0f}%)")
    print(f"crew credit : {hit_crew}/{n} ({100*hit_crew/n:.0f}%)")
    print(f"proportion  : median {ar}  (range {spread[0]:.3f}-{spread[1]:.3f})")
    print("\n  samples:")
    for cid in [out[0]["d"], out[200]["d"], out[500]["d"], out[-1]["d"]]:
        m = meta.get(cid, {})
        print(f"    {out[[x['d'] for x in out].index(cid)]['t']:24} "
              f"{m.get('credit','')[:34]:36} {len(m.get('credits',[]))} crew")


if __name__ == "__main__":
    main()
