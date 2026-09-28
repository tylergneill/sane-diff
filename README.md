# sane-diff

Reconciles two page-aligned transcriptions of the same text —
Sanskrit by default, or any other language —
one page at a time, with a language model doing the reading.

The two inputs have fixed roles. The **base** is the text whose readings are
kept by default: usually the one readers already trust, such as a human-made
e-text. The **suggester** is a second transcription that proposes changes to
it. Either one can be OCR, a hand transcription, or another model's output.
What each one actually is goes in `input/notes.md`, and every model is shown
it.

Both texts must carry the same page markers, `<p.12>` or `=== 12 ===` (either
works, detected per file), and the same lines within each page.

## Run

```sh
make init BASE=path/to/base.txt SUGGESTER=path/to/suggester.txt IMAGE=path/to/image.pdf
make prep-pending
make resolve
make review
```

Every target takes `PAGES=3-5` to work on just those pages. Every `resolve*`
target takes `LANGUAGE=Latin` (or any language) for texts not in Sanskrit;
the prompts name it wherever they speak of the text. The default is the
`LANGUAGE` line in `scripts/common.py`.

| target | what it does |
|---|---|
| `init` | clears `input/` (except `notes.md`), `tmp/` and `output/`, asking first if the last two hold anything, then copies the three files in as `input/base.txt`, `suggester.txt` and `image.pdf`. `IMAGE` is optional; without it only the no-vision runs work. |
| `prep-pending` | finds every disagreement between the two texts, page by page, and lists the pages still to resolve |
| `resolve` | Claude sub-agents settle each disagreement, looking at the page image |
| `resolve-claude-no-vision` | the same, from the two texts and the notes only |
| `resolve-gemini-no-vision` | the Gemini API rewrites each page whole from the two texts, as the old notebook did |
| `review` | walks the questionable verdicts of a Claude run, opening each page image |
| `review-summary` | counts a Claude run's verdicts by source and confidence |

Each `resolve` target writes its report when it finishes, into its own folder,
so the runs can be compared:

| run | output |
|---|---|
| `resolve` | `output/claude-vision/` |
| `resolve-claude-no-vision` | `output/claude-no-vision/` |
| `resolve-gemini-no-vision` | `output/gemini-no-vision/gemini-2.5-flash.txt` |

It then deletes the page images, which are the bulk of `tmp/`. `review` and
`review-summary` extract them again. For the no-vision Claude run, pass
`VISION=no` to either.

These are three points on three axes, which is why they are named as they
are:

| axis | values |
|---|---|
| backend | Claude sub-agents (on your subscription) · Gemini API |
| unit | `item`: the model decides each disagreement, and a script applies its answers to the base · `page`: the model rewrites the whole page |
| vision | the model sees the page image, or not |

The Claude runs start Claude Code as `claude "<prompt>"`; it fans out one
sub-agent per page, following `agents/dispatcher.md`, and `make` writes the
report when you leave the session. An interrupted run resumes where it
stopped: finished pages drop off the pending list.

Image extraction needs `poppler` (brew-install it). `pip install tqdm` gets
you progress bars instead of a plain counter.

## Gemini

`resolve-gemini-no-vision` needs `litellm`. Point `PYTHON` at an environment
that has it, e.g. `make resolve-gemini-no-vision PYTHON=~/venvs/ai-apis-311/bin/python`.
The API key is read from `GEMINI_API_KEY`, or from a `.env` file at the repo
root holding a `GEMINI_API_KEY=...` line. `.env` is gitignored.

Every billed response is logged in `tmp/usage/gemini-2.5-flash.jsonl`,
including failed ones, since those are billed too. Each entry holds the usage
as reported, the price applied and the resulting cost. The report prints the
running total:

```
label             pages  calls  failed  prompt tok  output tok  thought tok  cost USD
gemini-2.5-flash      2      2       0       1,733         425        5,639    0.0157
```

Cost is prompt tokens at the input rate plus visible output and thinking at
the output rate, as Google bills them. The rates live in `PRICES` in
`scripts/gemini.py`, dated. Keep them current. A model with no price there is
refused rather than recorded at $0. The ledger lives in `tmp/`, so `make init`
deletes it along with everything else there, after asking.

The prompt is `agents/merger.md` plus `input/notes.md`. To see exactly what
is sent for page 12: `python3 scripts/merge.py prompt 12`.
`examples/notes.merge-hyp.md` holds the project-specific half of the old
notebook's prompt; copy it to `input/notes.md` to reproduce that prompt.

## Review

```sh
meld input/base.txt output/claude-vision/corrected.txt
```

Use `output/claude-vision/corrected.marked.txt` instead to see each change with
its verdict:

| mark | |
|---|---|
| *(none)* | base kept, high confidence |
| `{+}` | suggester adopted |
| `{!}` | agent override — neither candidate |
| `{~}` `{?}` | medium / low confidence, combined (`{+~}`, `{!?}`) |

`make review` groups the low- and medium-confidence verdicts by page, prints
the base, the suggester and the adjudicated reading with the agent's note, and
opens each page image as it goes. The image opens without raising the viewer,
so the keyboard stays with the prompt; put the viewer window where you can see
it before you start.

High-confidence verdicts are never shown — they are the bulk of any run, and
reviewing them is reviewing the whole text. For narrower walks, run
`scripts/review.py` directly: `--overrides` shows only `other` verdicts, the
only ones that can put a reading into the output that neither source
contains, and `--low` only the low-confidence ones.

The prompt between pages takes a choice as well as `enter`:

```
[enter] next page, [b] base, [s] suggester, [ctrl-c] stop
```

`b` or `s` rewrites that verdict to the named source straight away, so `ctrl-c`
keeps whatever you have already decided. Where a page holds several items they
are numbered, and the choice takes the number with it — `b3` picks the base
for item 3. A verdict decided this way is recorded as `decided_by: human` at
`high` confidence and drops out of later walks. Run `make report` afterwards
to fold the changes into `output/`.

`scripts/review.py --set p0002-002=suggester` does the same for one named item
without walking, at any confidence. You can also edit a page's verdict file by
hand, which is the only route for a reading neither source got right — set
`choice` to `other` and write the `reading` yourself. Editing `corrected.txt`
directly works only if you are done for good: the report regenerates it from
the verdicts.

The reports behind it: `report.flagged.tsv` holds the overrides and
low-confidence readings, `report.tsv` every item with its note, and
`report.json` the same plus totals. The line number they cite counts lines in
the base, blank lines included, so it runs ahead of the printed line count on
the page — use it to get near the right spot, then match on the text.

## How the item unit decides

The aim is to cut down manual work, not to remove it. Most differences between
the base and the suggester are easy to settle: a mark one of them dropped, a
typo. Those are settled automatically. The hard cases — broken type, ambiguous
conjuncts, readings that depend on knowing the text — are left for you, marked
low confidence.

The base is the default. The agent adopts the suggester's reading when the
evidence points to it, at whatever confidence it actually has. It proposes a
reading of its own (`other`, never above medium confidence) only when neither
source can be right. Leaving the hard cases for you is deliberate: a wrong
correction looks like every other change once it is in the output, so it is
hard to find and hard to undo, while an open item costs a minute of review.

Every verdict is applied regardless of confidence; confidence controls the mark
only. The design reasoning is in `docs/adjudicate-spec.md`.

## Starting over

`make init` starts a new text. To redo one run on the same text, delete its
verdict files, `tmp/pages/*/verdicts.claude-vision.json` (or
`claude-no-vision`), or for Gemini the files in `tmp/pages/*/merged/`, and
resolve again. To redo one page, delete just that page's file.

After changing how `prep.py` cuts items, start from a clean `tmp/`: verdicts
are keyed to item ids that renumber, and a stale verdict applies to the wrong
item silently.
