# OCR adjudication pipeline

Adjudicates disagreements between a Sanskrit e-text and OCR of the same printed
edition, using the scanned page as ground truth. Design and rationale:
`ocr-adjudication-spec.md`.

## Setup

Put in `input/`:

| file | |
|---|---|
| `etext.txt` | the e-text, one line per printed line, page-aligned |
| `ocr.txt` | OCR of the same edition, same alignment |
| `source.pdf` | the scan |
| `notes.md` | optional; passed to every sub-agent |

Page markers are lines reading `<p.12>`. For a different format pass
`--marker` a regex whose first capture group is the page number.

Install `mupdf-tools` (or `poppler` plus ImageMagick). Nothing else to install.

## Run

```sh
python3 scripts/prep.py                 # or --pages 1-9 to limit
python3 scripts/pending.py              # pages awaiting adjudication
```

Then fan out to sub-agents — see `agents/dispatcher.md`. Each writes a
`verdicts.json` into its page directory.

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

Keep the PDF open in its own viewer; the reports cite page and line.

To reject a verdict, edit that page's `verdicts.json` and re-run `apply.py`.

## Caveats

Every verdict is applied regardless of confidence; confidence controls the mark
only.
