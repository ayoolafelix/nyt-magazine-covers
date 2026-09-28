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
# Every role label the descriptions use, matched longest-first so that
# "Deputy Art Director" wins over the "Art Director" nested inside it.
# parse_crew walks these in document order and treats each as a boundary.
ROLE_LABEL = re.compile(
    r"Deputy\s+Art\s+Director|Art\s+Director|Design\s+Director|"
    r"Creative\s+Director|Director\s+of\s+Photography|Photography\s+Director|"
    r"Photo\s+Director|Editor\s+in\s+Chief|Art\s+Deputy|Deputy\s+Editor|"
    r"Design\s+Associate|Art\s+Associate", re.I)

# The same labels collapsed into one lowercase token, as the newest
# descriptions write them: "artdirector @mrwilley".
ROLE_FUSED = re.compile(
    r"(?:art|design|creative|deputy|photo|photography)director|editorinchief", re.I)


CANONICAL_ROLES = {
    "art director": "Art Director",
    "deputy art director": "Deputy Art Director",
    "design director": "Design Director",
    "creative director": "Creative Director",
    "director of photography": "Director of Photography",
    "photography director": "Director of Photography",
    "photo director": "Director of Photography",
    "editor in chief": "Editor in Chief",
    "design associate": "Design Associate",
    "art associate": "Design Associate",
    "art deputy": "Deputy Art Director",
    "deputy editor": "Deputy Art Director",
}

FUSED_ROLES = {
    "artdirector": "Art Director",
    "designdirector": "Design Director",
    "creativedirector": "Creative Director",
    "deputydirector": "Deputy Art Director",
    "artdeputydirector": "Deputy Art Director",
    "photodirector": "Director of Photography",
    "photographydirector": "Director of Photography",
    "editorinchief": "Editor in Chief",
    "designassociate": "Design Associate",
    "artassociate": "Design Associate",
}


def label_text(token):
    """Normalise a matched label so the pane shows one spelling per role.

    The descriptions write "Art director", "Art Director" and "artdirector" for
    the same job. Left alone those become three rows in the list, so every
    spelling is folded onto one canonical label here.
    """
    s = re.sub(r"\s+", " ", token).strip(" :")
    key = s.lower()
    if key in FUSED_ROLES:
        return FUSED_ROLES[key]
    if key in CANONICAL_ROLES:
        return CANONICAL_ROLES[key]
    return s

# The description is a sentence someone typed, not a structured field, so a
# role label is sometimes followed by prose rather than a name: "Design Director
# Arem Duplessis designed for The New York Times Magazine", "Art director:
# Matt Willey Kathy Ryan : Director of Photography". These are the words that
# mean a capture has run into the next clause. Anything here is rejected
# rather than shown as if it were part of a name.
PROSE = re.compile(
    r"\b(designed|openened|created|made|says?|said|shows?|showed|describes?|"
    r"designed|opens?|opened|features?|featured|stars?|starring|celebrates?|"
    r"congrats|winner|winners|award|awards|anniversary|issue|cover|covers|"
    r"photograph|photographs|photography|illustration|illustrations|"
    r"shoot|shoots|shot|via|and|with|for|from|about|that|this|these|those|"
    r"his|her|their|its|our|my|new|next|last|first|best|top|most|more|also|"
    r"team|staff|crew|whole|fab|great|amazing|proud|congratulations)\b", re.I)

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
    # titles and ranks that trail a name or handle
    "senior", "junior", "sr", "jr", "ii", "iii", "iv", "phd", "mfa",
    # roles fused with no space, as in the all-lowercase descriptions:
    # "creativedirector @gailbichler photodirector @kathyryan"
    "artdirector", "designdirector", "photodirector", "creativedirector",
    "deputydirector", "editordirector", "artdeputydirector",
}

# Some descriptions run the next role into the previous name with no space:
# "Craig Cutler DesignDirector", "Hannah Whitaker DesignDirector". Split the
# token so the role can then be trimmed as structure. The role word has to be
# followed by a capital D to be a real role, which is what keeps surnames
# that merely end in "art" or "design" intact.
FUSED_ROLE = re.compile(
    r"\s*(?=(?:art|design|photo|creative|deputy|editor)\s*Director\b)", re.I)

# Instagram handles appear as the name in the newer descriptions
# ("artdirector @mrwilley"). The handle is the identity, so it is kept, but
# the @ is dropped: these render as names, not as links we cannot resolve.
HANDLE = re.compile(r"^@?([A-Za-z][A-Za-z0-9._]{1,30})$")

# A handful of descriptions list a person's name and then the studio they
# belong to, separated by a colon: "Deputy Art Director: Caleb Bennett
# Designers: Hilary Greenbaum, ...". The name and the studio are both real and
# the studio is the part that identifies them, so the trailing noun is kept
# rather than treated as a stray word.
STUDIO_SUFFIX = re.compile(
    r"\b(Designers?|Studios?|Studio|Associates|Partners|Group|Collective|"
    r"Company|Division)\b")

# Captures that are a phrase, not a person. The description is written by
# whoever posted the scan, so it contains asides ("this weekends cover") that
# match the credit patterns without naming anyone.
NOT_A_NAME = re.compile(
    r"\b(cover|weekend|issue|magazine|edition|front|single|first|double|"
    r"anniversary|special|exclusive|new|best|top|last|read|see|check|"
    r"subscribe|buy|order|available|out now|coming)\b", re.I)


def clean_name(raw):
    """Trim a captured credit back to something that reads as a person."""
    # The newer descriptions separate credits with " / " and tag them with
    # hashtags: "kathyryan / #nytmag". Neither belongs to a name, so both go,
    # along with a trailing separator of any kind.
    s = re.sub(r"\s+", " ", raw or "")
    s = re.sub(r"\s*[/|#].*$", "", s)
    # "emmalbo Photoeditor @joshklustig" — a handle and a photo credit glued
    # together, neither of which is the name this row is for
    s = re.sub(r"\s+(?:photo|art|design)?\s*editor\s+@\S+.*$", "", s, flags=re.I)
    s = re.sub(r"\s+(?:photo|art|design)\s*editor\b.*$", "", s, flags=re.I)
    s = s.strip(" .,:;@·-—")
    if not s:
        return ""

    # split a fused role off the end: "Cutler DesignDirector" -> "Cutler"
    s = FUSED_ROLE.sub("  ", s)
    s = re.sub(r"\s+", " ", s).strip(" .,:;@·-—")

    # a bare handle keeps its characters but loses the @
    h = HANDLE.match(s)
    if h:
        s = h.group(1)

    # trim structure off both ends, repeatedly
    toks = s.split(" ")
    while toks and toks[0].strip(".,").lower() in STRUCTURAL:
        toks.pop(0)
    while toks and toks[-1].strip(".,").lower() in STRUCTURAL:
        toks.pop()
    s = " ".join(toks).strip(" .,:;@·-—")

    # 4 words is only allowed when the last is a studio noun, since that is a
    # real part of a credit; anything longer is a capture that ran off.
    words = s.split()
    limit = 4 if words and STUDIO_SUFFIX.fullmatch(words[-1]) else 3
    if len(s) < 3 or len(s) > 44 or len(words) > limit:
        return ""
    if PROSE.search(s):
        return ""
    # A truncated or partial word: "Directo" for "Director", "Gail Bi" for
    # "Gail Bichler". A name whose last word is a bare prefix of a longer
    # common word is a capture that stopped early, not a person.
    if words and len(words[-1]) >= 3 and words[-1].lower() in {
            "directo", "photo", "photos", "edi", "edit", "art", "de", "des",
            "dire", "direc"}:
        return ""
    # a name is mostly letters; punctuation or digits mean the capture ran off
    if sum(1 for ch in s if ch.isalpha()) < max(3, len(s) * 0.6):
        return ""
    if NOT_A_NAME.search(s):
        return ""
    return s


# A role label appearing shortly after a captured name, optionally preceded by
# a colon and one more capitalised word. This is the tell that the capture ran
# past the end of a name and into the next credit: in
# "Art Director Matt Willey Kathy Ryan : Director of Photography" the Art
# Director is Matt Willey, and "Kathy" only looks like part of that name
# because the two credits run together with no separator.
def parse_crew(desc):
    """Read the role list left to right.

    Each role label owns the text between it and the next label, so the list is
    walked in order rather than searched for one role at a time. That is what
    makes the mixed forms work: in

        Design Director: Gail Bichler : Art Director Kathy Ryan :
        Director of Photography Deputy Art Director: Caleb Bennett Designers

    searching for "Art Director" alone finds the *name* Kathy Ryan and
    attributes it to Art Director, which is correct, but searching for
    "Director of Photography" then finds the *label* "Deputy Art Director" and
    calls it a name. Walking the labels in order and slicing between them
    cannot confuse a label for a name, because a label is always consumed as a
    boundary.
    """
    labels = sorted(
        [m for m in ROLE_LABEL.finditer(desc)] + [m for m in ROLE_FUSED.finditer(desc)],
        key=lambda m: m.start())
    out, seen = [], set()
    for i, m in enumerate(labels):
        start = m.end()
        end = labels[i + 1].start() if i + 1 < len(labels) else len(desc)
        segment = desc[start:end]
        # a "Name: Role" pair puts the name *before* its label, so when the
        # segment holds no letters, look left instead
        if not re.search(r"[A-Za-z]", segment):
            prev_end = labels[i - 1].end() if i else 0
            segment = desc[prev_end:m.start()]
        name = clean_name(segment)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((label_text(m.group(0)), name))
    return out


def parse_credits(desc):
    """Return (credit, credits) for one cover description line."""
    desc = re.sub(r"\s+", " ", desc or "").strip()
    credit = ""
    for role, pat in MAKER:
        m = re.search(pat, desc, re.I)
        if m:
            # the maker pattern captures up to three words, so it needs the
            # same boundary treatment: the name ends where the next label or
            # the next sentence does
            end = m.end()
            nxt = ROLE_LABEL.search(desc, end)
            if nxt and nxt.start() - end <= 24:
                end = nxt.start()
            name = clean_name(desc[m.start(1):end] if False else m.group(1))
            if name:
                # "Photography by X" reads better in full than a bare "X"
                lead = {"photograph": "Photography", "illustrat": "Illustration",
                        "painting": "Painting", "cover": "Cover"}.get(role, "Cover")
                credit = f"{lead} by {name}" if role in ("photograph", "illustrat",
                                                         "painting", "cover") else name
                break
    return credit, parse_crew(desc)


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
