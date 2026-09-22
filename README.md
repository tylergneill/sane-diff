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

Then check the result with `scripts/review.py`, below.

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

To walk the questionable verdicts against the scan, use `review.py`. It groups
them by page, prints the e-text, the OCR and the adjudicated reading with the
agent's note, and opens each page image as it goes. On a tty it clears and
pauses between pages; `--no-clear` prints them in one go instead, and `--pages`
limits the walk (`--pages 12-24,96`).

The scan opens without raising the viewer, so the keyboard stays with the
prompt. Put the viewer window where you can see it before you start — it will
not come to the front on its own.

Three modes, narrowest first:

| flag | shows |
|---|---|
| `--overrides` | `other` verdicts — the only ones that can put a reading into the output that neither source contains |
| `--low` | every low-confidence verdict, whatever was chosen: what an agent said it could not settle |
| `--all` | every low- and medium-confidence verdict *(default)* |

```sh
python3 scripts/review.py --overrides
```

High-confidence `etext` and `ocr` verdicts are never shown — they are the bulk
of any run, and reviewing them is reviewing the whole text.

`--summary` does something else: rather than walking items it cross-tabulates
every verdict, high ones included, and exits.

```
$ python3 scripts/review.py --summary
┌────────┬──────┬────────┬─────┬───────┐
│ source │ high │ medium │ low │ total │
├────────┼──────┼────────┼─────┼───────┤
│ etext  │   61 │      6 │   3 │    70 │
├────────┼──────┼────────┼─────┼───────┤
│ ocr    │   25 │      2 │   1 │    28 │
├────────┼──────┼────────┼─────┼───────┤
│ other  │    0 │      2 │   0 │     2 │
├────────┼──────┼────────┼─────┼───────┤
│ total  │   86 │     10 │   4 │   100 │
└────────┴──────┴────────┴─────┴───────┘
```

It respects `--pages`, so `--summary --pages 17-18` scores just those pages.

The reports behind it: `output/report.flagged.tsv` is the overrides and
low-confidence readings as a table, `output/report.tsv` every item with its
note, `output/report.json` the same plus totals.

Keep the PDF open in its own viewer; the reports cite page and line. The line
number counts lines in the e-text, blank separator lines included, so it runs
ahead of the printed line count on the scan — use it to get near the right spot,
then match on the text itself.

### Rejecting a verdict

The prompt between pages takes a choice as well as `enter`:

```
[enter] next page, [e] e-text, [o] ocr, [ctrl-c] stop
```

`e` or `o` rewrites that verdict to the named source and writes
`verdicts.json` straight away, so `ctrl-c` keeps whatever you have already
decided. Where a page holds several items they are numbered, and the choice
takes the number with it — `e3` picks the e-text for item 3.

A verdict decided this way is recorded as `decided_by: human` at `high`
confidence. It stops being flagged and drops out of later walks: you settled
it, so there is nothing left to ask. `report.py` and `--summary` both report
how many items were decided this way.

Re-run `apply.py` afterwards to fold the changes into `output/`.

You can also edit a page's `verdicts.json` by hand, which is the only route
for a reading neither source got right — set `choice` to `other` and write the
`reading` yourself. Editing `corrected.txt` directly works only if you are
done for good: `apply.py` regenerates it from the verdicts and will overwrite
anything you put there, and the reports keep describing the unedited run.

## Caveats

Every verdict is applied regardless of confidence; confidence controls the mark
only.
