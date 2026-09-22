#!/usr/bin/env python3
"""Walk the flagged items one page at a time, next to the scan.

Reads output/report.flagged.tsv and prints each flagged item grouped by page,
so the page image only has to be opened once per group. With --open it also
opens each page's scan as it goes.
"""

import argparse
import csv
import subprocess
import sys
from pathlib import Path

FLAGGED = Path("output/report.flagged.tsv")
PAGES = Path("tmp/pages")


def rows(path, only=None):
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if only and int(row["page"]) not in only:
                continue
            yield row


def parse_pages(spec):
    if not spec:
        return None
    out = set()
    for part in spec.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(part))
    return out


def clear():
    """Clear the screen, falling back to blank lines where that is not possible."""
    if subprocess.run(["clear"], check=False).returncode != 0:
        print("\n" * 4)


def show(row):
    blank = "(none)"
    print(f"  {row['id']}  line {row['line']}  [{row['choice']}/{row['confidence']}]")
    print(f"    etext : {row['etext'] or blank}")
    print(f"    ocr   : {row['ocr'] or blank}")
    print(f"    →     : {row['reading'] or blank}")
    if row.get("note"):
        print(f"    why   : {row['note']}")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", help="restrict to these pages, e.g. 30 or 12-24,96")
    ap.add_argument("--open", action="store_true",
                    help="open each page scan with the system viewer")
    ap.add_argument("--no-clear", action="store_true",
                    help="print every page at once instead of clearing between them")
    args = ap.parse_args()

    if not FLAGGED.exists():
        sys.exit(f"review.py: {FLAGGED} not found; run scripts/report.py first")

    only = parse_pages(args.pages)
    grouped = {}
    for row in rows(FLAGGED, only):
        grouped.setdefault(int(row["page"]), []).append(row)

    if not grouped:
        print("no flagged items match")
        return

    total = sum(len(v) for v in grouped.values())
    pages = sorted(grouped)
    paging = not args.no_clear and sys.stdout.isatty() and len(pages) > 1

    if not paging:
        print(f"{total} flagged item(s) on {len(pages)} page(s)\n")

    for idx, page in enumerate(pages, 1):
        scan = PAGES / f"{page:04d}" / "page.jpg"
        if paging:
            clear()
        print(f"=== page {page}  ({idx}/{len(pages)} pages, "
              f"{len(grouped[page])} of {total} items)  {scan} ===")
        for row in grouped[page]:
            show(row)
        if args.open and scan.exists():
            subprocess.run(["open", str(scan)], check=False)
        if paging and idx < len(pages):
            try:
                input("    [enter] for next page, ctrl-c to stop ")
            except (EOFError, KeyboardInterrupt):
                print()
                return


if __name__ == "__main__":
    main()
