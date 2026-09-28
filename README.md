# sane-diff

Reconciles two page-aligned transcriptions of the same text, one page at a
time, with a language model reading both, and the page images too if you
like. Language-agnostic, with Sanskrit as a default.

The **base** is the text whose readings are kept by default, usually the one
readers already trust. The **suggester** is a second transcription that
proposes changes to it. These can be OCR, a hand transcription, another
model's output, or anything in between. Both texts must carry the same page 
markers, `<p.12>` or `=== 12 ===` (detected per file).

Each page is seen in isolation from every other. General prompts are set in 
`agents/` and shown equally to every inference call or agent. The LLM can 
issue decisions either on the level of individual diff items, or it can 
rewrite the whole page.

Currently supported:
- LLM backends Claude subscription or Gemini API
- Visual reference to PDF (Claude only)
- Item-specific instructions in `input/notes.md` (Claude only)
- API cost reporting (Gemini only)

## Install

| what | how | needed for |
|---|---|---|
| Python 3.9+ (tested on 3.11) | on macOS already, or `brew install python` | everything |
| `make` | `xcode-select --install` | everything |
| poppler | `brew install poppler` | extracting page images |
| litellm, tqdm | `pip install -r requirements.txt` | the Gemini run; progress bars (optional) |
| Claude Code | [claude.com/claude-code](https://claude.com/claude-code), then run `claude` once to log in (Max plan or higher recommended; see below) | the Claude runs |
| Gemini API key | `GEMINI_API_KEY=...` in `.env` at the repo root (gitignored), or in your environment | the Gemini run |
| meld | `brew install --cask meld` | optional: reading output against the base |

Everything else is Python standard library. `make review` opens images with
macOS `open`.

## Run

```sh
make init BASE=path/to/base.txt SUGGESTER=path/to/suggester.txt IMAGE=path/to/image.pdf
make prep-pending
make resolve
make review
```

| target | what it does | output |
|---|---|---|
| `init` | clears `input/` (except `notes.md`), `tmp/` and `output/`, asking first if the last two hold anything, then copies in the files. `IMAGE` is optional; without it only no-vision runs work. | |
| `prep-pending` | finds every disagreement, page by page, and lists pages still to resolve | |
| `resolve` | Claude sub-agents settle each disagreement, looking at the page image | `output/claude-vision/` |
| `resolve-claude-no-vision` | the same, from the texts and notes only | `output/claude-no-vision/` |
| `resolve-gemini-no-vision` | the Gemini API rewrites each page whole, as the old notebook did | `output/gemini-no-vision/` |
| `review` | walks a Claude run's questionable verdicts, opening each page image | |
| `review-summary` | counts a Claude run's verdicts by source and confidence | |

Every target takes `PAGES=3-5`. `resolve-claude-no-vision` takes
`LANGUAGE=Latin` (or any language; the default is the `LANGUAGE` line in
`scripts/common.py`). The other two targets use their original prompts,
`agents/claude-adjudicator.md` and `agents/gemini-harmonizer.md`, unchanged,
and those name Sanskrit themselves.
For the no-vision Claude run, pass `VISION=no` to `review`.

Each `resolve*` writes its report when it finishes, then deletes the page
images, the bulk of `tmp/`; `review` extracts them again (fast).

The `resolve*` targets differ along three axes:

| axis | values |
|---|---|
| backend | Claude sub-agents (on your subscription) · Gemini API |
| unit | `item`: the model decides each disagreement and a script applies its answers · `page`: the model rewrites the whole page |
| vision | the model sees the page image, or not |

A Claude run starts Claude Code as `claude "<prompt>"`, which fans out one
sub-agent per page following `agents/dispatcher.md`; `make` writes the report
when you leave the session. An interrupted run resumes where it stopped.

**Claude runs are token-hungry.** Each page gets a fresh sub-agent, and in
a vision run each one reads a full page image. A whole book uses a lot of
your subscription, so these runs are recommended only on a Max plan or
higher. Try `PAGES=1-3` first to see what a page costs you.

## Gemini

Every billed response, failed ones included, is logged in
`tmp/usage/gemini-2.5-flash.jsonl` with its usage, price and cost. The report
prints the running total:

```
label             pages  calls  failed  prompt tok  output tok  thought tok  cost USD
gemini-2.5-flash      2      2       0       1,733         425        5,639    0.0157
```

Prompt tokens are charged at the input rate; visible output and thinking at
the output rate, as Google bills them. The rates are in `PRICES` in
`scripts/gemini.py`, dated; keep them current. A model with no price is
refused rather than recorded at $0. `make init` deletes the ledger with the
rest of `tmp/`, after asking.

The prompt is `agents/gemini-harmonizer.md`, the old notebook's, with the two
pages filled in; it does not use `input/notes.md`. `python3 scripts/merge.py
prompt 12` prints exactly what page 12 is sent.

## Review

Output should be inspected directly with a good diff tool like [Meld](https://meld.en.softonic.com/)

```sh
meld input/base.txt output/claude-vision/corrected.txt
```

`corrected.marked.txt` shows each change with its verdict:

| mark | |
|---|---|
| *(none)* | base kept, high confidence |
| `{+}` | suggester adopted |
| `{!}` | agent override — neither candidate |
| `{~}` `{?}` | medium / low confidence, combined (`{+~}`, `{!?}`) |

This same markup in `corrected.marked.txt` is consumed by sane-diff's own
review system: `make review` opens a CLI interface that walks the low- and 
medium-confidence verdicts page by page, showing the base, the suggester, 
the reading and the agent's note, and opens each page image without raising 
the viewer (so place the image viewer window where you want it first).
High-confidence verdicts are never shown. For narrower
walks, `scripts/review.py --overrides` shows only `other` verdicts, and
`--low` only low-confidence ones.

Between pages, `b` or `s` rewrites a verdict to the base or the suggester
(`b3` for item 3 on a page with several), saving at once. It becomes
`decided_by: human` at `high` confidence and drops out of later walks. Run
`make report` afterwards to update `output/`.

`scripts/review.py --set p0002-002=suggester` settles one named item without
walking. For a reading neither source has, edit the page's verdict file:
`choice` to `other`, and the `reading` yourself. Don't edit `corrected.txt`;
the report regenerates it.

`report.flagged.tsv` lists the overrides and low-confidence readings,
`report.tsv` every item, `report.json` the same plus totals.

## How the item unit decides

Most disagreements are easy — a dropped mark, a typo — and are settled
automatically. The hard ones are left for you at low confidence. The base is
the default: the agent adopts the suggester's reading when the evidence
points to it, and proposes its own (`other`, at most medium confidence) only
when neither can be right. A wrong correction is hard to find once applied,
while an open item costs a minute of review. Every verdict is applied;
confidence only sets the mark. The reasoning is in `docs/adjudicate-spec.md`.

## Starting over

`make init` starts a new text. To redo a run, delete its verdict files
(`tmp/pages/*/verdicts.json`, or `verdicts.claude-no-vision.json`), or for
Gemini `tmp/pages/*/merged/`, and resolve again; for one page, delete just
its file.
