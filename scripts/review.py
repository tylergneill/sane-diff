#!/usr/bin/env python3
"""Stage five: build the review interface.

Emits a single self-contained review.html with the adjudicated lines and
their verdicts inlined, so it opens from the filesystem with no server.

Review is by exception: every verdict is already applied to corrected.txt.
The interface exists to reject or amend, and it writes reviews.json, which
apply.py reads back to regenerate the corrected text with human overrides.
"""

import argparse
import json
import re
import sys
from pathlib import Path

TEMPLATE = Path(__file__).with_name("review_template.html")


def die(msg):
    print(f"review.py: {msg}", file=sys.stderr)
    sys.exit(1)


def etext_lines(path, marker):
    """Return {(page, line): text} for every line of the e-text."""
    pattern = re.compile(marker)
    out = {}
    page = None
    n = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(raw)
        if m:
            page = int(m.group(1))
            n = 0
        elif page is not None:
            n += 1
            out[(page, n)] = raw
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", default="report.json", type=Path)
    ap.add_argument("--input", default="input", type=Path)
    ap.add_argument("--marker", default=r"^\s*<p\.(\d+)>\s*$")
    ap.add_argument("--reviews", default="reviews.json", type=Path)
    ap.add_argument("--out", default="review.html", type=Path)
    args = ap.parse_args()

    if not args.report.exists():
        die(f"missing {args.report}; run report.py first")
    if not TEMPLATE.exists():
        die(f"missing template at {TEMPLATE}")

    report = json.loads(args.report.read_text(encoding="utf-8"))
    lines = etext_lines(args.input / "etext.txt", args.marker)

    existing = {}
    if args.reviews.exists():
        data = json.loads(args.reviews.read_text(encoding="utf-8"))
        existing = {o["id"]: o for o in data.get("overrides", [])}

    # Group items by their line so the interface can show each change in context.
    by_line = {}
    for item in report["items"]:
        key = (item["page"], item["line"])
        by_line.setdefault(key, []).append(item)

    blocks = []
    for (page, line) in sorted(by_line):
        blocks.append({
            "page": page,
            "line": line,
            "text": lines.get((page, line), ""),
            "items": sorted(by_line[(page, line)], key=lambda i: i["id"]),
        })

    payload = {
        "totals": report["totals"],
        "blocks": blocks,
        "existing": existing,
    }

    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    args.out.write_text(html, encoding="utf-8")

    print(f"lines with changes: {len(blocks)}")
    print(f"items:              {report['totals']['items']}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
