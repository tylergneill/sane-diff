#!/usr/bin/env python3
"""Page images: extract them from input/image.pdf, or clean them away.

  images.py prep [--pdf-offset N] [--pages 3-5]
                      page.jpg for every page of the PDF, and the offset
                      recorded in tmp/pages/prep.json (make prep-images)
  images.py extract   page.jpg for every page directory with a diffs.json
                      that lacks one, with the recorded offset
  images.py clean     delete every page.jpg, and the scratch/ crops agents
                      made (make clean-up)

Images go into tmp/pages/NNNN/page.jpg, NNNN being the page marker's
number: the PDF page index minus --pdf-offset. They stay until clean-up, so
every stage that reads them (align-pages, fix-gaps, resolve, review) finds
them there. prep.py writes the diffs into the same directories and leaves
the images alone.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from common import PAGES, parse_page_selection
from prep import RUN_FILE, _pdf_page_count, extract_pages, read_offset


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["prep", "extract", "clean"])
    ap.add_argument("--work", default=PAGES, type=Path)
    ap.add_argument("--pdf", default=Path("input/image.pdf"), type=Path)
    ap.add_argument("--pdf-offset", default=0, type=int,
                    help="prep: PDF page index minus printed page number, e.g. -2 "
                         "when printed page 3 is the PDF's first page")
    ap.add_argument("--pages", help="prep: only these pages, e.g. 12-21 or 3,5,9")
    args = ap.parse_args()

    if args.action == "prep":
        if not args.pdf.exists():
            sys.exit(f"images.py: no {args.pdf}, so there are no page images to extract")
        offset = args.pdf_offset
        numbers = [i - offset for i in range(1, _pdf_page_count(args.pdf) + 1) if i - offset >= 1]
        if args.pages:
            wanted = parse_page_selection(args.pages)
            numbers = [n for n in numbers if n in wanted]
        # With another offset every image would sit under the wrong number.
        if (args.work / RUN_FILE).exists() and read_offset(args.work) != offset:
            old = list(args.work.glob("*/page.jpg"))
            for f in old:
                f.unlink()
            print(f"offset changed from {read_offset(args.work)} to {offset}: "
                  f"removed {len(old)} image(s) extracted with the old one")
        args.work.mkdir(parents=True, exist_ok=True)
        (args.work / RUN_FILE).write_text(
            json.dumps({"pdf_offset": offset}, indent=2) + "\n", encoding="utf-8")
        extract_pages(args.pdf, args.work, numbers, offset)
        print(f"extracted {len(numbers)} page image(s), pages {numbers[0]}-{numbers[-1]}"
              if numbers else "no pages to extract")
        return

    if not args.work.is_dir():
        sys.exit(f"images.py: no page directories at {args.work}; run make prep-images first")
    dirs = sorted(d for d in args.work.iterdir() if d.is_dir() and d.name.isdigit())

    if args.action == "clean":
        removed = 0
        for d in dirs:
            if (d / "page.jpg").exists():
                (d / "page.jpg").unlink()
                removed += 1
            shutil.rmtree(d / "scratch", ignore_errors=True)
            if not any(d.iterdir()):
                d.rmdir()
        print(f"removed {removed} page image(s)")
        return

    if not args.pdf.exists():
        sys.exit(f"images.py: no {args.pdf}, so there are no page images to extract")
    wanted = [int(d.name) for d in dirs
              if (d / "diffs.json").exists() and not (d / "page.jpg").exists()]
    if wanted:
        extract_pages(args.pdf, args.work, wanted, read_offset(args.work))
    extracted = sum((args.work / f"{p:04d}" / "page.jpg").exists() for p in wanted)
    print(f"extracted {extracted} page image(s)")


if __name__ == "__main__":
    main()
