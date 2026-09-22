#!/usr/bin/env python3
"""List page directories still awaiting adjudication.

A page is pending if it has diffs.json but no verdicts.json. This is what
makes a run resumable: re-run it after an interruption and only the
unfinished pages come back. The dispatcher uses it to decide what to fan
out; a human can use it to see how far along a run is.
"""

import argparse
import json
import sys
from pathlib import Path


def pending_pages(work):
    out = []
    for page_dir in sorted(p for p in work.iterdir() if p.is_dir()):
        if not (page_dir / "diffs.json").exists():
            continue
        if (page_dir / "verdicts.json").exists():
            continue
        try:
            diffs = json.loads((page_dir / "diffs.json").read_text(encoding="utf-8"))
            count = len(diffs.get("items", []))
        except (json.JSONDecodeError, OSError):
            count = -1
        out.append((page_dir, count))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="tmp/pages", type=Path)
    ap.add_argument("--list", action="store_true",
                    help="one line per pending page; what the dispatcher reads")
    args = ap.parse_args()

    if not args.work.is_dir():
        print(f"pending.py: no work directory at {args.work}", file=sys.stderr)
        sys.exit(1)

    pending = pending_pages(args.work)
    if args.list:
        for page_dir, count in pending:
            print(f"{page_dir}\t{count} item(s)")
        return
    if not pending:
        print("all pages adjudicated")
        return
    items = sum(c for _, c in pending if c >= 0)
    print(f"{len(pending)} page(s) pending, {items} item(s)")


if __name__ == "__main__":
    main()
