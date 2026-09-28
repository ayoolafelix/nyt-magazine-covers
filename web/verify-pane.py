#!/usr/bin/env python3
"""Check the detail pane's markup and CSS agree, without a browser.

The pane broke once because the markup was restructured while the CSS still
described the old shape: .pane__row is the element that carries the
two-column grid, so a .pane__row wrapped *around* a .pane__meta squeezes the
whole list into the label column. Nothing throws in that case, it just looks
wrong, which is why it needs asserting rather than eyeballing.

This walks the built page and the built stylesheet and checks the structural
invariants that must hold for the pane to lay out correctly.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def built():
    dist = os.path.join(ROOT, "dist")
    html = open(os.path.join(dist, "index.html"), encoding="utf-8").read()
    js_name = re.search(r'assets/index-[A-Za-z0-9_-]+\.js', html).group(0)
    js = open(os.path.join(dist, js_name), encoding="utf-8").read()
    css_name = re.search(r'assets/index-[A-Za-z0-9_-]+\.css', html).group(0)
    css = open(os.path.join(dist, css_name), encoding="utf-8").read()
    return html, js, css


def rule(css, selector):
    """Return the declaration body for a selector, or None."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return m.group(1) if m else None


def credits(root):
    meta = json.load(open(os.path.join(root, "public", "meta.json"), encoding="utf-8"))
    rows = [(r, n) for v in meta.values() for r, n in v.get("credits", [])]
    covers = json.load(open(os.path.join(root, "public", "covers.json"), encoding="utf-8"))
    return meta, rows, covers


def check_credits(root):
    """The pane lists credits straight from this data, so malformed values are
    visible on the page. Assert on the values rather than trusting the parser.
    """
    meta, rows, covers = credits(root)
    fails = []

    def check(ok, label, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  -> ' + detail) if detail and not ok else ''}")
        if not ok:
            fails.append(label)

    names = [n for _, n in rows]
    roles = [r for r, _ in rows]

    print("\ncredit data")
    # a name that swallowed the next role reads as a name on the page
    role_in_name = [n for n in names
                    if re.search(r"(art|design|photo|creative|deputy|editor)\s*director",
                                 n, re.I)]
    check(not role_in_name, "no name contains a role label",
          f"{len(role_in_name)} e.g. {role_in_name[:2]}")

    punct = [n for n in names if re.search(r"[/|@#]", n)]
    check(not punct, "no name carries a separator or handle marker",
          f"{len(punct)} e.g. {punct[:2]}")

    trailing = [n for n in names if n != n.strip()]
    check(not trailing, "no name has leading or trailing whitespace")

    short = [n for n in names if len(n) < 3]
    check(not short, "no name is shorter than 3 characters", f"{short[:3]}")

    long_words = [n for n in names if len(n.split()) > 4]
    check(not long_words, "no name runs past 4 words", f"{long_words[:2]}")

    # one spelling per role, or the list shows "Art director" and "Art Director"
    canon = {"Art Director", "Deputy Art Director", "Design Director",
             "Creative Director", "Director of Photography", "Editor in Chief",
             "Design Associate"}
    odd = sorted({r for r in roles if r not in canon})
    check(not odd, "every role label is canonical", f"{odd}")

    # a role with no name beside it is a row that renders blank
    empty = [(k, r) for k, v in meta.items() for r, n in v.get("credits", []) if not n.strip()]
    check(not empty, "no credit row without a name", f"{empty[:2]}")

    print(f"\n  {len(meta)} covers carry credits, {len(set(names))} distinct names, "
          f"{len(set(roles))} roles")
    return fails


def main():
    html, js, css = built()
    fails = []

    def check(ok, label, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  -> ' + detail) if detail and not ok else ''}")
        if not ok:
            fails.append(label)

    print("markup")
    # the definition list must be the ancestor of the rows, not the child
    dl = re.search(r'<dl class="pane__meta"[^>]*id="paneMeta"[^>]*>(.*?)</dl>', html, re.S)
    check(dl is not None, "paneMeta <dl> present")
    inner = dl.group(1) if dl else ""
    check('id="paneRowCredit"' in inner, "paneRowCredit is a child of paneMeta",
          "row must live inside the dl, not wrap it")
    check(inner.count("<dl") == 0, "no nested <dl> inside paneMeta",
          f"found {inner.count('<dl')} nested dl")
    # a row wrapping a dl is the exact bug: check no row directly contains a dl
    bad = re.search(r'<div class="pane__row[^"]*"[^>]*>\s*<dl', inner)
    check(bad is None, "no .pane__row wrapping a <dl>")

    print("\nscript wiring")
    want = set(re.findall(r"getElementById\([\"'](pane[A-Za-z]*)[\"']\)", js))
    have = set(re.findall(r'id="(pane[A-Za-z]*)"', html))
    check(not (want - have), "every id the script reads exists in the markup",
          f"missing {sorted(want - have)}")
    check('classList.add("open")' in js or "classList.add('open')" in js,
          "pane still opens")

    print("\ncss")
    row = rule(css, ".pane__row")
    check(row is not None, ".pane__row rule present")
    if row:
        check("display:grid" in row.replace(" ", ""), ".pane__row is the grid container")
        check("minmax(0,1fr)" in row.replace(" ", ""),
              "value column is minmax(0,1fr) so it can shrink", row)
    crew = rule(css, ".pane__row--crew")
    check(crew is not None, ".pane__row--crew rule present")
    if crew and row:
        rw = re.search(r"grid-template-columns:([^;]+)", row)
        cw = re.search(r"grid-template-columns:([^;]+)", crew)
        check(bool(rw and cw) and cw.group(1) != rw.group(1),
              "crew rows use their own, wider label column",
              "role names like 'Deputy Art Director' need more than 5.2rem")
    meta = rule(css, ".pane__meta")
    if meta:
        check("border-top" in meta, "the block rule lives on .pane__meta, once")
    # a rule on .pane__row would double up when two rows are visible
    check(row is None or "border-top" not in row,
          "no border-top on .pane__row (would double between rows)")

    print("\nmobile")
    # the stylesheet is written with a space in "(max-width: 700px)"; the check
    # was matching the minified form, so normalise before comparing
    flat = re.sub(r"\s+", "", css)
    check("@media(max-width:700px)" in flat,
          "phone breakpoint present")
    # There is more than one max-width:700px block, and the one that restyles
    # the pane rows is not the first. Collecting them all and requiring that
    # one of them does the work avoids asserting against the wrong block.
    def blocks(pattern):
        out = []
        for m in re.finditer(pattern, css):
            depth, i = 0, m.end() - 1
            while i < len(css):
                if css[i] == "{":
                    depth += 1
                elif css[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            out.append(css[m.end():i])
        return out

    phone = blocks(r"@media\s*\(max-width:\s*700px\)\s*\{")
    check(len(phone) >= 1, "phone breakpoint parses")
    stacking = [b for b in phone
                if ".pane__row" in b and re.search(
                    r"grid-template-columns:\s*minmax\(0,\s*1fr\)", b)]
    check(bool(stacking), "some phone breakpoint stacks the label above the value",
          f"{len(phone)} phone blocks, none restyles .pane__row to one column")

    fails += check_credits(ROOT)

    print()
    if fails:
        print(f"FAIL  {len(fails)} problem(s): {fails}")
        return 1
    print("PASS  pane markup, script wiring, stylesheet and credit data agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
