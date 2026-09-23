#!/usr/bin/env python3
"""Stage three: apply every verdict to the e-text.

Writes corrected.txt — same page markers and line structure as the input,
so it diffs cleanly against etext.txt and shows only real changes — and
corrected.marked.txt, the same text with each adjudicated word marked by
confidence and choice.

Every verdict is applied regardless of confidence. A text with only the
confident changes applied is neither the original nor the corrected version,
and reconciling it by hand is the work this pipeline exists to avoid.
Confidence governs how a change is marked, not whether it is made.

Corrections are made by editing a page's verdicts.json and re-running this
script; diff the output against input/etext.txt in a diff viewer to review.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Marked-file annotations. `other` is distinct from low confidence: it is the
# agent asserting a reading neither source proposed, not a weak nod to one.
MARKS = {
    ("etext", "high"): "",
    ("etext", "medium"): "~",
    ("etext", "low"): "?",
    ("ocr", "high"): "+",
    ("ocr", "medium"): "+~",
    ("ocr", "low"): "+?",
    ("other", "high"): "!",
    ("other", "medium"): "!~",
    ("other", "low"): "!?",
}


def die(msg):
    print(f"apply.py: {msg}", file=sys.stderr)
    sys.exit(1)


def split_pages_with_markers(text, marker):
    """Split into [(marker_line_or_None, page_no_or_None, [lines])] blocks.

    Unlike prep.py's splitter this keeps the marker lines themselves, so the
    output can be reassembled byte-for-byte apart from the words we change.
    """
    pattern = re.compile(marker)
    blocks = []
    preamble = []
    current_marker = None
    current_page = None
    lines = []
    for raw in text.splitlines():
        m = pattern.match(raw)
        if m:
            if current_marker is None and preamble:
                blocks.append((None, None, preamble))
                preamble = []
            elif current_marker is not None:
                blocks.append((current_marker, current_page, lines))
            current_marker = raw
            current_page = int(m.group(1))
            lines = []
        elif current_marker is None:
            preamble.append(raw)
        else:
            lines.append(raw)
    if current_marker is not None:
        blocks.append((current_marker, current_page, lines))
    elif preamble:
        blocks.append((None, None, preamble))
    return blocks


def load_verdicts(work):
    """Return {(page, line): [item dicts]} joined with their verdicts."""
    by_line = {}
    problems = []
    for page_dir in sorted(p for p in work.iterdir() if p.is_dir()):
        diffs_path = page_dir / "diffs.json"
        verdicts_path = page_dir / "verdicts.json"
        if not diffs_path.exists() or not verdicts_path.exists():
            continue
        diffs = json.loads(diffs_path.read_text(encoding="utf-8"))
        items = {i["id"]: i for i in diffs["items"]}
        try:
            verdicts = json.loads(verdicts_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{page_dir.name}: verdicts.json is not valid JSON ({exc})")
            continue
        for v in verdicts.get("verdicts", []):
            item = items.get(v.get("id"))
            if item is None:
                continue
            choice = v.get("choice", "")
            reading = v.get("reading")
            if reading is None:
                reading = item.get(choice, "") if choice in ("etext", "ocr") else ""
            by_line.setdefault((item["page"], item["line"]), []).append({
                "id": v["id"],
                "word_index": item["word_index"],
                "word_span": item.get("word_span", 1),
                "etext": item.get("etext", ""),
                "ocr": item.get("ocr", ""),
                "reading": reading,
                "choice": choice,
                "confidence": v.get("confidence", ""),
            })
    return by_line, problems


def rebuild_line(line, items, marked):
    """Apply this line's verdicts to one e-text line.

    Works on the word list rather than by string substitution, so a word that
    appears twice on a line is not changed in the wrong place. Items are keyed
    by word_index; several may share an index when OCR merged tokens, in which
    case they are applied in id order and empty readings drop the word.

    An item's word_span says how many e-text words it replaces: a spacing
    item covering `tvak cakṣuṣī` has span 2, so the second word is consumed
    by the item rather than emitted again on its own. A span of 0 is an
    insertion before the word at word_index (a word only the OCR has); it
    replaces nothing, so that e-text word is still emitted after it.
    """
    words = line.split()
    # Group by index: a merge puts the joined token at one index and leaves
    # its partner resolving to empty at another.
    by_index = {}
    for it in sorted(items, key=lambda i: i["id"]):
        by_index.setdefault(it["word_index"], []).append(it)

    def emit(hit):
        reading = hit["reading"]
        if reading == "":
            return  # the word is absorbed into a neighbouring token
        if marked:
            mark = MARKS.get((hit["choice"], hit["confidence"]), "?")
            out.append(f"{reading}{{{mark}}}" if mark else reading)
        else:
            out.append(reading)

    out = []
    absorbed = 0
    for idx, word in enumerate(words):
        hits = by_index.pop(idx, None)
        if not hits:
            if absorbed > 0:
                absorbed -= 1  # consumed by a preceding multi-word item
                continue
            out.append(word)
            continue
        inserts = [h for h in hits if h.get("word_span", 1) == 0]
        replaces = [h for h in hits if h.get("word_span", 1) != 0]
        for hit in inserts:
            emit(hit)
        if not replaces:
            if absorbed > 0:
                absorbed -= 1
                continue
            out.append(word)
            continue
        absorbed = max(h.get("word_span", 1) for h in replaces) - 1
        for hit in replaces:
            emit(hit)

    # Insertions past the end of the e-text line (OCR had a word the e-text lacks).
    for idx in sorted(by_index):
        for hit in by_index[idx]:
            emit(hit)

    rebuilt = " ".join(out)
    # Preserve the original leading indentation.
    indent = line[:len(line) - len(line.lstrip())]
    return indent + rebuilt if rebuilt else line


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="input", type=Path)
    ap.add_argument("--work", default="tmp/pages", type=Path)
    ap.add_argument("--marker", default=r"^\s*<p\.(\d+)>\s*$")
    ap.add_argument("--out", default="output/corrected.txt", type=Path)
    ap.add_argument("--marked-out", default=None, type=Path,
                    help="default: alongside --out, named <stem>.marked<suffix>")
    args = ap.parse_args()

    etext_path = args.input / "etext.txt"
    if not etext_path.exists():
        die(f"missing {etext_path}")
    if not args.work.is_dir():
        die(f"no work directory at {args.work}")

    marked_out = args.marked_out or args.out.with_suffix(f".marked{args.out.suffix}")

    by_line, problems = load_verdicts(args.work)
    if not by_line:
        die("no verdicts found; run the adjudication stage first")

    text = etext_path.read_text(encoding="utf-8")
    blocks = split_pages_with_markers(text, args.marker)

    clean_out, mark_out = [], []
    applied = 0
    adjudicated_pages = {p for (p, _) in by_line}
    for marker_line, page_no, lines in blocks:
        if marker_line is not None:
            clean_out.append(marker_line)
            mark_out.append(marker_line)
        # Pages never adjudicated pass through untouched.
        touched = page_no in adjudicated_pages
        for i, line in enumerate(lines, start=1):
            items = by_line.get((page_no, i)) if touched else None
            if not items:
                clean_out.append(line)
                mark_out.append(line)
                continue
            clean_out.append(rebuild_line(line, items, marked=False))
            mark_out.append(rebuild_line(line, items, marked=True))
            applied += len(items)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(clean_out) + "\n", encoding="utf-8")
    marked_out.write_text("\n".join(mark_out) + "\n", encoding="utf-8")

    print(f"verdicts applied: {applied}")
    print(f"pages touched:    {len(adjudicated_pages)}")
    print(f"wrote {args.out} and {marked_out}")

    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)


if __name__ == "__main__":
    main()
