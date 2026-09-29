#!/usr/bin/env python3
"""Page images: extract them from input/image.pdf, or clean them away.

The images take far more room than anything else in tmp/, and are only
needed while a vision run is reading them or a person is reviewing against
them. So each resolve run cleans them up when it finishes, and review brings
them back.

  images.py extract   page.jpg for every page directory with a diffs.json
  images.py clean     delete every page.jpg, and the scratch/ crops agents made

extract uses the PDF offset prep.py recorded, so each image comes from the
same PDF page the resolve run saw.
"""

import argparse
import shutil
import sys
from pathlib import Path

from common import PAGES
from prep import extract_pages, read_offset


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["extract", "clean"])
    ap.add_argument("--work", default=PAGES, type=Path)
    ap.add_argument("--pdf", default=Path("input/image.pdf"), type=Path)
    args = ap.parse_args()

    if not args.work.is_dir():
        sys.exit(f"images.py: no page directories at {args.work}; run prep first")
    dirs = sorted(d for d in args.work.iterdir() if d.is_dir() and d.name.isdigit())

    if args.action == "clean":
        removed = 0
        for d in dirs:
            if (d / "page.jpg").exists():
                (d / "page.jpg").unlink()
                removed += 1
            shutil.rmtree(d / "scratch", ignore_errors=True)
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
