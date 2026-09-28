#!/usr/bin/env python3
"""Item unit: merge one run's verdicts into report.tsv.

Walks tmp/pages in page order, joins each verdict back to its diff item,
and writes one row per adjudicated item. Tab-separated, because Devanagari
text and transliteration both tend to contain commas. Also writes a filtered
view holding only the rows flagged for human review.
"""

import argparse
import json
import sys
from pathlib import Path

from common import PAGES, add_run_arg, verdicts_name

COLUMNS = ["page", "line", "id", "base", "suggester", "reading", "choice", "confidence",
           "decided_by", "note"]
CHOICES = ("base", "suggester", "other")
CONFIDENCES = ("high", "medium", "low")


def clean(value):
    """Flatten a field so it cannot break the TSV structure."""
    text = "" if value is None else str(value)
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def load_page(page_dir, run, problems):
    """Join one page's verdicts onto its diff items. Returns a list of rows."""
    diffs_path = page_dir / "diffs.json"
    verdicts_path = page_dir / verdicts_name(run)
    if not diffs_path.exists():
        return []  # the two texts agree on this page: nothing to adjudicate
    if not verdicts_path.exists():
        problems.append(f"{page_dir.name}: no {verdicts_path.name} yet")
        return []

    diffs = json.loads(diffs_path.read_text(encoding="utf-8"))
    items = {item["id"]: item for item in diffs["items"]}

    try:
        verdicts = json.loads(verdicts_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        problems.append(f"{page_dir.name}: {verdicts_path.name} is not valid JSON ({exc})")
        return []

    rows = []
    seen = set()
    for verdict in verdicts.get("verdicts", []):
        vid = verdict.get("id")
        item = items.get(vid)
        if item is None:
            problems.append(f"{page_dir.name}: verdict {vid!r} matches no diff item")
            continue
        if vid in seen:
            problems.append(f"{page_dir.name}: duplicate verdict for {vid}")
            continue
        seen.add(vid)

        choice = verdict.get("choice", "")
        if choice not in CHOICES:
            problems.append(f"{page_dir.name}: {vid} has unknown choice {choice!r}")
        confidence = verdict.get("confidence", "")
        if confidence not in CONFIDENCES:
            problems.append(f"{page_dir.name}: {vid} has unknown confidence {confidence!r}")

        if choice == "other" and confidence == "high":
            problems.append(f"{page_dir.name}: {vid} is 'other' at high confidence; "
                            f"an override of both sources is never that certain")

        reading = verdict.get("reading")
        if reading is None:
            reading = item.get(choice, "") if choice in ("base", "suggester") else ""
            if choice == "other":
                problems.append(f"{page_dir.name}: {vid} is 'other' with no reading")

        rows.append({
            "page": item["page"],
            "line": item["line"],
            "word_index": item.get("word_index", 0),
            "id": vid,
            "base": clean(item.get("base")),
            "suggester": clean(item.get("suggester")),
            "reading": clean(reading),
            "choice": clean(choice),
            "confidence": clean(confidence),
            # "agent" unless a human overrode the verdict in review.py.
            "decided_by": clean(verdict.get("decided_by") or "agent"),
            "note": clean(verdict.get("note")),
        })

    missing = [i for i in items if i not in seen]
    if missing:
        problems.append(f"{page_dir.name}: {len(missing)} item(s) with no verdict "
                        f"({', '.join(sorted(missing)[:5])}{'...' if len(missing) > 5 else ''})")
    return rows


def flagged(row):
    """Rows needing human eyes: an agent override, or a weak reading.

    A verdict a human already decided in review is settled, however it started,
    so it drops off the list rather than asking to be looked at twice.
    """
    if row["decided_by"] == "human":
        return False
    return row["choice"] == "other" or row["confidence"] == "low"


def write_tsv(path, rows):
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            fh.write("\t".join(str(row[c]) for c in COLUMNS) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=PAGES, type=Path)
    add_run_arg(ap)
    ap.add_argument("--out", default=None, type=Path, help="default: output/<run>/report.tsv")
    ap.add_argument("--flagged-out", default=None, type=Path,
                    help="default: alongside --out, named <stem>.flagged.tsv")
    ap.add_argument("--json-out", default=None, type=Path,
                    help="default: alongside --out, named <stem>.json")
    ap.add_argument("--verdicts-out", default=None, type=Path,
                    help="every page's verdicts in one searchable file; "
                         "default: output/<run>/verdicts.all.json")
    args = ap.parse_args()

    if not args.work.is_dir():
        print(f"report.py: no work directory at {args.work}", file=sys.stderr)
        sys.exit(1)

    args.out = args.out or Path("output") / args.run / "report.tsv"
    args.verdicts_out = args.verdicts_out or args.out.parent / "verdicts.all.json"
    flagged_out = args.flagged_out or args.out.with_suffix(".flagged.tsv")

    problems = []
    rows = []
    for page_dir in sorted(p for p in args.work.iterdir() if p.is_dir()):
        rows.extend(load_page(page_dir, args.run, problems))

    rows.sort(key=lambda r: (r["page"], r["line"], r["id"]))
    flagged_rows = [r for r in rows if flagged(r)]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_tsv(args.out, rows)
    write_tsv(flagged_out, flagged_rows)

    for row in rows:
        row["flagged"] = flagged(row)

    by_choice = {c: sum(1 for r in rows if r["choice"] == c) for c in CHOICES}
    by_confidence = {c: sum(1 for r in rows if r["confidence"] == c) for c in CONFIDENCES}

    print(f"items adjudicated: {len(rows)}")
    print(f"  base: {by_choice['base']}   suggester: {by_choice['suggester']}   other: {by_choice['other']}")
    print(f"  confidence — high: {by_confidence['high']}  "
          f"medium: {by_confidence['medium']}  low: {by_confidence['low']}")
    decided = sum(1 for r in rows if r["decided_by"] == "human")
    if decided:
        print(f"  decided in review: {decided}")
    json_out = args.json_out or args.out.with_suffix(".json")
    json_out.write_text(json.dumps({
        "totals": {
            "items": len(rows),
            "by_choice": by_choice,
            "by_confidence": by_confidence,
            "flagged": len(flagged_rows),
        },
        "items": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # The per-page verdict files stay the unit of work -- the dispatcher
    # resumes on their presence and the agents write them independently. This
    # is a read-only consolidation of them, for searching and diffing.
    pages = {}
    for row in rows:
        verdict = {"id": row["id"], "choice": row["choice"],
                   "reading": row["reading"], "confidence": row["confidence"]}
        if row["note"]:
            verdict["note"] = row["note"]
        if row["decided_by"] == "human":
            verdict["decided_by"] = "human"
        pages.setdefault(row["page"], []).append(verdict)

    args.verdicts_out.parent.mkdir(parents=True, exist_ok=True)
    args.verdicts_out.write_text(json.dumps(
        [{"page": page, "verdicts": pages[page]} for page in sorted(pages)],
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"flagged for review: {len(flagged_rows)}")
    print(f"wrote {args.out}, {flagged_out}, {json_out} and {args.verdicts_out}")

    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)


if __name__ == "__main__":
    main()
