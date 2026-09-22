#!/usr/bin/env python3
"""Walk the agent's overrides one page at a time, next to the scan.

An `other` verdict is the only one that can put a reading into the output that
neither source contains, so it is the one that needs human eyes. Reads
output/report.tsv and shows those overrides grouped by page, so the page image
only has to be opened once per group. With --open it also opens each scan.

By default only low-confidence overrides are shown. Use --include-medium to add
the medium ones, or --medium-only to see just those. An override is never high
confidence, so there is no band above medium.
"""

import argparse
import csv
import subprocess
import sys
from pathlib import Path

REPORT = Path("output/report.tsv")
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
    band = ap.add_mutually_exclusive_group()
    band.add_argument("--include-medium", action="store_true",
                      help="also show medium-confidence overrides")
    band.add_argument("--medium-only", action="store_true",
                      help="show only medium-confidence overrides")
    args = ap.parse_args()

    if args.medium_only:
        want = {"medium"}
    elif args.include_medium:
        want = {"low", "medium"}
    else:
        want = {"low"}

    if not REPORT.exists():
        sys.exit(f"review.py: {REPORT} not found; run scripts/report.py first")

    only = parse_pages(args.pages)
    grouped = {}
    for row in rows(REPORT, only):
        if row["choice"] != "other" or row["confidence"] not in want:
            continue
        grouped.setdefault(int(row["page"]), []).append(row)

    if not grouped:
        print("no overrides match")
        return

    total = sum(len(v) for v in grouped.values())
    pages = sorted(grouped)
    paging = not args.no_clear and sys.stdout.isatty() and len(pages) > 1

    label = "+".join(sorted(want))
    if not paging:
        print(f"{total} override(s) [{label} confidence] on {len(pages)} page(s)\n")

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
