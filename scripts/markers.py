#!/usr/bin/env python3
"""Massage, stage 1: give a text a complete set of page markers.

Takes the page markers of a source text whose markers are complete, and puts
them into a target text in place of whatever markers it had. Only marker
lines and the blank lines around them change; every other character of the
target stays as it was, and the script checks that before writing.

  markers.py run --source suggester [--target base]
  markers.py accept

--source is base, suggester, or the path to another file with the same text
(an earlier OCR output, say). --target defaults to the other input, or to
both inputs when the source is a separate file.

`run` writes the result to tmp/massage/markers/, with report.txt, and
changes nothing in input/. Inspect it, then `accept` copies it into input/,
keeping the previous version beside it as <role>.before.txt.

The placing itself is transfer_page_markers.py, copied here from hansel-data
(utils/transforms/txt, as of 8071f3e, 2026-10-26), which fuzzy-matches the text on either side of each source page break
against the target. It never places the first page's marker, so this script
puts that one where the target had it, or at the very start of the text.

report.txt lists every page, worst first. For each new marker it gives the
transfer's match score and the nearest marker the target had before: which
number, and how many letters away. Most pages should show the same number
close by. A different number close by usually means the old markers counted
differently; a marker far from any old one, or a low score, is the place to
look.
"""

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import transfer_page_markers as transfer
from common import MARKER_FORMATS, MARKERS, resolve_marker, split_pages

INPUT = Path("input")
OUT = Path("tmp/massage/markers")
ROLES = ("base", "suggester")

# An old marker within this many letters of the new one, with the same
# number, counts as agreeing with it.
AGREE = 20
# A transfer score below this is flagged.
LOW_SCORE = 0.8
# This many low scores in a row means the transfer has lost its place.
LOST_RUN = 3
# Letters of a page's opening looked for in the target, to find a gap.
SNIPPET = 30
CONTEXT = 60


def die(msg):
    print(f"markers.py: {msg}", file=sys.stderr)
    sys.exit(1)



def marker_name(regex):
    """The MARKERS name of a resolved marker regex, or None for a custom one."""
    return next((name for name, r in MARKERS.items() if r == regex), None)


def detect(text):
    """The MARKERS regex text uses, or None if it has no markers yet."""
    for regex in MARKERS.values():
        pattern = re.compile(regex)
        if any(pattern.match(line) for line in text.splitlines()):
            return regex
    return None


def letters(text):
    return sum(1 for c in text if not c.isspace())


def content(text, regex):
    """Every non-whitespace character outside the marker lines, in order."""
    pattern = re.compile(regex)
    return "".join("".join(line.split()) for line in text.splitlines()
                   if not pattern.match(line))


def markers_at(text, regex):
    """[(page_no, letters before the marker, marker line)] in text order."""
    pattern = re.compile(regex)
    found, count = [], 0
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            found.append((int(m.group(1)), count, line))
        else:
            count += letters(line)
    return found


def strip_markers(text, regex):
    """text without its marker lines, and without the extra blank lines a
    removed marker leaves behind."""
    pattern = re.compile(regex)
    out, removed_here = [], False
    for line in text.splitlines():
        if pattern.match(line):
            removed_here = True
            continue
        if removed_here and not line.strip() and (not out or not out[-1].strip()):
            continue
        removed_here = removed_here and not line.strip()
        out.append(line)
    while out and not out[0].strip():
        out.pop(0)
    return "\n".join(out) + "\n"


def raw_index(text, n):
    """Index in text of the n-th non-whitespace character (0-based); len(text)
    if there are fewer."""
    seen = 0
    for i, c in enumerate(text):
        if not c.isspace():
            if seen == n:
                return i
            seen += 1
    return len(text)


def insert_marker(text, at_letter, marker_line, transfer):
    """Put marker_line on its own, blank-line-separated, before the
    at_letter-th letter of text."""
    a, b = transfer.trim_span_around(text, raw_index(text, at_letter))
    before, after = text[:a], text[b:]
    return (before + "\n\n" if before else "") + marker_line + "\n\n" + after


def after(text, line_no, n=CONTEXT):
    """The first n characters of text after line line_no, on one line."""
    rest = " ".join(text.splitlines()[line_no + 1:line_no + 12])
    return re.sub(r"\s+", " ", rest).strip()[:n]


def render(text, old_regex, placed, style):
    """The target text with its markers changed to `placed` [(page, letter
    offset)], and nothing else touched.

    The spacing around a marker carries meaning (a blank line for a new
    paragraph, none for prose running on across the page), so the target's
    own marker lines stay where they agree:

    - an old marker at a placed position with the same number is kept as is;
    - one at a placed position with another number gets the new number, in
      place;
    - an old marker no placed one lands on loses just its own line;
    - a placed marker with no old one at its position goes in on its own
      line, without blank lines: before the line it starts, or splitting a
      line at the space where it falls.
    """
    lines = text.splitlines()
    pattern = re.compile(old_regex) if old_regex else None

    # Letter offset at which each line starts, and the old markers.
    starts, old, count = [], [], 0
    for i, line in enumerate(lines):
        starts.append(count)
        if pattern and pattern.match(line):
            old.append((i, int(pattern.match(line).group(1)), count))
        else:
            count += letters(line)

    todo = sorted(placed, key=lambda p: (p[1], p[0]))
    replace, remove = {}, set()
    for i, n, off in old:
        here = [p for p in todo if p[1] == off]
        keep = next((p for p in here if p[0] == n), None) or (here[0] if here else None)
        if keep is None:
            remove.add(i)
            continue
        todo.remove(keep)
        if keep[0] != n:
            replace[i] = style.format(n=keep[0])

    # Remaining markers to insert, grouped by the line they fall in: either
    # at a line's start (before it) or inside it (split there).
    inserts = {}
    for n, off in todo:
        target = next((i for i, line in enumerate(lines)
                       if not (pattern and pattern.match(line)) and letters(line)
                       and starts[i] <= off < starts[i] + letters(line)), len(lines))
        at = off - starts[target] if target < len(lines) else 0
        inserts.setdefault(target, []).append((at, n))

    out = []
    for i, line in enumerate(lines):
        if i in remove:
            # Don't leave two blank lines where a marker stood between them.
            if out and not out[-1].strip() and i + 1 < len(lines) and not lines[i + 1].strip():
                out.pop()
            continue
        line = replace.get(i, line)
        pieces = []
        for at, n in sorted(inserts.get(i, []), reverse=True):
            if at == 0:  # at the line's start: the marker goes above it
                pieces = [style.format(n=n), line] + pieces
                line = None
                break
            cut = raw_index(line, at)
            line, rest = line[:cut].rstrip(), line[cut:].lstrip()
            pieces = [style.format(n=n), rest] + pieces
        if line is not None:
            out.append(line)
        out += [p for p in pieces if p != ""] if pieces else []
    for at, n in sorted(inserts.get(len(lines), [])):
        out.append(style.format(n=n))
    return "\n".join(out) + "\n"


def opens_with_word(lines):
    """Whether a page's first token has a letter in it, rather than being
    punctuation or a number such as `|` or `8,`."""
    tokens = " ".join(lines).split()
    return bool(tokens) and any(c.isalpha() for c in tokens[0])


def snap_to_words(stripped, placed, word_first):
    """Move each (page, letter offset) that falls inside a token to a token
    edge. The transfer matches on letters with spaces folded away, so it can
    land a few letters off: inside a word (`bh|airavaḥ`), which goes to the
    word's nearer edge, or inside punctuation or a number (`|| 6 |<>|`,
    `8<>,`), which goes after it, since a page does not start with the
    previous verse's daṇḍas. A marker in front of free-standing punctuation
    or numbers (`vyākaravāṇīti <> | kiñca`) also moves past them, unless the
    source page itself opens that way (word_first[page] is False).
    Returns the new list and {page: letters moved}."""
    tokens = []  # (first letter offset, end offset, is a word)
    count = 0
    for tok in stripped.split():
        tokens.append((count, count + len(tok), any(c.isalpha() for c in tok)))
        count += len(tok)
    out, moved = [], {}
    for page, off in placed:
        new = off
        tok = next((t for t in tokens if t[0] < new < t[1]), None)
        if tok is not None:
            start, end, word = tok
            new = (start if new - start <= end - new else end) if word else end
        if word_first.get(page, True):
            for start, end, word in tokens:
                if start == new and not word:
                    new = end
        if new != off:
            moved[page] = new - off
        out.append((page, new))
    return out, moved


def lost_at(scores):
    """The first page of the first run of LOST_RUN low scores in a row, or None.

    The transfer searches only forward from where it put the last marker, so
    once a stretch of text one side lacks has pushed it too far ahead, every
    later page scores low. One low page is a hard boundary; a run of them is
    the transfer having lost its place.
    """
    run = []
    for page in sorted(scores):
        run = run + [page] if scores[page] < LOW_SCORE else []
        if len(run) == LOST_RUN:
            return run[0]
    return None


def missing_near(src_pages, target, lost, transfer):
    """Source pages around `lost` whose opening text the target lacks: the
    likely gap. Starts a page before `lost` and stops at the first page the
    target does have."""
    norm = transfer.normalize_with_map(target)[0]
    missing = []
    for page in [p for p in src_pages if p >= lost - 1]:
        opening = transfer.normalize_with_map("\n".join(src_pages[page]))[0][:SNIPPET]
        if len(opening) < SNIPPET or opening in norm:
            if missing or page >= lost:
                break
            continue
        missing.append(page)
    return missing


def source_role(value):
    return value if value in ROLES else None


def run(args):
    src_path = INPUT / f"{args.source}.txt" if source_role(args.source) else Path(args.source)
    if not src_path.is_file():
        die(f"no source text at {src_path}")
    if args.target:
        targets = ROLES if args.target == "both" else (args.target,)
    elif source_role(args.source):
        targets = tuple(r for r in ROLES if r != args.source)
    else:
        targets = ROLES
    if args.source in targets:
        die("the source cannot also be a target")

    src = src_path.read_text(encoding="utf-8")
    src_regex = resolve_marker("auto", src, str(src_path), die)
    src_pages = split_pages(src, src_regex, str(src_path), die)
    first_page = next(iter(src_pages))

    OUT.mkdir(parents=True, exist_ok=True)
    report, summary, lost_roles = [], [], []
    for role in targets:
        path = INPUT / f"{role}.txt"
        if not path.is_file():
            die(f"no {path}; run make init first")
        text = path.read_text(encoding="utf-8")

        old_regex = detect(text)
        old = markers_at(text, old_regex) if old_regex else []
        style_name = marker_name(old_regex) if old else marker_name(src_regex)
        style = MARKER_FORMATS.get(style_name, "<{n}>")

        stripped = strip_markers(text, old_regex) if old else text
        patched, log = transfer.transfer_page_markers(src, stripped, marker=src_regex)

        # The transfer writes <N> or <p.N>; restyle those to the target's own
        # format. Old markers are gone, so every such line is a new one.
        placed = re.compile(r"^<(?:p\.)?(\d+)>$")
        patched = "\n".join(style.format(n=placed.match(l).group(1)) if placed.match(l) else l
                            for l in patched.splitlines()) + "\n"

        # The first page's marker, which the transfer never places.
        same = [off for n, off, _ in old if n == first_page]
        first_at = same[0] if same else 0
        first_note = (f"where the old <{first_page}> was" if same
                      else "at the start of the text: no old marker for it, check by hand")
        patched = insert_marker(patched, first_at, style.format(n=first_page), transfer)

        new_regex = MARKERS.get(style_name) or old_regex or src_regex

        # Where each marker goes, in letters from the start, with any that
        # landed inside a word moved to its edge. The transfer's own text is
        # used only for these positions; the output is the target as it was,
        # with only the markers that change touched (render).
        placed = [(n, off) for n, off, _ in markers_at(patched, new_regex)]
        word_first = {n: opens_with_word(lines) for n, lines in src_pages.items()}
        placed, snapped = snap_to_words(stripped, placed, word_first)
        # An old marker with the same number within AGREE letters was placed
        # by a person, who may have had reasons the letters don't show (an
        # editorial note like `[111 is missing]`, which the transfer skips):
        # keep it where it is.
        old_at = {n: off for n, off, _ in old}
        placed = [(n, old_at[n]) if n in old_at and abs(old_at[n] - off) <= AGREE else (n, off)
                  for n, off in placed]
        snapped = {n: d for n, d in snapped.items() if dict(placed)[n] != old_at.get(n)}
        patched = render(text, old_regex, placed, style)

        if content(patched, new_regex) != content(text, old_regex or new_regex):
            die(f"{role}: placing markers changed the text itself; nothing written")

        scores = {int(m.group(1)): float(m.group(2)) for m in
                  re.finditer(r"=== PAGE (\d+) \(after \d+\) ===\nscore=([\d.]+)", log)}
        new = markers_at(patched, new_regex)
        lines = patched.splitlines()
        line_of = [i for i, l in enumerate(lines) if re.match(new_regex, l)]
        old_lines = text.splitlines()
        old_line_of = [i for i, l in enumerate(old_lines) if re.match(old_regex, l)] if old else []

        entries, numbering = [], Counter()
        new_numbers = {n for n, _, _ in new}
        for k, (n, off, _) in enumerate(new):
            near = min(range(len(old)), key=lambda j: abs(old[j][1] - off)) if old else None
            if near is None:
                status, near_txt, dist = "no old markers", "", None
            else:
                on, ooff, _ = old[near]
                dist = off - ooff
                if abs(dist) <= 200:
                    numbering[on - n] += 1
                if on == n and abs(dist) <= AGREE:
                    status = "agrees"
                elif on == n:
                    status = "moved"
                else:
                    status = "differs"
                near_txt = f"old <{on}> {dist:+d} letters"
            score = scores.get(n)
            bad = status != "agrees" or (score is not None and score < LOW_SCORE)
            rank = (0 if bad else 1, score if score is not None else 0.0)
            entry = [f"page {n}: {status}"
                     + (f", score {score:.2f}" if score is not None else ", first page, " + first_note)
                     + (f", nearest {near_txt}" if near_txt else "")
                     + (f", moved {snapped[n]:+d} letters to a word edge" if n in snapped else "")]
            src_line = next((i for i, l in enumerate(src.splitlines())
                             if re.match(src_regex, l) and int(re.match(src_regex, l).group(1)) == n), None)
            if src_line is not None:
                entry.append(f"    source:  {after(src, src_line)}")
            entry.append(f"    new:     {after(patched, line_of[k])}")
            if near is not None and status != "agrees":
                entry.append(f"    old:     {after(text, old_line_of[near])}")
            entries.append((rank, n, "\n".join(entry)))

        dropped = sorted({n for n, _, _ in old} - new_numbers)
        agree = sum(1 for _, _, e in entries if ": agrees" in e.splitlines()[0])
        flagged = sum(1 for r, _, _ in entries if r[0] == 0)
        shift = numbering.most_common(1)[0][0] if numbering else 0

        (OUT / f"{role}.txt").write_text(patched, encoding="utf-8")
        (OUT / f"{role}.transfer.log").write_text(log, encoding="utf-8")

        lost = lost_at(scores)
        if lost is not None:
            gap = missing_near(src_pages, stripped, lost, transfer)
            where = (f"the opening text of page(s) {', '.join(map(str, gap))} is not in the {role}"
                     if gap else f"no page near it is missing outright from the {role}; "
                                 f"look for a long passage one side lacks")
            warning = [f"!! LOST from page {lost} on: every later marker is unreliable.",
                       f"!! {where}.",
                       f"!! Close that gap first (stage 2, or by hand), then run this again."]
        else:
            warning = []

        head = [f"== {role} =="] + warning + [
                f"source:            {src_path} ({len(src_pages)} pages)",
                f"markers before:    {len(old)}",
                f"markers after:     {len(new)}",
                f"agree with an old marker (same number, within {AGREE} letters): {agree}",
                f"flagged below:     {flagged}"]
        if shift:
            head.append(f"old markers mostly number {shift:+d} from the new ones: "
                        f"they seem to count pages differently")
        if dropped:
            head.append(f"old marker numbers the source lacks: {dropped}")
        if lost is not None:
            lost_roles.append(role)
        summary += head + [""]
        report += head + [""] + [e for _, _, e in sorted(entries)] + [""]

    (OUT / "report.txt").write_text("\n".join(report), encoding="utf-8")
    (OUT / "run.json").write_text(json.dumps({"source": str(src_path), "targets": list(targets),
                                              "lost": lost_roles}, indent=2) + "\n",
                                  encoding="utf-8")
    print("\n".join(summary))
    print(f"wrote {', '.join(str(OUT / f'{r}.txt') for r in targets)} and {OUT / 'report.txt'}")
    if lost_roles:
        print(f"not acceptable as it stands: the transfer lost its place in {', '.join(lost_roles)}")
    else:
        print("inspect them, e.g. meld input/<role>.txt " + str(OUT / "<role>.txt")
              + ", then: make massage-markers-accept")


def accept(_args):
    run_file = OUT / "run.json"
    if not run_file.exists():
        die("nothing to accept; run make massage-markers first")
    run_info = json.loads(run_file.read_text(encoding="utf-8"))
    if run_info.get("lost"):
        die(f"the last run lost its place in {', '.join(run_info['lost'])}; close the gap "
            f"its report names and run make massage-markers again")
    for role in run_info["targets"]:
        new, cur = OUT / f"{role}.txt", INPUT / f"{role}.txt"
        shutil.copyfile(cur, OUT / f"{role}.before.txt")
        shutil.copyfile(new, cur)
        print(f"{cur}  <-  {new}  (previous kept as {OUT / f'{role}.before.txt'})")
    run_file.unlink()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--source", required=True,
                   help="base, suggester, or a path to a text with complete markers")
    r.add_argument("--target", choices=list(ROLES) + ["both"])
    sub.add_parser("accept")
    args = ap.parse_args()
    run(args) if args.cmd == "run" else accept(args)


if __name__ == "__main__":
    main()
