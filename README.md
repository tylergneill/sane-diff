# Claude Diff Adjudicator

A workflow for using Claude to systematically adjudicate disagreements between two structured Sanskrit e-text files using its vision and natural language capabilities.

## Setup

Put in `input/` two page- and line-aligned versions of a text, e.g.:

| file | |
|---|---|
| `etext.txt` | a pre-existing e-text |
| `ocr.txt` | OCR output of the same edition, with same page/line alignment |
| `source.pdf` | the edition scan |
| `notes.md` | optional; passed to every sub-agent |

Page markers are lines reading `<p.12>`. For a different format pass
`--marker` a regex whose first capture group is the page number.

Brew-install `poppler`. Nothing else is required; `pip install tqdm` gets you
progress bars instead of a plain counter.

## Run

```sh
python3 scripts/prep.py                 # or --pages 1-9 to limit
python3 scripts/pending.py              # pages awaiting adjudication
```

For stage two, open Claude Code in this repo and tell it:

> Adjudicate the pending pages using subagents, following `agents/dispatcher.md`.

It dispatches one sub-agent per page, each writing a `verdicts.json` into its
page directory, and repeats until nothing is pending. Then it runs the last two
steps for you:

```sh
python3 scripts/apply.py
python3 scripts/report.py
```

Both write into `output/`.

An interrupted run resumes where it stopped — `pending.py` lists whatever
still lacks a `verdicts.json`.

## Starting over

`tmp/` and `output/` are both regenerable from `input/`. Nothing else is.

```sh
rm -rf tmp output
python3 scripts/prep.py
```

Do this whenever `prep.py` changes how items are cut, because verdicts are
keyed to item ids that renumber — a stale verdict then applies to the wrong
item silently, with no error.

`prep.py` alone is not enough: it writes `diffs.json` into existing page
directories and leaves any `verdicts.json` beside it untouched, so old verdicts
rejoin the run. Delete `tmp/` outright.

To redo one page rather than all of them, delete just its
`tmp/pages/NNNN/verdicts.json` and re-run from `pending.py`.

## Review

```sh
meld input/etext.txt output/corrected.txt
```

Use `output/corrected.marked.txt` instead to see each change with its verdict:

| mark | |
|---|---|
| *(none)* | e-text kept, high confidence |
| `{+}` | OCR adopted |
| `{!}` | agent override — neither candidate |
| `{~}` `{?}` | medium / low confidence, combined (`{+~}`, `{!?}`) |

Start with `output/report.flagged.tsv` — agent overrides and low-confidence
readings, the rows needing eyes. `output/report.tsv` has every item with its
note; `output/report.json` the same plus totals.

Keep the PDF open in its own viewer; the reports cite page and line. The line
number counts lines in the e-text, blank separator lines included, so it runs
ahead of the printed line count on the scan — use it to get near the right spot,
then match on the text itself.

To reject a verdict, edit that page's `verdicts.json` and re-run `apply.py`.

## Caveats

Every verdict is applied regardless of confidence; confidence controls the mark
only.
