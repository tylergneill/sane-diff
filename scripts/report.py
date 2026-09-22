#!/usr/bin/env python3
"""Stage three: merge every verdicts.json into report.tsv.

Walks work/pages in page order, joins each verdict back to its diff item,
and writes one row per adjudicated item. Tab-separated, because Devanagari
text and transliteration both tend to contain commas. Also writes a filtered
view holding only the rows flagged for human review.
"""

import argparse
import json
import sys
from pathlib import Path

COLUMNS = ["page", "line", "id", "etext", "ocr", "reading", "choice", "confidence", "note"]
CHOICES = ("etext", "ocr", "other")
CONFIDENCES = ("high", "medium", "low")


def clean(value):
    """Flatten a field so it cannot break the TSV structure."""
    text = "" if value is None else str(value)
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def load_page(page_dir, problems):
    """Join one page's verdicts onto its diff items. Returns a list of rows."""
    diffs_path = page_dir / "diffs.json"
    verdicts_path = page_dir / "verdicts.json"
    if not diffs_path.exists():
        problems.append(f"{page_dir.name}: no diffs.json")
        return []
    if not verdicts_path.exists():
        problems.append(f"{page_dir.name}: not yet adjudicated (no verdicts.json)")
        return []

    diffs = json.loads(diffs_path.read_text(encoding="utf-8"))
    items = {item["id"]: item for item in diffs["items"]}

    try:
        verdicts = json.loads(verdicts_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        problems.append(f"{page_dir.name}: verdicts.json is not valid JSON ({exc})")
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

        reading = verdict.get("reading")
        if reading is None:
            reading = item.get(choice, "") if choice in ("etext", "ocr") else ""
            if choice == "other":
                problems.append(f"{page_dir.name}: {vid} is 'other' with no reading")

        rows.append({
            "page": item["page"],
            "line": item["line"],
            "word_index": item.get("word_index", 0),
            "id": vid,
            "etext": clean(item.get("etext")),
            "ocr": clean(item.get("ocr")),
            "reading": clean(reading),
            "choice": clean(choice),
            "confidence": clean(confidence),
            "note": clean(verdict.get("note")),
        })

    missing = [i for i in items if i not in seen]
    if missing:
        problems.append(f"{page_dir.name}: {len(missing)} item(s) with no verdict "
                        f"({', '.join(sorted(missing)[:5])}{'...' if len(missing) > 5 else ''})")
    return rows


def flagged(row):
    """Rows needing human eyes: an override, or an admitted weak reading."""
    return row["choice"] == "other" or row["confidence"] == "low"


def write_tsv(path, rows):
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            fh.write("\t".join(str(row[c]) for c in COLUMNS) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="work/pages", type=Path)
    ap.add_argument("--out", default="report.tsv", type=Path)
    ap.add_argument("--flagged-out", default=None, type=Path,
                    help="default: alongside --out, named <stem>.flagged.tsv")
    ap.add_argument("--json-out", default=None, type=Path,
                    help="default: alongside --out, named <stem>.json")
    ap.add_argument("--reviews", default="reviews.json", type=Path,
                    help="human overrides; folded into the JSON when present")
    args = ap.parse_args()

    if not args.work.is_dir():
        print(f"report.py: no work directory at {args.work}", file=sys.stderr)
        sys.exit(1)

    flagged_out = args.flagged_out or args.out.with_suffix(".flagged.tsv")

    problems = []
    rows = []
    for page_dir in sorted(p for p in args.work.iterdir() if p.is_dir()):
        rows.extend(load_page(page_dir, problems))

    rows.sort(key=lambda r: (r["page"], r["line"], r["id"]))
    flagged_rows = [r for r in rows if flagged(r)]

    write_tsv(args.out, rows)
    write_tsv(flagged_out, flagged_rows)

    overrides = {}
    if args.reviews.exists():
        data = json.loads(args.reviews.read_text(encoding="utf-8"))
        overrides = {o["id"]: o for o in data.get("overrides", [])}
    for row in rows:
        row["flagged"] = flagged(row)
        row["overridden"] = row["id"] in overrides

    by_choice = {c: sum(1 for r in rows if r["choice"] == c) for c in CHOICES}
    by_confidence = {c: sum(1 for r in rows if r["confidence"] == c) for c in CONFIDENCES}

    print(f"items adjudicated: {len(rows)}")
    print(f"  etext: {by_choice['etext']}   ocr: {by_choice['ocr']}   other: {by_choice['other']}")
    print(f"  confidence — high: {by_confidence['high']}  "
          f"medium: {by_confidence['medium']}  low: {by_confidence['low']}")
    json_out = args.json_out or args.out.with_suffix(".json")
    json_out.write_text(json.dumps({
        "totals": {
            "items": len(rows),
            "by_choice": by_choice,
            "by_confidence": by_confidence,
            "flagged": len(flagged_rows),
            "overridden": sum(1 for r in rows if r["overridden"]),
        },
        "items": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"flagged for review: {len(flagged_rows)}")
    print(f"wrote {args.out}, {flagged_out} and {json_out}")

    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)


if __name__ == "__main__":
    main()
