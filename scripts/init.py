#!/usr/bin/env python3
"""Start a new text: clear input/, tmp/ and output/, then copy the sources in.

input/notes.md is kept, since it often carries over between texts of one
edition; delete it by hand when it does not. Everything else in input/ goes.

tmp/ and output/ are only cleared after you confirm, when there is anything
in them. tmp/ holds the Gemini cost ledger (tmp/usage/) as well as the
verdicts, so clearing it loses both.

  init.py --base B.txt --suggester S.txt [--image I.pdf]
"""

import argparse
import shutil
import sys
from pathlib import Path

INPUT = Path("input")
KEEP = {"notes.md"}
CLEARED = (Path("tmp"), Path("output"))


def contents(path):
    return sorted(path.iterdir()) if path.is_dir() else []


def to_clear(path):
    """What clearing this directory would delete; input/ keeps notes.md."""
    return [p for p in contents(path) if not (path == INPUT and p.name in KEEP)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, type=Path)
    ap.add_argument("--suggester", required=True, type=Path)
    ap.add_argument("--image", type=Path, help="the PDF of the page images; optional")
    args = ap.parse_args()

    # Check everything before touching anything, so a typo in one path
    # cannot leave the old inputs deleted and the new ones not copied.
    sources = {"base.txt": args.base, "suggester.txt": args.suggester}
    if args.image:
        sources["image.pdf"] = args.image
    missing = [str(p) for p in sources.values() if not p.is_file()]
    if missing:
        sys.exit(f"init.py: not found: {', '.join(missing)}")

    busy = [d for d in CLEARED if contents(d)]
    if busy:
        print("This will delete everything in:")
        for d in busy:
            names = [p.name for p in contents(d)]
            more = f" and {len(names) - 6} more" if len(names) > 6 else ""
            print(f"  {d}/  ({', '.join(names[:6])}{more})")
        if (Path("tmp") / "usage").is_dir():
            print("including the Gemini cost ledger in tmp/usage/")
        if not sys.stdin.isatty():
            sys.exit("init.py: not a terminal, so not asking; nothing deleted")
        if input("Delete? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("nothing deleted")
    for d in CLEARED:
        shutil.rmtree(d, ignore_errors=True)

    INPUT.mkdir(exist_ok=True)
    for p in to_clear(INPUT):
        shutil.rmtree(p) if p.is_dir() else p.unlink()

    for name, src in sources.items():
        shutil.copyfile(src, INPUT / name)
        print(f"{INPUT / name}  <-  {src}")
    kept = [n for n in KEEP if (INPUT / n).exists()]
    if kept:
        print(f"kept {', '.join(str(INPUT / n) for n in kept)}")
    if not args.image:
        print("no image: vision runs are unavailable for this text")


if __name__ == "__main__":
    main()
