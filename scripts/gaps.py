#!/usr/bin/env python3
"""fix-gaps: find the big gaps between the two texts, and put the settled
pages back together.

  gaps.py find [--pages 3-5]    find the gaps; set up each page for its
                                agents; print the pages still to do
  gaps.py apply                 check what the agents did and write
                                tmp/gaps/base.txt, suggester.txt, report.txt

make fix-gaps runs both inside a Claude session (agents/fix-gaps.md), with a
workflow between them that takes each page through two agents: scribe
transcribes the lines around each gap from the page image, on its own, and
a settler (agents/gap-settler.md) decides each gap from the two texts,
scribe's reading and the image.

A gap is either
- a run of at least LINE words that one text has and the other lacks
  (or has much shorter in its place), or
- a line repeated within NEAR lines in one text but not the other, the
  usual OCR failure.
Everything smaller is left to resolve.

find writes, per page with gaps, tmp/gaps/pages/NNNN/:
  base.txt, suggester.txt   the page in each text, for the settler to edit
  before/                   the same, untouched, for apply to compare with
  gaps.json, gaps.md        the gaps, for apply and for the settler
  scribe_task.md            scribe's prompt: transcribe the lines around
                            each gap, found by the words before and after it
and a scribe project in tmp/gaps/scribe/ (its images and transcriptions in
tmp/gaps/scribe/work/). A page that already has decisions.json is kept as
it is, so an interrupted run picks up where it stopped.

apply checks each settled page: every change must fall within a gap (give
or take MARGIN words), or the page's edits are set aside and its gaps
reported as open. It writes both texts whole into tmp/gaps/, the report
beside them, and changes nothing in input/.
"""

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from common import PAGES, parse_page_selection, resolve_marker
from prep import read_offset

INPUT = Path("input")
OUT = Path("tmp/gaps")
ROLES = ("base", "suggester")
AGENTS = Path(__file__).resolve().parent.parent / "agents"

# A one-sided run this many words long or longer is a gap: about a line.
LINE = 8
# A line repeated within this many lines (of at least DUP_WORDS words, and
# at least DUP_RATIO alike) is a repeat.
NEAR = 4
DUP_WORDS = 3
DUP_RATIO = 0.9
# Gaps this close together are one; a change this close to a gap is in it.
MARGIN = 3
# A passage counts as also on another page when that page shares this
# share of its runs of GRAM words.
GRAM = 4
SHARED = 0.5
# A long passage is checked in pieces this many words long.
CHUNK = 16
# Gaps covering more than this share of a page, in either text, get scribe
# reading the whole page rather than excerpts.
WHOLE = 0.5
# Words of context shown on either side of a gap.
CONTEXT = 6

WORKFLOW = """export const meta = {
  name: 'fix-gaps',
  description: 'Per page: scribe reads the lines around each gap from the image, then the gaps are settled',
  phases: [{ title: 'Transcribe' }, { title: 'Settle' }],
}
const SETTLE = %s
const label = dir => dir.split('/').pop()
await pipeline(args,
  dir => agent(`If ${dir}/scribe.done exists, reply "skip" and stop. Otherwise read and carry out the task in ${dir}/scribe_task.md, then create the empty file ${dir}/scribe.done.`,
    { label: 'read ' + label(dir), phase: 'Transcribe', agentType: 'general-purpose' }),
  (_, dir) => agent(SETTLE + '\\n' + dir,
    { label: 'settle ' + label(dir), phase: 'Settle', agentType: 'general-purpose' }),
)
"""


def die(msg):
    print(f"gaps.py: {msg}", file=sys.stderr)
    sys.exit(1)


# ------------------------------------------------------------------ texts

def page_blocks(text, regex):
    """(lines, {page: (start, end)}): each page's lines are lines[start:end],
    the lines after its marker up to the next one."""
    lines = text.split("\n")
    pat = re.compile(regex)
    blocks, current, start = {}, None, 0
    for i, line in enumerate(lines):
        m = pat.match(line)
        if m:
            if current is not None:
                blocks[current] = (start, i)
            current, start = int(m.group(1)), i + 1
    if current is not None:
        blocks[current] = (start, len(lines))
    return lines, blocks


def load(role):
    path = INPUT / f"{role}.txt"
    if not path.is_file():
        die(f"no {path}")
    text = path.read_text(encoding="utf-8")
    return page_blocks(text, resolve_marker("auto", text, str(path), die))


def words(page_text):
    """[(word, line number from 1)] for a page."""
    return [(w, n) for n, line in enumerate(page_text.split("\n"), 1) for w in line.split()]


def norm(w):
    return re.sub(r"[^\w]", "", w.lower())


# ------------------------------------------------------------------ gaps

def repeats(page_text):
    """Word ranges of lines that repeat one of the NEAR lines before them:
    [((start, end) of the repeat, (start, end) of the earlier copy)]."""
    spans, at = [], 0
    for line in page_text.split("\n"):
        n = len(line.split())
        spans.append((line.strip(), at, at + n))
        at += n
    found = []
    real = [s for s in spans if len(s[0].split()) >= DUP_WORDS]
    for k, (line, a, b) in enumerate(real):
        for prev, pa, pb in real[max(0, k - NEAR):k]:
            if difflib.SequenceMatcher(None, line, prev, autojunk=False).ratio() > DUP_RATIO:
                found.append(((a, b), (pa, pb)))
                break
    return found


def find_gaps(btext, stext):
    """The gaps on a page: [{"kind", "base": [i1, i2], "suggester": [j1, j2]}],
    word ranges into each side's words()."""
    bw, sw = [w for w, _ in words(btext)], [w for w, _ in words(stext)]
    ops = difflib.SequenceMatcher(None, [norm(w) for w in bw], [norm(w) for w in sw],
                                  autojunk=False).get_opcodes()
    gaps = []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            continue
        if (i2 - i1) - (j2 - j1) >= LINE:
            gaps.append({"kind": "only in the base", "base": [i1, i2], "suggester": [j1, j2]})
        elif (j2 - j1) - (i2 - i1) >= LINE:
            gaps.append({"kind": "only in the suggester", "base": [i1, i2], "suggester": [j1, j2]})

    def overlapping(side, a, b):
        k = 1 if side == "base" else 3
        return [o for o in ops if o[0] != "equal" and o[k] <= b and o[k + 1] >= a]

    for side, text in (("base", btext), ("suggester", stext)):
        for (a, b), (pa, pb) in repeats(text):
            hit = overlapping(side, a, b) or overlapping(side, pa, pb)
            if not hit:
                continue  # the other text repeats it too
            i1, i2 = min(o[1] for o in hit), max(o[2] for o in hit)
            j1, j2 = min(o[3] for o in hit), max(o[4] for o in hit)
            gaps.append({"kind": f"a line repeated in the {side}",
                         "base": [i1, i2], "suggester": [j1, j2]})
    return merge(gaps)


def merge(gaps):
    gaps = sorted(gaps, key=lambda g: (g["base"][0], g["suggester"][0]))
    out = []
    for g in gaps:
        if out and all(g[r][0] <= out[-1][r][1] + MARGIN for r in ROLES):
            last = out[-1]
            for r in ROLES:
                last[r] = [min(last[r][0], g[r][0]), max(last[r][1], g[r][1])]
            if g["kind"] not in last["kind"]:
                last["kind"] += "; " + g["kind"]
        else:
            out.append({**g, "base": list(g["base"]), "suggester": list(g["suggester"])})
    return out


def show(page_text, span):
    """A gap's text on one side, with a little context and its lines."""
    ws = words(page_text)
    a, b = span
    before = " ".join(w for w, _ in ws[max(0, a - CONTEXT):a])
    inside = " ".join(w for w, _ in ws[a:b])
    after = " ".join(w for w, _ in ws[b:b + CONTEXT])
    if a == b:
        line = ws[a][1] if a < len(ws) else (ws[-1][1] if ws else 1)
        return f"nothing, at line {line}: …{before} ⟦⟧ {after}…"
    lines = f"line {ws[a][1]}" if ws[a][1] == ws[b - 1][1] else f"lines {ws[a][1]}-{ws[b - 1][1]}"
    return f"{b - a} words, {lines}: …{before} ⟦{inside}⟧ {after}…"


def grams(ws):
    """The passage's runs of GRAM words, normalized, blanks dropped."""
    ws = [x for x in (norm(w) for w in ws) if x]
    return {tuple(ws[i:i + GRAM]) for i in range(len(ws) - GRAM + 1)}


def elsewhere(page, words_, span, pages_grams):
    """Where else the same text has the passage, chunk by chunk:
    [(first word, last word, place)], words counted from 1 within the
    passage, place a page number or "this page" (outside the passage). A
    chunk is there when the place shares at least SHARED of its GRAM-word
    runs: fuzzy, since a passage typed twice rarely comes out the same
    twice."""
    a, b = span
    if b - a < LINE:
        return []
    places = {p: g for p, g in pages_grams.items() if p != page}
    places["this page"] = grams(words_[:a]) | grams(words_[b:])
    found = []
    for c in range(a, b, CHUNK):
        mine = grams(words_[c:min(b, c + CHUNK)])
        if len(mine) < GRAM:
            continue
        hit = next((p for p, g in places.items() if len(mine & g) >= SHARED * len(mine)), None)
        if hit is None:
            continue
        lo, hi = c - a + 1, min(b, c + CHUNK) - a
        if found and found[-1][2] == hit and found[-1][1] == lo - 1:
            found[-1] = (found[-1][0], hi, hit)
        else:
            found.append((lo, hi, hit))
    return found


def gaps_md(page, gaps, btext, stext):
    out = [f"# Gaps on page {page}", ""]
    for k, g in enumerate(gaps, 1):
        out += [f"## Gap {k}: {g['kind']}", "",
                f"- base: {show(btext, g['base'])}",
                f"- suggester: {show(stext, g['suggester'])}"]
        for role, found in g.get("elsewhere", {}).items():
            n = g[role][1] - g[role][0]
            for lo, hi, place in found:
                part = "all of the" if (lo, hi) == (1, n) else f"words {lo}-{hi} of the"
                where = ("elsewhere on this page" if place == "this page"
                         else f"on {role} page {place}")
                out.append(f"- {part} {role}'s passage also appear(s) {where}")
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------ find

def scribe(*args):
    """Run a scribe tool by module, with this Python, so it works whatever
    PATH the session has."""
    cmd = [sys.executable, "-m", f"sanskrit_scribe.{args[0]}", *args[1:]]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        die(f"{' '.join(cmd)} failed:\n{result.stderr.strip()}")
    return result.stdout


def scribe_notes():
    """The "## Scribe" section of input/notes_gaps.md, if it has one: notes
    for the transcriber about the edition. The rest of the notes is about
    the two texts, which scribe must not see."""
    path = INPUT / "notes_gaps.md"
    if not path.exists():
        return ""
    m = re.search(r"^## Scribe\s*\n(.*?)(?=^## |\Z)", path.read_text(encoding="utf-8"),
                  re.M | re.S)
    return m.group(1).strip() if m else ""


def find(args):
    try:
        import sanskrit_scribe  # noqa: F401
    except ImportError:
        die("claude-sanskrit-scribe is not installed: pip install -r requirements.txt")
    pdf = (INPUT / "image.pdf").resolve()
    if not pdf.exists():
        die(f"no {pdf}: fix-gaps needs the page images")

    (blines, bblocks), (slines, sblocks) = load("base"), load("suggester")
    wanted = parse_page_selection(args.pages) if args.pages else None
    pages = sorted(p for p in set(bblocks) & set(sblocks) if wanted is None or p in wanted)

    def page_grams(lines, blocks):
        return {p: grams("\n".join(lines[slice(*blocks[p])]).split()) for p in blocks}
    norm_pages = {"base": page_grams(blines, bblocks), "suggester": page_grams(slines, sblocks)}

    todo, kept, total, todo_gaps = [], [], 0, {}
    for page in pages:
        btext = "\n".join(blines[slice(*bblocks[page])])
        stext = "\n".join(slines[slice(*sblocks[page])])
        d = OUT / "pages" / f"{page:04d}"
        if (d / "decisions.json").exists():
            if ((d / "before" / "base.txt").read_text(encoding="utf-8") != btext
                    or (d / "before" / "suggester.txt").read_text(encoding="utf-8") != stext):
                die(f"page {page} is settled, but the texts in input/ have changed since; "
                    f"delete {d} to do it again")
            kept.append(page)
            continue
        gaps = find_gaps(btext, stext)
        for g in gaps:
            for role, text in (("base", btext), ("suggester", stext)):
                found = elsewhere(page, [w for w, _ in words(text)], g[role], norm_pages[role])
                if found:
                    g.setdefault("elsewhere", {})[role] = found
        if not gaps:
            shutil.rmtree(d, ignore_errors=True)
            continue
        total += len(gaps)
        # A page scribed before excerpts (one whole-page file, and a check
        # pass) has no reading where the settler now looks: scribe it again.
        sout = OUT / "scribe" / "work" / "out"
        if not (sout / f"p{page:04d}").is_dir():
            (d / "scribe.done").unlink(missing_ok=True)
        (d / "scribe_verify.md").unlink(missing_ok=True)
        (d / "before").mkdir(parents=True, exist_ok=True)
        for role, text in (("base", btext), ("suggester", stext)):
            (d / f"{role}.txt").write_text(text, encoding="utf-8")
            (d / "before" / f"{role}.txt").write_text(text, encoding="utf-8")
        (d / "gaps.json").write_text(json.dumps({"page": page, "gaps": gaps}, ensure_ascii=False,
                                                indent=2) + "\n", encoding="utf-8")
        (d / "gaps.md").write_text(gaps_md(page, gaps, btext, stext), encoding="utf-8")
        todo.append(page)
        todo_gaps[page] = (gaps, btext, stext)

    if todo:
        setup_scribe(todo_gaps, pdf, args.profile)
    write_workflow()

    print(f"pages compared: {len(pages)}")
    print(f"pages with gaps to settle: {len(todo)} ({total} gaps)")
    if kept:
        print(f"pages already settled, kept: {len(kept)}")
    print(f"workflow: {(OUT / 'fix-gaps.js').resolve()}")
    print("pages:", json.dumps([str((OUT / 'pages' / f'{p:04d}').resolve()) for p in todo]))


def lettered(w):
    return any(c.isalpha() for c in w)


def anchors(text, span):
    """The words just before and just after a gap on one side, for finding
    it on the image: CONTEXT real words each way, with the marks between
    them; ("", ...) when no real word comes before, as at the start of the
    page, (..., "") when none comes after. A lone `|` finds nothing. Never
    the gap's own words, so scribe's reading of them stays its own."""
    ws = [w for w, _ in words(text)]
    a, b = span
    i, n = a, 0
    while i > 0 and n < CONTEXT:
        i -= 1
        n += lettered(ws[i])
    j, m = b, 0
    while j < len(ws) and m < CONTEXT:
        m += lettered(ws[j])
        j += 1
    return (" ".join(ws[i:a]) if n else "", " ".join(ws[b:j]) if m else "")


def covered(text, gaps, role):
    """The share of a page's words, on one side, that its gaps cover."""
    total = len(words(text))
    return sum(g[role][1] - g[role][0] for g in gaps) / total if total else 0


def setup_scribe(pages, pdf, profile):
    """pages: {page: (gaps, base text, suggester text)}. Renders scribe's images of the
    pages, and writes each page's scribe_task.md: transcribe the lines
    around each gap, not the whole page."""
    from sanskrit_scribe.common import REPO as SCRIBE
    sdir = (OUT / "scribe").resolve()
    work = sdir / "work"
    project = sdir / "project"
    project.mkdir(parents=True, exist_ok=True)
    offset = read_offset(Path(PAGES))
    notes = scribe_notes()
    source = "the printed edition scanned in input/image.pdf"
    (project / "PROJECT.md").write_text(
        "# Project: a second reading of parts of pages\n\n"
        "- Only the excerpts asked for are transcribed, as an independent\n"
        "  reading to check two existing e-texts against.\n"
        + (f"\n{notes}\n" if notes else ""), encoding="utf-8")

    def project_json(names):
        (project / "project.json").write_text(json.dumps({
            "source": source, "profile": profile, "pdf": str(pdf), "mode": "print", "dpi": 300,
            "pages": {f"p{p:04d}": p + offset for p in names}}, indent=2) + "\n",
            encoding="utf-8")

    missing = [p for p in pages if not (work / "images" / f"p{p:04d}.png").exists()]
    if missing:
        project_json(missing)
        print(f"scribe: rendering {len(missing)} page image(s)", file=sys.stderr)
        scribe("prep", str(project), "--work", str(work))
    project_json(sorted(pages))

    template = (AGENTS / "scribe-excerpt.md").read_text(encoding="utf-8")
    for p, (gaps, btext, stext) in pages.items():
        name = f"p{p:04d}"
        out = work / "out" / name
        out.mkdir(parents=True, exist_ok=True)
        listed = []
        # Gaps over most of the page: one whole-page reading costs less than
        # many excerpts to find.
        if max(covered(btext, gaps, "base"), covered(stext, gaps, "suggester")) > WHOLE:
            listed.append(f"   - {name}_page.txt\n"
                          f"     Before: (start of page)\n"
                          f"     After: (end of page)")
        for k, g in enumerate([] if listed else gaps, 1):
            # From both texts, when they differ: either may be wrong here,
            # even holding another page's text.
            both = [anchors(btext, g["base"]), anchors(stext, g["suggester"])]
            befores = list(dict.fromkeys(b or "(start of page)" for b, _ in both))
            afters = list(dict.fromkeys(a or "(end of page)" for _, a in both))
            listed.append(f"   - {name}_g{k}.txt\n"
                          f"     Before: {'  OR  '.join(befores)}\n"
                          f"     After: {'  OR  '.join(afters)}")
        crops = ", ".join(sorted(c.name for c in (work / "images").glob(f"{name}_*.png")))
        values = {"source": source, "markup": str(SCRIBE / "core" / "MARKUP.md"),
                  "profile": str(SCRIBE / "profiles" / profile / "PROFILE.md"),
                  "project": str(project / "PROJECT.md"),
                  "image": str(work / "images" / f"{name}.png"), "crops": crops,
                  "out_dir": str(out), "excerpts": "\n".join(listed)}
        text = template
        for key, val in values.items():
            text = text.replace("{" + key + "}", val)
        (OUT / "pages" / f"{p:04d}" / "scribe_task.md").write_text(text, encoding="utf-8")


def write_workflow():
    prompt = (AGENTS / "gap-settler.md").read_text(encoding="utf-8")
    notes = INPUT / "notes_gaps.md"
    if notes.exists():
        prompt = prompt.rstrip() + "\n\n## Editor's notes\n\n" + notes.read_text(encoding="utf-8").strip() + "\n"
    prompt += ("\n## Paths\n\n"
               f"- The page image is {Path(PAGES).resolve()}/NNNN/page.jpg, NNNN being your page.\n"
               f"- Scribe's reading is in {(OUT / 'scribe' / 'work' / 'out').resolve()}/pNNNN/, "
               f"one file per gap; put it into your page directory as plain text with\n"
               f"  `{sys.executable} -m sanskrit_scribe.export <that folder> --to IAST --marker \"<{{n}}>\" -o <your page directory>/scribe.txt`\n"
               "\nYour page directory:")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fix-gaps.js").write_text(WORKFLOW % json.dumps(prompt, ensure_ascii=False),
                                     encoding="utf-8")


# ------------------------------------------------------------------ apply

def changes(old, new):
    """Word ranges of old that new changed: [(i1, i2)], an insertion as (i, i)."""
    ow, nw = [w for w, _ in words(old)], [w for w, _ in words(new)]
    return [(i1, i2) for op, i1, i2, _, _ in
            difflib.SequenceMatcher(None, ow, nw, autojunk=False).get_opcodes() if op != "equal"]


def disagreements(btext, stext):
    """Every stretch where the two texts differ, big or small, as gaps.
    Stretches split only by a few matching words (fewer than LINE, often
    just `|| 4 ||`) are one: the texts agree only where they match for a
    line or more."""
    bw, sw = [w for w, _ in words(btext)], [w for w, _ in words(stext)]
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, [norm(w) for w in bw], [norm(w) for w in sw], autojunk=False).get_opcodes():
        if op == "equal":
            continue
        if out and i1 - out[-1]["base"][1] < LINE:
            out[-1]["base"][1], out[-1]["suggester"][1] = i2, j2
        else:
            out.append({"base": [i1, i2], "suggester": [j1, j2]})
    return out


def within(span, gaps, role):
    a, b = span
    return any(g[role][0] - MARGIN <= a and b <= g[role][1] + MARGIN for g in gaps)


def apply(_args):
    pdirs = sorted((OUT / "pages").glob("[0-9][0-9][0-9][0-9]")) if (OUT / "pages").is_dir() else []
    if not pdirs:
        die("nothing to apply; run gaps.py find first")
    texts = {r: load(r) for r in ROLES}
    pages, unsettled, rejected = [], [], []
    for d in pdirs:
        page = int(d.name)
        gaps = json.loads((d / "gaps.json").read_text(encoding="utf-8"))["gaps"]
        if not (d / "decisions.json").exists():
            unsettled.append(page)
            continue
        decisions = json.loads((d / "decisions.json").read_text(encoding="utf-8"))
        before = {r: (d / "before" / f"{r}.txt").read_text(encoding="utf-8") for r in ROLES}
        after = {r: (d / f"{r}.txt").read_text(encoding="utf-8") for r in ROLES}
        # A change must fall within a gap, or at least where the two texts
        # already disagreed (as when one side held another page's text);
        # text both sides agreed on is never touched.
        differ = disagreements(before["base"], before["suggester"])
        changed = [(r, span) for r in ROLES for span in changes(before[r], after[r])]
        stray = [(r, span) for r, span in changed
                 if not within(span, gaps, r) and not within(span, differ, r)]
        beside = sum(1 for r, span in changed if not within(span, gaps, r)
                     and within(span, differ, r))
        left = find_gaps(after["base"], after["suggester"])
        pages.append({"page": page, "gaps": gaps, "decisions": decisions, "stray": stray,
                      "beside": beside,
                      "left": left, "after": after, "before": before})
        if stray:
            rejected.append(page)

    # Put the pages back, from the bottom up so earlier line numbers hold.
    out = {}
    for role in ROLES:
        lines, blocks = texts[role]
        lines = list(lines)
        for p in sorted(pages, key=lambda p: -p["page"]):
            if p["stray"]:
                continue
            start, end = blocks[p["page"]]
            if "\n".join(lines[start:end]) != p["before"][role]:
                die(f"page {p['page']} of input/{role}.txt has changed since find; "
                    f"run gaps.py find again")
            lines[start:end] = p["after"][role].split("\n")
        out[role] = "\n".join(lines)
        (OUT / f"{role}.txt").write_text(out[role], encoding="utf-8")

    report = summary(pages, unsettled, rejected)
    (OUT / "report.txt").write_text(report, encoding="utf-8")
    print(report)


def summary(pages, unsettled, rejected):
    counts, open_cases = {}, []
    for p in pages:
        for dec in p["decisions"]:
            if p["stray"]:
                open_cases.append((0, p["page"], dec.get("gap"), "edits set aside",
                                   f"the settler changed text outside the gaps: "
                                   + "; ".join(f"{r} words {a}-{b}" for r, (a, b) in p["stray"][:5])))
                continue
            if dec.get("outcome") == "open":
                open_cases.append((1, p["page"], dec.get("gap"), dec.get("what", ""),
                                   dec.get("why", "")))
            else:
                counts[dec.get("what", "settled")] = counts.get(dec.get("what", "settled"), 0) + 1
        open_ids = {d.get("gap") for d in p["decisions"] if d.get("outcome") == "open"}
        if p["left"] and not p["stray"] and len(p["left"]) > len(open_ids):
            open_cases.append((2, p["page"], None, "gaps still there",
                               f"{len(p['left'])} gap(s) remain after settling, "
                               f"{len(open_ids)} of them reported open"))
    settled = sum(counts.values())
    beside = [(p["page"], p["beside"]) for p in pages if p["beside"] and not p["stray"]]
    lines = ["fix-gaps report", "",
             f"pages with gaps: {len(pages) + len(unsettled)}; settled {len(pages)}"
             + (f", not yet: {len(unsettled)} ({', '.join(map(str, unsettled[:15]))})" if unsettled else ""),
             f"gaps settled: {settled}; left open: {len(open_cases)}", ""]
    if counts:
        lines.append("What was done:")
        lines += [f"  {n:4d}  {what}" for what, n in sorted(counts.items(), key=lambda x: -x[1])]
        lines.append("")
        lines.append("Every settled gap:")
        for p in pages:
            if p["stray"]:
                continue
            for dec in p["decisions"]:
                if dec.get("outcome") != "open":
                    lines.append(f"  page {p['page']}, gap {dec.get('gap')}: "
                                 f"{dec.get('what', 'settled')} — {dec.get('why', '')}")
        lines.append("")
    if beside:
        lines.append("Changed outside the gaps, where the texts already disagreed:")
        lines += [f"  page {pg}: {n} spot(s)" for pg, n in beside]
        lines.append("")
    if open_cases:
        lines.append("Open, hardest first:")
        for _, page, gap, what, why in sorted(open_cases):
            lines.append(f"  page {page}" + (f", gap {gap}" if gap else "") + f": {what}")
            if why:
                lines.append(f"      {why}")
        lines.append("")
    lines.append(f"wrote {OUT / 'base.txt'} and {OUT / 'suggester.txt'}; input/ is unchanged")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find")
    f.add_argument("--pages", help="only these pages, e.g. 12-21 or 3,5,9")
    f.add_argument("--profile", default="deva_print",
                   help="scribe's profile for the edition (default deva_print)")
    sub.add_parser("apply")
    args = ap.parse_args()
    find(args) if args.cmd == "find" else apply(args)


if __name__ == "__main__":
    main()
