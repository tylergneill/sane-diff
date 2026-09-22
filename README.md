# OCR adjudication pipeline

Adjudicates disagreements between a pre-existing Sanskrit e-text and OCR output,
using the scanned page image of the printed edition as ground truth. The e-text
is already good; OCR is a second opinion, not a replacement. For each point where
the two disagree, a vision-capable agent decides what the printed page says.

See `ocr-adjudication-spec.md` for the design and its rationale.

## Inputs

Three required files in `input/`, plus one optional:

| file | what it is |
|---|---|
| `etext.txt` | the pre-existing e-text, one line per printed line, page-aligned |
| `ocr.txt` | OCR output from the same edition, same line and page alignment |
| `source.pdf` | the scanned printed edition |
| `notes.md` | **optional** — an expert reader's account of the two texts |

Line numbers and page boundaries are assumed accurate and consistent across all
three. The pipeline does not re-derive alignment; every location reference is a
page number plus a line number.

`notes.md` is always optional. When absent the sub-agent decides everything from
the page image on its own; when present its contents go into each sub-agent
prompt and the agent respects it. Use it for what an agent cannot derive from a
single page: what the editorial markup means, whether ellipsis length carries
information, how the apparatus is delimited, which OCR artifacts are known.
Where the note and the page disagree, the page wins and the item is flagged.

Both texts are split on page markers. The default marker is a line reading
`<p.12>`; use `--marker` to pass a different regex whose first capture group is
the page number.

## Running it

```sh
# Stage one — deterministic, no model.
python3 scripts/prep.py

# Just the trial pages:
python3 scripts/prep.py --pages 12-21

# Stage two — fan out to sub-agents. See agents/dispatcher.md.
python3 scripts/pending.py          # what still needs adjudicating

# Stage three — apply every verdict to the e-text.
python3 scripts/apply.py

# Stage four — the readout that explains it.
python3 scripts/report.py

# Stage five — the review interface.
python3 scripts/review.py
```

`prep.py` renders each page that has diffs to a 300 DPI grayscale `page.png` and
writes its `diffs.json`. Pages where the two texts agree completely get no
directory and are skipped — on a clean edition that is most of the book, and it
is the main reason the run stays cheap.

Rendering uses `mutool` when present, otherwise `pdftoppm` plus ImageMagick.
Install `mupdf-tools` or `poppler`. The scripts are otherwise stdlib-only.

## Output

`corrected.txt` is the deliverable: the e-text with every verdict applied, same
page markers and line structure, so `diff input/etext.txt corrected.txt` shows
only real changes.

Every verdict is applied regardless of confidence. A half-applied text is a third
artifact that has to be reconciled by hand, which is the work this avoids.
Confidence governs how a change is *marked*, not whether it is made.

`corrected.marked.txt` is the same text with each change annotated:

| mark | meaning |
|---|---|
| *(none)* | e-text kept, high confidence |
| `{+}` | OCR adopted |
| `{!}` | agent override — neither candidate |
| `{~}` `{?}` | medium / low confidence, combined with the above (`{+~}`, `{!?}`) |
| `{*}` | a human override from `reviews.json` |

`report.tsv` holds one row per item: page, line, item id, e-text reading, OCR
reading, final reading, choice, confidence, note. Sorted by page then line.
Tab-separated, since Devanagari text and transliteration both tend to contain
commas. `report.json` carries the same rows plus run totals for the interface.

`report.flagged.tsv` holds only the rows needing human eyes:

- `choice` is `other` — the agent overrode both candidates
- `confidence` is `low`

Everything else stays silent. The flagged view keeps the review pass short; the
full file remains the audit trail.

## Reviewing

`review.html` is self-contained — open it in a browser, no server needed. It
shows each changed line with the adjudicated words marked by choice and
confidence; clicking one shows both candidates, the final reading, and the
agent's note.

Review is by exception. Everything is already applied, so the interface exists to
reject or amend, not to approve item by item. Filter to flagged, overrides, or
low/medium to keep the pass short.

Decisions download as `reviews.json`. Save it next to `corrected.txt` and re-run
`apply.py`; human overrides take precedence over the agent's verdicts and are
marked `{*}`. It is the one artifact holding human judgment and cannot be
regenerated, so it is tracked.

Keep the PDF open in its own viewer — the interface cites page and line for every
item and deliberately does not duplicate the page images.

## Layout

```
input/     etext.txt, ocr.txt, source.pdf, notes.md (optional)
scripts/   prep.py, pending.py, apply.py, report.py, review.py
agents/    dispatcher.md, adjudicator.md
work/      pages/NNNN/{page.png, diffs.json, verdicts.json}  — disposable
corrected.txt, corrected.marked.txt
report.tsv, report.flagged.tsv, report.json
review.html, reviews.json
```

Everything in `work/` is regenerable from the three input files, so it stays out
of version control.

## Resumability

A page either has a `verdicts.json` or it does not. Interrupt a run and start it
again; finished pages drop off the pending list on their own. Sub-agents share no
state, so pages can be redone individually by deleting just that page's
`verdicts.json`.

## The trial

Start with ten pages chosen because the e-text is known to be imperfect there, so
the diff list is substantial rather than empty. Hand-check every verdict on the
first two pages.

The question is not only whether the verdicts are correct, but whether the
confidence scores track accuracy. If high-confidence verdicts are reliably right,
the rest of a long run can be reviewed by flag alone and the approach scales. If
confidence is uncorrelated with correctness, the readout is not trustworthy at
scale, and cropping becomes necessary after all.

That is the real question the trial answers: not whether the agent can read
Devanagari, but whether it knows when it cannot.
