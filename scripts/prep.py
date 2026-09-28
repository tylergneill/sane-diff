#!/usr/bin/env python3
"""Item unit, stage one: turn base.txt, suggester.txt and image.pdf into
tmp/pages/NNNN/.

Fully deterministic, no model involved. Extracts each PDF page's embedded
scan, splits both texts into per-page blocks on their page markers, diffs them
line by line and then word by word, and writes one diffs.json per page
that disagrees. Pages where the two texts agree get no directory at all.

The two texts must be page- and line-aligned.

Page images are extracted only if input/image.pdf exists. They are deleted
again after each resolve run and brought back for review; images.py does
both.
"""

import argparse
import difflib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from common import PAGES, marker_regex, parse_page_selection, resolve_marker, split_pages, tqdm


def die(msg):
    print(f"prep.py: {msg}", file=sys.stderr)
    sys.exit(1)


def word_diffs(base_line, sugg_line):
    """Word-level disagreements within a pair of lines.

    Returns a list of (word_index, word_span, base_reading, sugg_reading)
    where word_index is the index into the base line's words (or the
    insertion point, for words the base lacks) and word_span is how many
    base words the item covers. Empty string means "absent here".

    A run whose two sides differ only in whitespace — `tvak cakṣuṣī` against
    `tvakcakṣuṣī` — is one question about the printed page, not one question
    per token, so it is emitted as a single item spanning both words rather
    than as a pair in which one half has no suggester reading at all.
    """
    bwords = base_line.split()
    swords = sugg_line.split()
    out = []
    matcher = difflib.SequenceMatcher(a=bwords, b=swords, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            if "".join(bwords[i1:i2]) == "".join(swords[j1:j2]):
                # Same characters, different spacing: one item for the run.
                out.append((i1, i2 - i1, " ".join(bwords[i1:i2]),
                            " ".join(swords[j1:j2])))
                continue
            # Pair them up positionally; the leftovers are adds or drops.
            span = max(i2 - i1, j2 - j1)
            for k in range(span):
                e = bwords[i1 + k] if i1 + k < i2 else ""
                o = swords[j1 + k] if j1 + k < j2 else ""
                out.append((min(i1 + k, i2 - 1 if i2 > i1 else i1), 1, e, o))
        elif tag == "delete":
            for k in range(i1, i2):
                out.append((k, 1, bwords[k], ""))
        elif tag == "insert":
            for k in range(j1, j2):
                out.append((i1, 0, "", swords[k]))
    return out


def page_diffs(page_no, blines, slines):
    """All diff items for one page, line-aligned then word-aligned."""
    items = []
    matcher = difflib.SequenceMatcher(a=blines, b=slines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        span = max(i2 - i1, j2 - j1)
        for k in range(span):
            bline = blines[i1 + k] if i1 + k < i2 else ""
            sline = slines[j1 + k] if j1 + k < j2 else ""
            lineno = (i1 + k if i1 + k < i2 else i2 - 1 if i2 > i1 else i1) + 1
            if bline.strip() == sline.strip():
                continue
            for widx, wspan, bword, sword in word_diffs(bline, sline):
                items.append(
                    {
                        "id": f"p{page_no:04d}-{len(items) + 1:03d}",
                        "page": page_no,
                        "line": lineno,
                        "word_index": widx,
                        "word_span": wspan,
                        "etext": bword,  # the base; see ITEM_KEYS in common.py
                        "ocr": sword,    # the suggester
                        "context": bline if bline else sline,
                    }
                )
    return items


def extract_pages(pdf, outdir, pages):
    """Extract each wanted page's embedded scan into its page directory.

    A scanned edition stores one image per page, so the page image is already
    in the PDF and nothing needs rendering. pdfimages -j writes the JPEG
    stream out byte for byte, which is both faster than rasterising the page
    and lossless — re-rendering a 200 DPI scan at 300 DPI only interpolates
    pixels that were never scanned.

    Pages whose embedded image is not a single JPEG are reported rather than
    silently skipped.
    """
    if not shutil.which("pdfimages"):
        die("pdfimages not found on PATH (install poppler)")

    missing = []
    for page_no in tqdm(pages, desc="extracting", unit="page"):
        dest = outdir / f"{page_no:04d}"
        dest.mkdir(parents=True, exist_ok=True)
        prefix = dest / "page"
        _run(["pdfimages", "-j", "-f", str(page_no), "-l", str(page_no),
              str(pdf), str(prefix)], page_no)

        # pdfimages appends its own index: page-000.jpg, and .ppm/.pbm when
        # the stream was not JPEG after all.
        produced = sorted(dest.glob("page-*"))
        if len(produced) == 1 and produced[0].suffix == ".jpg":
            produced[0].rename(dest / "page.jpg")
        else:
            for f in produced:
                f.unlink()
            missing.append(page_no)

    if missing:
        print(f"prep.py: warning: {len(missing)} page(s) had no single embedded "
              f"JPEG and were left without an image: "
              f"{', '.join(str(p) for p in missing[:10])}"
              f"{'...' if len(missing) > 10 else ''}", file=sys.stderr)


def _run(cmd, page_no):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        die(f"{cmd[0]} failed on page {page_no}: {result.stderr.strip()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="input", type=Path)
    ap.add_argument("--work", default=PAGES, type=Path)
    ap.add_argument("--marker", default="auto", type=marker_regex,
                    help="page marker: auto (default: <p.12> or === 12 ===, detected "
                         "per file), or a regex whose group 1 is the page number")
    ap.add_argument("--pages", default=None,
                    help="restrict to these pages, e.g. 12-21 or 3,5,9")
    ap.add_argument("--no-images", action="store_true",
                    help="write diffs.json only, even if image.pdf exists")
    args = ap.parse_args()

    base_path = args.input / "base.txt"
    sugg_path = args.input / "suggester.txt"
    pdf_path = args.input / "image.pdf"
    for p in (base_path, sugg_path):
        if not p.exists():
            die(f"missing input file: {p}")

    base_text = base_path.read_text(encoding="utf-8")
    sugg_text = sugg_path.read_text(encoding="utf-8")
    base = split_pages(base_text, resolve_marker(args.marker, base_text, "base.txt", die),
                       "base.txt", die)
    sugg = split_pages(sugg_text, resolve_marker(args.marker, sugg_text, "suggester.txt", die),
                       "suggester.txt", die)

    only_b = sorted(set(base) - set(sugg))
    only_s = sorted(set(sugg) - set(base))
    if only_b or only_s:
        print(f"prep.py: warning: pages only in base: {only_b or 'none'}; "
              f"only in suggester: {only_s or 'none'}", file=sys.stderr)

    wanted = parse_page_selection(args.pages) if args.pages else None
    shared = sorted(set(base) & set(sugg))
    if wanted is not None:
        shared = [p for p in shared if p in wanted]

    args.work.mkdir(parents=True, exist_ok=True)
    with_diffs = []
    total_items = 0
    for page_no in tqdm(shared, desc="diffing", unit="page"):
        items = page_diffs(page_no, base[page_no], sugg[page_no])
        if not items:
            continue
        with_diffs.append(page_no)
        total_items += len(items)
        dest = args.work / f"{page_no:04d}"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "diffs.json").write_text(
            json.dumps({"page": page_no, "items": items}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if with_diffs and not args.no_images and pdf_path.exists():
        extract_pages(pdf_path, args.work, with_diffs)

    clean = len(shared) - len(with_diffs)
    print(f"pages compared:   {len(shared)}")
    print(f"pages in agreement (skipped): {clean}")
    print(f"pages with diffs: {len(with_diffs)}")
    print(f"diff items:       {total_items}")
    if not pdf_path.exists():
        print(f"no {pdf_path}, so no page images: vision runs are unavailable")


if __name__ == "__main__":
    main()
