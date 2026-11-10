#!/usr/bin/env python3
"""align-lines: set out the base's lines, then carry that layout over to
the suggester, so the two line up line by line.

  lines.py prep [--pages 3-5] [--model sonnet]
                    set up each page for its agent; print the pages
                    still to do
  lines.py apply    check the agents' pages and write tmp/lines/base.txt,
                    suggester.txt and report.txt

make align-lines runs both inside a Claude session (agents/align-lines.md),
with a workflow between them that gives each page to an agent
(agents/line-setter.md). The agent sets out the base page's lines from the
page image and input/notes_lines.md: paragraphs, verses, headings. It
changes only whitespace: every word stays, in order, spelled as it was.

apply then
- checks each page: the base's words must be exactly as they were, and the
  page must start and end as it did (whether it opens a new paragraph or
  runs on from the page before). A page that fails keeps its old layout
  and is reported;
- carries the base's layout over to the suggester: the two are aligned
  word by word, and each break between two suggester words takes the
  whitespace between the matching base words. Where the texts differ, the
  suggester's words keep to the base's line;
- writes both texts whole into tmp/lines/, and changes nothing in input/.

prep writes, per page, tmp/lines/pages/NNNN/:
  base.txt         the base page, for the agent to edit
  before/base.txt  the same, untouched
A page that already has done.json is kept as it is, so an interrupted run
picks up where it stopped.
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

from common import PAGES, parse_page_selection
from gaps import ROLES, load, norm

INPUT = Path("input")
OUT = Path("tmp/lines")
AGENTS = Path(__file__).resolve().parent.parent / "agents"

WORKFLOW = """export const meta = {
  name: 'align-lines',
  description: 'Per page: set out the base page\\'s lines from the image',
  phases: [{ title: 'Set out' }],
}
const PROMPT = %s
const MODEL = %s
await parallel(args.map(dir => () =>
  agent(PROMPT + '\\n' + dir, Object.assign(
    { label: dir.split('/').pop(), phase: 'Set out', agentType: 'general-purpose' },
    MODEL ? { model: MODEL } : {}))))
"""


def die(msg):
    print(f"lines.py: {msg}", file=sys.stderr)
    sys.exit(1)


def page_text(lines, blocks, page):
    return "\n".join(lines[slice(*blocks[page])])


def parts(text):
    """(leading whitespace, [words], [whitespace after each word but the
    last], trailing whitespace)."""
    body = text.strip()
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):] if body else ""
    if not body:
        return text, [], [], ""
    pieces = re.split(r"(\s+)", body)
    return lead, pieces[0::2], pieces[1::2], trail


def join(lead, words, seps, trail):
    out = [lead]
    for k, w in enumerate(words):
        out.append(w)
        if k < len(seps):
            out.append(seps[k])
    out.append(trail)
    return "".join(out)


def strongest(seps):
    """Of several separators, the one with the most line breaks."""
    return max(seps, key=lambda s: (s.count("\n"), len(s))) if seps else " "


def project(base, sugg):
    """The suggester page laid out as the base page is.

    Each suggester word is matched to a base word: one to one where the two
    agree, spread evenly where they differ, and a word only the suggester
    has goes with the base word before it. The break between two suggester
    words is then the strongest whitespace between their base words (most
    line breaks), so a paragraph or verse break survives even where a word
    around it differs or is missing; two words matched to the same base
    word are joined by a space."""
    blead, bw, bseps, btrail = parts(base)
    _, sw, _, _ = parts(sugg)
    if not sw or not bw:
        return join(blead, sw, [" "] * max(0, len(sw) - 1), btrail)
    at = [0] * len(sw)
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, [norm(w) for w in bw], [norm(w) for w in sw], autojunk=False).get_opcodes():
        for j in range(j1, j2):
            if op == "equal":
                at[j] = i1 + (j - j1)
            elif op == "replace":
                at[j] = i1 + (j - j1) * (i2 - i1) // (j2 - j1)
            elif op == "insert":
                at[j] = max(i1 - 1, 0)
    new = []
    for k in range(len(sw) - 1):
        a, b = at[k], at[k + 1]
        new.append(strongest(bseps[a:b]) if b > a else " ")
    return join(blead, sw, new, btrail)


# ------------------------------------------------------------------ prep

def prep(args):
    (blines, bblocks), (slines, sblocks) = load("base"), load("suggester")
    wanted = parse_page_selection(args.pages) if args.pages else None
    pages = sorted(p for p in set(bblocks) & set(sblocks) if wanted is None or p in wanted)
    todo, kept = [], []
    for page in pages:
        btext = page_text(blines, bblocks, page)
        d = OUT / "pages" / f"{page:04d}"
        if (d / "done.json").exists():
            if (d / "before" / "base.txt").read_text(encoding="utf-8") != btext:
                die(f"page {page} is done, but input/base.txt has changed since; "
                    f"delete {d} to do it again")
            kept.append(page)
            continue
        (d / "before").mkdir(parents=True, exist_ok=True)
        (d / "base.txt").write_text(btext, encoding="utf-8")
        (d / "before" / "base.txt").write_text(btext, encoding="utf-8")
        todo.append(page)

    prompt = (AGENTS / "line-setter.md").read_text(encoding="utf-8")
    notes = INPUT / "notes_lines.md"
    if notes.exists():
        prompt = prompt.rstrip() + "\n\n## Editor's notes\n\n" + notes.read_text(encoding="utf-8").strip() + "\n"
    prompt += (f"\n## Paths\n\n- The page image is {Path(PAGES).resolve()}/NNNN/page.jpg, "
               "NNNN being your page.\n\nYour page directory:")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "align-lines.js").write_text(
        WORKFLOW % (json.dumps(prompt, ensure_ascii=False), json.dumps(args.model)),
        encoding="utf-8")

    print(f"pages: {len(pages)}; to do: {len(todo)}" + (f"; done already, kept: {len(kept)}" if kept else ""))
    print(f"workflow: {(OUT / 'align-lines.js').resolve()}")
    print("pages:", json.dumps([str((OUT / 'pages' / f'{p:04d}').resolve()) for p in todo]))


# ------------------------------------------------------------------ apply

def edges(text):
    lead, _, _, trail = parts(text)
    return lead, trail


def apply(_args):
    pdirs = sorted((OUT / "pages").glob("[0-9][0-9][0-9][0-9]")) if (OUT / "pages").is_dir() else []
    if not pdirs:
        die("nothing to apply; run lines.py prep first")
    (blines, bblocks), (slines, sblocks) = load("base"), load("suggester")
    done, pending, refused = [], [], []
    new_pages = {}
    for d in pdirs:
        page = int(d.name)
        if not (d / "done.json").exists():
            pending.append(page)
            continue
        before = (d / "before" / "base.txt").read_text(encoding="utf-8")
        after = (d / "base.txt").read_text(encoding="utf-8")
        # Writing a file usually ends it with a newline; the page had none.
        if after.endswith("\n") and not before.endswith("\n"):
            after = after[:-1]
        if page_text(blines, bblocks, page) != before:
            die(f"page {page} of input/base.txt has changed since prep; run lines.py prep again")
        if before.split() != after.split():
            refused.append((page, "a word changed, not only whitespace"))
            continue
        if edges(before) != edges(after):
            refused.append((page, "the page's start or end changed (blank lines before or after "
                                  "its text), which says whether it runs on across the page break"))
            continue
        stext = page_text(slines, sblocks, page)
        new_pages[page] = (after, project(after, stext))
        done.append(page)

    out = {}
    for role, (lines, blocks) in (("base", (blines, bblocks)), ("suggester", (slines, sblocks))):
        lines = list(lines)
        for page in sorted(new_pages, reverse=True):
            start, end = blocks[page]
            lines[start:end] = new_pages[page][ROLES.index(role)].split("\n")
        out[role] = "\n".join(lines)
        (OUT / f"{role}.txt").write_text(out[role], encoding="utf-8")

    # How well the two now line up: pages whose lines pair off one to one.
    _, nb = __import__("gaps").page_blocks(out["base"], _marker(out["base"]))
    nlines_b, nlines_s = out["base"].split("\n"), out["suggester"].split("\n")
    _, ns = __import__("gaps").page_blocks(out["suggester"], _marker(out["suggester"]))
    paired = sum(1 for p in done if nb[p][1] - nb[p][0] == ns[p][1] - ns[p][0])
    changed_b = sum(1 for p in done if new_pages[p][0] != page_text(blines, bblocks, p))
    changed_s = sum(1 for p in done if new_pages[p][1] != page_text(slines, sblocks, p))

    report = ["align-lines report", "",
              f"pages set out: {len(done)}" + (f"; not yet: {len(pending)}" if pending else ""),
              f"base pages whose layout changed: {changed_b}",
              f"suggester pages whose layout changed: {changed_s}",
              f"pages where the two now have the same number of lines: {paired} of {len(done)}", ""]
    if refused:
        report.append("Refused, layout left as it was:")
        report += [f"  page {p}: {why}" for p, why in refused]
        report.append("")
    notes = []
    for p in done:
        dj = json.loads((OUT / "pages" / f"{p:04d}" / "done.json").read_text(encoding="utf-8"))
        if dj.get("notes"):
            notes.append(f"  page {p}: {dj['notes']}")
    if notes:
        report.append("Agents' notes:")
        report += notes
        report.append("")
    report.append(f"wrote {OUT / 'base.txt'} and {OUT / 'suggester.txt'}; input/ is unchanged")
    text = "\n".join(report) + "\n"
    (OUT / "report.txt").write_text(text, encoding="utf-8")
    print(text)


def _marker(text):
    from common import resolve_marker
    return resolve_marker("auto", text, "text", die)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep")
    p.add_argument("--pages", help="only these pages, e.g. 12-21 or 3,5,9")
    p.add_argument("--model", help="the agents' model, e.g. sonnet or haiku (default: the session's)")
    sub.add_parser("apply")
    args = ap.parse_args()
    prep(args) if args.cmd == "prep" else apply(args)


if __name__ == "__main__":
    main()
