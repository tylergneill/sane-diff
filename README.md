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

To redo a page, delete its `work/pages/NNNN/verdicts.json` and re-run from
`pending.py`. An interrupted run resumes where it stopped.

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

Verdicts are keyed to item ids that renumber whenever `prep.py` changes how
items are cut. Stale verdicts then apply to the wrong item silently. After any
such change, delete every `verdicts.json` and re-adjudicate.

Every verdict is applied regardless of confidence; confidence controls the mark
only.
