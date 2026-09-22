#!/usr/bin/env python3
"""Stage one: turn etext.txt, ocr.txt and source.pdf into tmp/pages/NNNN/.

Fully deterministic, no model involved. Extracts each PDF page's embedded
scan, splits both texts into per-page blocks on their page markers, diffs them
line by line and then word by word, and writes one diffs.json per page
that disagrees. Pages where the two texts agree get no directory at all.
"""

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_MARKER = r"^\s*<p\.(\d+)>\s*$"

try:
    from tqdm import tqdm
except ImportError:  # optional; the scripts stay runnable without it
    def tqdm(iterable, **kwargs):
        desc = kwargs.get("desc", "")
        total = kwargs.get("total") or len(iterable)
        live = sys.stderr.isatty()
        for n, item in enumerate(iterable, 1):
            if live:
                print(f"\r{desc}: {n}/{total}", end="", file=sys.stderr, flush=True)
            yield item
        if live:
            print(file=sys.stderr)
        else:
            print(f"{desc}: {total}", file=sys.stderr)


def die(msg):
    print(f"prep.py: {msg}", file=sys.stderr)
    sys.exit(1)


def split_pages(text, marker, label):
    """Split a text into {page_number: [lines]} on its page markers.

    Line numbers are 1-based within each page and count every line of the
    page block, blank lines included, so that etext and ocr line numbers
    refer to the same printed line.
    """
    pattern = re.compile(marker)
    pages = {}
    current = None
    lines = []
    for raw in text.splitlines():
        m = pattern.match(raw)
        if m:
            if current is not None:
                pages[current] = lines
            current = int(m.group(1))
            if current in pages:
                die(f"{label}: page {current} appears more than once")
            lines = []
        else:
            lines.append(raw)
    if current is not None:
        pages[current] = lines
    elif lines:
        die(f"{label}: no page markers matched {marker!r}")
    return pages


def word_diffs(etext_line, ocr_line):
    """Word-level disagreements within a pair of lines.

    Returns a list of (word_index, word_span, etext_reading, ocr_reading)
    where word_index is the index into the e-text line's words (or the
    insertion point, for words the e-text lacks) and word_span is how many
    e-text words the item covers. Empty string means "absent here".

    A run whose two sides differ only in whitespace — `tvak cakṣuṣī` against
    `tvakcakṣuṣī` — is one question about the printed page, not one question
    per token, so it is emitted as a single item spanning both words rather
    than as a pair in which one half has no OCR reading at all.
    """
    ewords = etext_line.split()
    owords = ocr_line.split()
    out = []
    matcher = difflib.SequenceMatcher(a=ewords, b=owords, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            if "".join(ewords[i1:i2]) == "".join(owords[j1:j2]):
                # Same characters, different spacing: one item for the run.
                out.append((i1, i2 - i1, " ".join(ewords[i1:i2]),
                            " ".join(owords[j1:j2])))
                continue
            # Pair them up positionally; the leftovers are adds or drops.
            span = max(i2 - i1, j2 - j1)
            for k in range(span):
                e = ewords[i1 + k] if i1 + k < i2 else ""
                o = owords[j1 + k] if j1 + k < j2 else ""
                out.append((min(i1 + k, i2 - 1 if i2 > i1 else i1), 1, e, o))
        elif tag == "delete":
            for k in range(i1, i2):
                out.append((k, 1, ewords[k], ""))
        elif tag == "insert":
            for k in range(j1, j2):
                out.append((i1, 0, "", owords[k]))
    return out


def page_diffs(page_no, elines, olines):
    """All diff items for one page, line-aligned then word-aligned."""
    items = []
    matcher = difflib.SequenceMatcher(a=elines, b=olines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        span = max(i2 - i1, j2 - j1)
        for k in range(span):
            eline = elines[i1 + k] if i1 + k < i2 else ""
            oline = olines[j1 + k] if j1 + k < j2 else ""
            lineno = (i1 + k if i1 + k < i2 else i2 - 1 if i2 > i1 else i1) + 1
            if eline.strip() == oline.strip():
                continue
            for widx, wspan, eword, oword in word_diffs(eline, oline):
                items.append(
                    {
                        "id": f"p{page_no:04d}-{len(items) + 1:03d}",
                        "page": page_no,
                        "line": lineno,
                        "word_index": widx,
                        "word_span": wspan,
                        "etext": eword,
                        "ocr": oword,
                        "context": eline if eline else oline,
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
    silently skipped; see --render for the fallback.
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
    ap.add_argument("--work", default="tmp/pages", type=Path)
    ap.add_argument("--marker", default=DEFAULT_MARKER,
                    help="regex for a page marker line, group 1 = page number")
    ap.add_argument("--pages", default=None,
                    help="restrict to these pages, e.g. 12-21 or 3,5,9")
    ap.add_argument("--no-render", action="store_true",
                    help="write diffs.json only, skip image extraction")
    args = ap.parse_args()

    etext_path = args.input / "etext.txt"
    ocr_path = args.input / "ocr.txt"
    pdf_path = args.input / "source.pdf"
    for p in (etext_path, ocr_path):
        if not p.exists():
            die(f"missing input file: {p}")
    if not args.no_render and not pdf_path.exists():
        die(f"missing input file: {pdf_path}")

    etext = split_pages(etext_path.read_text(encoding="utf-8"), args.marker, "etext.txt")
    ocr = split_pages(ocr_path.read_text(encoding="utf-8"), args.marker, "ocr.txt")

    only_e = sorted(set(etext) - set(ocr))
    only_o = sorted(set(ocr) - set(etext))
    if only_e or only_o:
        print(f"prep.py: warning: pages only in etext: {only_e or 'none'}; "
              f"only in ocr: {only_o or 'none'}", file=sys.stderr)

    wanted = parse_page_selection(args.pages) if args.pages else None
    shared = sorted(set(etext) & set(ocr))
    if wanted is not None:
        shared = [p for p in shared if p in wanted]

    args.work.mkdir(parents=True, exist_ok=True)
    with_diffs = []
    total_items = 0
    for page_no in tqdm(shared, desc="diffing", unit="page"):
        items = page_diffs(page_no, etext[page_no], ocr[page_no])
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

    if with_diffs and not args.no_render:
        extract_pages(pdf_path, args.work, with_diffs)

    clean = len(shared) - len(with_diffs)
    print(f"pages compared:   {len(shared)}")
    print(f"pages in agreement (skipped): {clean}")
    print(f"pages with diffs: {len(with_diffs)}")
    print(f"diff items:       {total_items}")


def parse_page_selection(spec):
    """Parse '12-21' or '3,5,9' or a mix into a set of page numbers."""
    wanted = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            wanted.update(range(int(lo), int(hi) + 1))
        else:
            wanted.add(int(chunk))
    return wanted


if __name__ == "__main__":
    main()
