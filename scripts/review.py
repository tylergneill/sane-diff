#!/usr/bin/env python3
"""Walk the questionable verdicts one page at a time, next to the scan.

Reads output/<run>/report.tsv and groups the selected items by page, opening each
page scan as it goes so the print can be checked against the reading.

Three modes, narrowest first:

  --overrides   `other` verdicts: the only ones that can put a reading into
                the output that neither source contains. In practice these
                are all medium, since the adjudicator prompt caps an override
                there, but a low one is permitted and is included here too.
  --low         every low-confidence verdict, whatever was chosen — the items
                an agent said it could not settle.
  --all         every low- and medium-confidence verdict (the default).

High-confidence base and suggester verdicts are never shown; with 86 of 100 items
here, reviewing them is reviewing the whole run. They are not thereby beyond
question — an agent can be confidently wrong, and nothing in the walk will
surface it. Those are found by reading the output or diffing it against the
base, and settled with --set.

--set ID=CHOICE settles one named item without walking anything, at any
confidence. It takes the reading from diffs.json rather than from you, so the
text cannot drift from the source it names, and marks the item decided_by
human. Editing the verdict file by hand does the same job with two ways to go
wrong: changing `choice` while leaving `reading` alone is silently ignored by
apply.py, which writes `reading` verbatim, and retyping `reading` can put a
third text into the output that neither source contains.

--summary does something else entirely: instead of walking items it prints a
source-by-confidence table of every verdict, high ones included, and exits.
Both it and the walk respect --pages.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from common import PAGES as PAGES_DIR, add_run_arg, verdicts_name

# Set from --run in main(); review works on one run at a time.
REPORT = None
VERDICTS = None
PAGES = Path(PAGES_DIR)


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


CHOICES = ["base", "suggester", "other"]
CONFIDENCES = ["high", "medium", "low"]


def table(headers, body):
    """Render rows as a box-drawn table; every column after the first right-aligned."""
    grid = [headers] + body
    width = [max(len(r[i]) for r in grid) for i in range(len(headers))]

    def rule(left, mid, right):
        return left + mid.join("─" * (w + 2) for w in width) + right

    def line(cells):
        out = [f" {cells[0]:<{width[0]}} "]
        out += [f" {c:>{width[i]}} " for i, c in enumerate(cells[1:], 1)]
        return "│" + "│".join(out) + "│"

    print(rule("┌", "┬", "┐"))
    print(line(headers))
    for cells in body:
        print(rule("├", "┼", "┤"))
        print(line(cells))
    print(rule("└", "┴", "┘"))


def summary(counts):
    """Cross-tabulate the adjudicated items by chosen source and confidence."""
    body = []
    for choice in CHOICES + ["total"]:
        if choice == "total":
            cells = [sum(counts[(c, f)] for c in CHOICES) for f in CONFIDENCES]
        else:
            cells = [counts[(choice, f)] for f in CONFIDENCES]
        body.append([choice] + [str(n) for n in cells] + [str(sum(cells))])
    table(["source"] + CONFIDENCES + ["total"], body)


def override(page, item_id, choice):
    """Rewrite one verdict in a page's verdict file, leaving its siblings alone.

    The reading is taken from diffs.json rather than retyped, so it cannot
    drift from the source it claims to be. Confidence becomes `high` -- a human
    looked at the scan, which is a stronger warrant than the agent's own -- and
    `decided_by: human` records whose call it was, so the reports can tell a
    confirmed reading from a confident machine one.
    """
    page_dir = PAGES / f"{page:04d}"
    verdicts_path = page_dir / VERDICTS
    diffs_path = page_dir / "diffs.json"
    if not verdicts_path.exists() or not diffs_path.exists():
        return f"page {page}: {VERDICTS} or diffs.json missing"

    diffs = json.loads(diffs_path.read_text(encoding="utf-8"))
    item = next((i for i in diffs["items"] if i["id"] == item_id), None)
    if item is None:
        return f"{item_id}: not in diffs.json"
    reading = item.get(choice, "")

    data = json.loads(verdicts_path.read_text(encoding="utf-8"))
    for v in data.get("verdicts", []):
        if v.get("id") == item_id:
            v.clear()
            v.update({"id": item_id, "choice": choice, "reading": reading,
                      "confidence": "high", "decided_by": "human"})
            break
    else:
        return f"{item_id}: not in {VERDICTS}"

    verdicts_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return None


def clear():
    """Clear the screen, falling back to blank lines where that is not possible."""
    if subprocess.run(["clear"], check=False).returncode != 0:
        print("\n" * 4)


def show(row, n=None):
    blank = "(none)"
    tag = f"{n}) " if n else "  "
    print(f"  {tag}{row['id']}  line {row['line']}  [{row['choice']}/{row['confidence']}]")
    print(f"    base  : {row['base'] or blank}")
    print(f"    sugg  : {row['suggester'] or blank}")
    print(f"    →     : {row['reading'] or blank}")
    if row.get("note"):
        print(f"    why   : {row['note']}")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_run_arg(ap)
    ap.add_argument("--pages", help="restrict to these pages, e.g. 30 or 12-24,96")
    ap.add_argument("--no-clear", action="store_true",
                    help="print every page at once instead of clearing between them")
    ap.add_argument("--summary", action="store_true",
                    help="print a source-by-confidence table of every verdict and exit")
    ap.add_argument("--set", metavar="ID=CHOICE", action="append", dest="settings",
                    help="override one verdict without walking, e.g. p0002-002=suggester; "
                         "repeatable. Works at any confidence, including high.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--overrides", action="store_true",
                      help="only `other` verdicts, at any confidence")
    mode.add_argument("--low", action="store_true",
                      help="only low-confidence verdicts, whatever was chosen")
    mode.add_argument("--all", action="store_true",
                      help="every low- and medium-confidence verdict (default)")
    args = ap.parse_args()

    global REPORT, VERDICTS
    REPORT = Path("output") / args.run / "report.tsv"
    VERDICTS = verdicts_name(args.run)

    if args.overrides:
        keep = lambda row: row["choice"] == "other"
        label = "overrides"
    elif args.low:
        keep = lambda row: row["confidence"] == "low"
        label = "low confidence"
    else:
        keep = lambda row: row["confidence"] in {"low", "medium"}
        label = "low+medium confidence"

    # --set settles a named item outright. It is the only way to reach a
    # high-confidence verdict, which the walk deliberately never shows: meld or
    # a reading eye finds those, not a confidence score.
    if args.settings:
        failed = False
        for setting in args.settings:
            item_id, _, choice = setting.partition("=")
            if choice not in CHOICES[:2]:
                print(f"{setting}: choice must be base or suggester", file=sys.stderr)
                failed = True
                continue
            match = re.fullmatch(r"p(\d{4})-\d+", item_id)
            if not match:
                print(f"{setting}: expected an id like p0002-002", file=sys.stderr)
                failed = True
                continue
            problem = override(int(match.group(1)), item_id, choice)
            if problem:
                print(problem, file=sys.stderr)
                failed = True
            else:
                print(f"{item_id} -> {choice} (decided_by: human)")
        if not failed:
            print("\nrun `make report` to pick these up")
        sys.exit(1 if failed else 0)

    if not REPORT.exists():
        sys.exit(f"review.py: {REPORT} not found; run `make report` first")

    only = parse_pages(args.pages)

    if args.summary:
        tallied = list(rows(REPORT, only))
        summary(Counter((r["choice"], r["confidence"]) for r in tallied))
        # A reviewed verdict counts as high/base like any other, so say how
        # many of these cells were settled by hand rather than by an agent.
        decided = sum(1 for r in tallied if r.get("decided_by") == "human")
        if decided:
            print(f"\n{decided} of {len(tallied)} decided in review.")
        return

    grouped = {}
    for row in rows(REPORT, only):
        # Already settled by hand; walking it again would re-ask a closed question.
        if row.get("decided_by") == "human" or not keep(row):
            continue
        grouped.setdefault(int(row["page"]), []).append(row)

    if not grouped:
        print(f"no items match [{label}]")
        return

    total = sum(len(v) for v in grouped.values())
    pages = sorted(grouped)
    # Prompting needs a terminal; clearing additionally needs somewhere to go.
    interactive = not args.no_clear and sys.stdout.isatty()
    paging = interactive and len(pages) > 1

    if not paging:
        print(f"{total} item(s) [{label}] on {len(pages)} page(s)\n")

    changed = 0
    for idx, page in enumerate(pages, 1):
        items = grouped[page]
        scan = PAGES / f"{page:04d}" / "page.jpg"
        if paging:
            clear()
        print(f"=== page {page}  ({idx}/{len(pages)} pages, "
              f"{len(items)} of {total} items)  {scan} ===")
        for n, row in enumerate(items, 1):
            show(row, n if len(items) > 1 else None)
        if scan.exists():
            # -g loads the scan without raising the viewer, so the keyboard
            # stays with this prompt and there is no focus flicker per page.
            # The trade-off: a viewer window behind the terminal stays behind.
            subprocess.run(["open", "-g", str(scan)], check=False)
        if not interactive:
            continue

        pick = "[b] base, [s] suggester" if len(items) == 1 else "[b2] base of 2, [s1] suggester of 1"
        last = idx == len(pages)
        nxt = "finish" if last else "next page"
        while True:
            try:
                reply = input(f"    [enter] {nxt}, {pick}, [ctrl-c] stop ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                reply = None
            if not reply:
                break
            choice = {"b": "base", "s": "suggester"}.get(reply[:1])
            rest = reply[1:].strip()
            if choice is None or (rest and not rest.isdigit()):
                print(f"    ? {reply!r} — expected enter, b, s, or b/s with an item number")
                continue
            if rest:
                pos = int(rest)
            elif len(items) == 1:
                pos = 1
            else:
                print(f"    ? which item — {reply[:1]}1 to {reply[:1]}{len(items)}")
                continue
            if not 1 <= pos <= len(items):
                print(f"    ? no item {pos} on this page (1 to {len(items)})")
                continue
            row = items[pos - 1]
            problem = override(page, row["id"], choice)
            if problem:
                print(f"    ! {problem}")
                continue
            row["choice"] = choice
            row["reading"] = row[choice]
            row["confidence"] = "high"
            changed += 1
            print(f"    ✓ {row['id']} → {choice} {row[choice] or '(empty)'}")
        if reply is None:
            break

    if changed:
        print(f"\n{changed} verdict(s) rewritten; run `make report` to "
              f"regenerate output/{args.run}/")


if __name__ == "__main__":
    main()
