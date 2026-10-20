#!/usr/bin/env python3
"""Add an offset to every page marker in a text file.

For texts whose markers count PDF pages from 1 rather than giving printed
page numbers: run the pipeline on them as they are, with no PDF_OFFSET, and
renumber the final text at the end.

    renumber.py corrected.txt --offset 151        # writes corrected.renumbered.txt
    renumber.py corrected.txt --offset 151 --in-place

The offset is added to each marker's number, so when the PDF starts at printed
page 152 it is 151, the opposite sign of the PDF_OFFSET prep-pending would
have taken. Only the number changes; the rest of each marker line is kept.
"""

import argparse
import re
import sys
from pathlib import Path

from common import marker_regex, resolve_marker


def die(msg):
    print(f"renumber.py: {msg}", file=sys.stderr)
    sys.exit(1)


def renumber(text, marker, offset):
    """text with offset added to each marker's number, and how many changed."""
    pattern = re.compile(marker)
    lines = text.splitlines(keepends=True)
    count = 0
    for i, line in enumerate(lines):
        m = pattern.match(line.rstrip("\r\n"))
        if not m:
            continue
        new = int(m.group(1)) + offset
        if new < 1:
            die(f"line {i + 1}: page {m.group(1)} would become {new}")
        lines[i] = line[:m.start(1)] + str(new) + line[m.end(1):]
        count += 1
    return "".join(lines), count


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--offset", required=True, type=int,
                    help="added to each page number, e.g. 151 when the PDF starts "
                         "at printed page 152")
    ap.add_argument("--marker", default="auto", type=marker_regex,
                    help="page marker: auto (default: <p.12> or === 12 ===), "
                         "or a regex whose group 1 is the page number")
    ap.add_argument("--in-place", action="store_true",
                    help="overwrite the file instead of writing <name>.renumbered<ext>")
    args = ap.parse_args()

    if not args.file.exists():
        die(f"no such file: {args.file}")
    text = args.file.read_text(encoding="utf-8")
    marker = resolve_marker(args.marker, text, str(args.file), die)
    out_text, count = renumber(text, marker, args.offset)

    out = args.file if args.in_place else args.file.with_name(
        f"{args.file.stem}.renumbered{args.file.suffix}")
    out.write_text(out_text, encoding="utf-8")
    print(f"renumbered {count} page marker(s) by {args.offset:+d} into {out}")


if __name__ == "__main__":
    main()
