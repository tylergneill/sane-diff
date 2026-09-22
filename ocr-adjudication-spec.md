# OCR Adjudication Pipeline — Design Spec

## Purpose

Use a vision-capable agent to adjudicate disagreements between a pre-existing Sanskrit e-text and OCR output, using the scanned page image of the printed edition as ground truth.

The e-text is already good. OCR is a second opinion, not a replacement. The agent's job is deliberately narrow: for each point where the two sources disagree, decide what the printed page actually reads.

## Inputs

The user supplies three required files:

1. `etext.txt` — the pre-existing e-text, one line per printed line, page-aligned.
2. `ocr.txt` — OCR output from the same edition, same line and page alignment.
3. `source.pdf` — the scanned printed edition.

Assumption treated as reliable throughout: line numbers and page boundaries are accurate and consistent across all three. The pipeline does not attempt to re-derive alignment, and every location reference downstream is a page number plus a line number.

### Optional — `notes.md`

A fourth file, always optional: an expert reader's account of the peculiarities of this particular pair of texts. Editorial markup conventions, what the bracket forms mean, whether ellipsis length carries information, how the apparatus is delimited, OCR artifacts already diagnosed.

The pipeline works without it. When absent, the sub-agent decides everything on its own from the page image, exactly as before. When present, its contents are passed verbatim into each sub-agent prompt, and the agent is expected to respect it.

This is information a sub-agent cannot derive for itself. It sees one page and has no view of the conventions running through the other four hundred; withholding what the editor knows does not make the agent more objective, it makes it worse at reading. The note removes guesswork about notation, not the obligation to look.

One procedural guardrail, stated in the prompt rather than enforced in code: where the note and the page disagree, the page wins, and the item is flagged. That keeps the note falsifiable. If it is wrong about some page, that surfaces as a flagged item instead of being silently absorbed.

## Repository layout

```
repo/
  input/
    etext.txt
    ocr.txt
    source.pdf
    notes.md         optional; expert account of the two texts
  scripts/
    prep.py          builds the working directory
    pending.py       lists pages still awaiting adjudication
    apply.py         writes the corrected text from the verdicts
    report.py        merges verdicts into the readout
  agents/
    dispatcher.md    fan-out prompt
    adjudicator.md   sub-agent prompt
  tmp/pages/
    0001/
      page.jpg
      diffs.json
      verdicts.json  (written by the sub-agent)
    0002/
    ...
  output/corrected.txt          the deliverable
  output/corrected.marked.txt   same text, changes marked for reading
  output/report.tsv             readout
  output/report.json            same rows, machine-readable
```

The working directory is disposable. Everything in `tmp/` is regenerable from the three input files, so it stays out of version control; `input/`, `scripts/`, `agents/` and the emitted deliverables are tracked.

## Stage one — prep.py

Run once, fully deterministic, no model involved. Its job is to turn three files into a directory tree that the agents can consume without any further reasoning about structure.

Responsibilities:

- Extract each PDF page's embedded scan to `page.jpg`, named by zero-padded page number.

A scanned edition stores one image per page, so the page image is already in the PDF. `pdfimages -j` copies that JPEG stream out byte for byte rather than rasterising the page, which is both faster and lossless: re-rendering a 200 DPI scan at 300 DPI interpolates pixels that were never scanned. This also removes the ImageMagick and mupdf dependencies — poppler alone is enough.
- Split `etext.txt` and `ocr.txt` into per-page blocks using the existing page markers.
- Within each page, diff the two texts line by line, then word by word within changed lines.
- Write one `diffs.json` per page.

Each diff item carries: an item id unique within the page, the line number, the word index within that line, the e-text reading, the OCR reading, and the full e-text line as surrounding context so the agent can locate the spot visually.

Pages where the two texts agree completely get no directory at all and are skipped. On a clean edition this may be most of the book, and it is the main reason the run stays cheap.

## Stage two — adjudication

A dispatcher agent fans out to five to ten sub-agents. Each sub-agent receives exactly one page directory and nothing else: no shared state, no cross-page memory, no knowledge of what any sibling is doing. That isolation is what makes the parallelism safe and the run resumable — a page either has a `verdicts.json` or it does not.

The sub-agent is given `page.jpg` in full, at full resolution, plus that page's `diffs.json`. It writes `verdicts.json` into the same directory.

Each verdict record contains:

- the item id, echoed back unchanged
- `choice` — one of `etext`, `ocr`, or `other`
- `reading` — the final adjudicated text; required when choice is `other`, and echoing the chosen source otherwise
- `confidence` — high, medium, or low
- `note` — one short sentence, present only when choice is `other` or confidence is low

When neither candidate matches what is printed, the agent commits to its own reading based on what it sees on the page and on what is sound in the language, rather than deferring or leaving the item blank. That is recorded as `other`, and every such item surfaces for review.

## Stage three — the corrected text

The primary deliverable. Every verdict is applied to the e-text and the result written as `corrected.txt`, carrying the same page markers and line structure as the input, so it diffs cleanly against `etext.txt` and shows only real changes.

Every verdict is applied regardless of confidence. A text with only the confident changes applied is a third artifact, neither the original nor the corrected version, and reconciling it by hand is the work the pipeline exists to avoid. Confidence governs how a change is *marked*, not whether it is made.

Alongside it, `corrected.marked.txt`: the same text with each adjudicated word carrying an inline marker for its confidence, and a distinct marker for `other`. The clean file stays authoritative and usable downstream; the marked file is for reading. Both are generated from the same verdict data, so neither is derived from the other by hand.

`other` is marked distinctly from low confidence. They are different failure modes: an `other` is the agent asserting a reading neither source proposed — more information, and more risk if wrong — while a low-confidence `etext` is a weak nod to a reading that was already there.

## Stage four — report.py

The report explains the corrected text rather than standing alone. It emits the same content in two forms:

- `report.tsv` — one row per adjudicated item, with columns for page, line, item id, e-text reading, OCR reading, final reading, choice, confidence, and note. Sorted by page then line. Tab-separated rather than comma-separated, since Devanagari text and transliteration both tend to contain commas.
- `report.json` — the same rows plus run-level totals, in machine-readable form.

The script also prints a short summary to the terminal: total items adjudicated, counts by choice, and the number of rows flagged for attention.

## Flagging

Two categories flag for human review:

- any item where choice is `other` — the agent overrode both candidates
- any item where confidence is low

Everything else stays silent. Alongside the full report, emit a filtered view containing only the flagged rows, so the review pass is short and the full file remains available as the audit trail.

## Review

Review happens in an ordinary diff viewer. `output/corrected.txt` and `output/corrected.marked.txt` diff against the input e-text, and `output/report.tsv` supplies the choice, confidence and note behind each item.

Review is by exception. Every verdict is already applied, so review exists to *reject*, not to approve one item at a time — defaulting to approval is what the confidence scoring was for. A verdict is corrected by editing the page's `verdicts.json` and re-running `apply.py`, which keeps every stage regenerable from the inputs plus the verdicts.

A purpose-built interface was built and then dropped. It re-implemented intra-line diff highlighting that existing tools already do better, and did it worse: a missing space inside a forty-character word highlighted all forty characters, which is feedback worse than none. Diff viewers isolate the differing characters, which is the whole question for most items.

No page images side by side. The reviewer is expected to have the PDF open in its own viewer; duplicating four hundred page images buys little and costs a great deal.

## The sub-agent prompt

The prompt in `agents/adjudicator.md` should establish, in roughly this order:

- The page image is the sole authority. The e-text and the OCR are candidate readings and nothing more; neither has priority over the other.
- Adjudicate only the listed items. Do not correct anything else on the page, and do not comment on readings that were not disputed.
- Locate each item by its line number, counting lines in the main text block. Ignore running heads, page numbers, and the footnote apparatus unless an item's line number falls there.
- Report confidence honestly. Low confidence on a smudged or broken impression is a useful signal and costs nothing; false confidence is the expensive failure.
- Respect `notes.md` when it is present, and decide unaided when it is not. Where the note and the page disagree, the page wins and the item is flagged.
- Return only the specified JSON structure, with no commentary outside it.

The main failure mode to guard against is scope creep: an agent handed a full page image is inclined to start correcting things it was not asked about. Constrain it to the item list explicitly and repeat that constraint near the end of the prompt.

## Trial run

Start with ten pages chosen because the e-text is known to be imperfect there, so the diff list is substantial rather than empty.

Hand-check every verdict on the first two pages. The question is not only whether the verdicts are correct, but whether the confidence scores track accuracy. If high-confidence verdicts are reliably right, the rest of a long run can be reviewed by flag alone, and the whole approach scales. If confidence turns out to be uncorrelated with correctness, the readout is not trustworthy at scale, and cropping becomes necessary after all.

That is the real question the trial answers: not whether the agent can read Devanagari, but whether it knows when it cannot.

## Deliberately out of scope

No deterministic page segmentation, no projection profiles, no bounding-box extraction, no proportional line slicing. The whole page image goes to the model every time.

If whole-page accuracy proves insufficient, that is the finding the trial exists to produce. It is not a problem to pre-solve, and building the segmentation layer first would obscure exactly the result being tested for.
