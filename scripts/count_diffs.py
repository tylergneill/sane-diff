#!/usr/bin/env python3
"""Print how many differences there are between two text files.

Counts the units Meld would highlight: the files are diffed line by line,
and each changed block is then diffed character by character, so every
yellow inline highlight counts once. A block that exists on only one side
(pure insertion or deletion) has no inline highlights and counts as one.

    count_diffs.py a.txt b.txt            # inline (Meld yellow) units
    count_diffs.py a.txt b.txt --unit word
    count_diffs.py a.txt b.txt --unit block  # Meld's blue/green/red blocks
    count_diffs.py a.txt b.txt -v         # also list each difference

In -v output each line is `A-LINE:B-LINE  ...context[a→b]context...`, where
∅ means "nothing on this side" and ⏎ stands for a line break.
"""

import argparse
import difflib
import unicodedata
from pathlib import Path

CONTEXT = 15  # characters (or words, for --unit word) shown either side


def ops(a, b):
    """Non-equal opcodes between two sequences."""
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    return [op for op in matcher.get_opcodes() if op[0] != "equal"]


def show(seq, sep):
    return sep.join(seq).replace("\n", "⏎") or "∅"


def diffs(a_text, b_text, unit):
    """Yield (a_lineno, b_lineno, description) for each difference."""
    alines, blines = a_text.splitlines(), b_text.splitlines()
    for tag, i1, i2, j1, j2 in ops(alines, blines):
        if unit == "block" or tag != "replace":
            yield i1 + 1, j1 + 1, f"[{show(alines[i1:i2], chr(10))}→{show(blines[j1:j2], chr(10))}]"
            continue
        achunk = "\n".join(alines[i1:i2])
        bchunk = "\n".join(blines[j1:j2])
        sep, ctx = "", CONTEXT
        if unit == "word":
            achunk, bchunk = achunk.split(), bchunk.split()
            sep, ctx = " ", 3
        for _, k1, k2, l1, l2 in ops(achunk, bchunk):
            # Line numbers: line breaks before the change, in each chunk.
            aline = i1 + 1 + (achunk[:k1].count("\n") if unit == "char" else 0)
            bline = j1 + 1 + (bchunk[:l1].count("\n") if unit == "char" else 0)
            before = show(achunk[max(0, k1 - ctx):k1], sep) if k1 else ""
            after = show(achunk[k2:k2 + ctx], sep) if k2 < len(achunk) else ""
            yield aline, bline, (f"{before}{sep}[{show(achunk[k1:k2], sep)}→"
                                 f"{show(bchunk[l1:l2], sep)}]{sep}{after}").strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--unit", choices=["char", "word", "block"], default="char",
                    help="char = Meld's inline highlights (default)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list each difference on its own line before the count")
    args = ap.parse_args()

    # NFC so that ṅ and n + combining dot count as the same character.
    a, b = (unicodedata.normalize("NFC", p.read_text(encoding="utf-8"))
            for p in (args.a, args.b))
    total = 0
    for aline, bline, text in diffs(a, b, args.unit):
        total += 1
        if args.verbose:
            print(f"{aline}:{bline}\t{text}")
    print(total)


if __name__ == "__main__":
    main()
