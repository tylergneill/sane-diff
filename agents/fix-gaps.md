# fix-gaps

You are running the step that closes the big gaps between the two texts in
`input/`: passages one text has and the other lacks, and lines the OCR
repeated. Agents do the work page by page; you start them, put the result
together, and talk it through with the user. You change nothing in `input/`
unless the user tells you to.

## Steps

1. Read `input/notes_gaps.md` if it exists: the user's notes for this text.
2. Run `python3 scripts/gaps.py find`, adding `--pages` if the request
   names pages, and `--profile` if it names a scribe profile. It finds the
   gaps, sets up each page with gaps in `tmp/gaps/pages/NNNN/`, and prints
   the workflow script's path and a JSON list of the page directories
   still to do.
3. If the list is empty, go to step 4. Otherwise start one Workflow with
   that script as `scriptPath` and the list as `args`. It takes each page
   through three agents: scribe transcribes the image, scribe checks the
   transcription, and a settler (`agents/gap-settler.md`) decides each gap.
   Do not settle pages yourself.
4. When the workflow is done, run `python3 scripts/gaps.py apply`. It
   checks that every page's edits stay within its gaps, writes
   `tmp/gaps/base.txt` and `tmp/gaps/suggester.txt`, and prints
   `tmp/gaps/report.txt`.
5. Read `tmp/gaps/report.txt` in full, including the line for every
   settled gap. Then tell the user, briefly and in prose: how many gaps
   there were, how many were settled and how (counts by kind), and the open
   cases, hardest first, each with its page and why it was left. Mention
   pages that did not get settled at all (a failed agent).
   Then tell them what is interesting among the settled gaps, the things
   an editor would want to look at, naming the pages. For example:
   - a stray copy of another page removed: name both pages, since the
     copy kept was typed separately and may differ from the one removed;
   - a side that held a whole other page, and got this page's text in full;
   - changes outside the gaps, where the texts already disagreed;
   - an addition where scribe disagreed, or had no reading;
   - anything else unusual in the reasons.
   Leave out the routine ones (a plain OCR repeat removed, a passage added
   that scribe confirms) beyond their counts. Then stop and wait.

## What the user may ask next

- **Take the result.** Copy `tmp/gaps/base.txt` and `tmp/gaps/suggester.txt`
  over the files in `input/`, only when the user says so. Then remind them
  to run `make prep-diffs` before `resolve`.
- **Settle an open case together.** Look at the page's image
  (`tmp/pages/NNNN/page.jpg`) and files with the user, edit
  `tmp/gaps/pages/NNNN/base.txt` and `suggester.txt` as agreed, update that
  page's `decisions.json`, and run `python3 scripts/gaps.py apply` again.
- **Redo a page.** Delete its `decisions.json` (and `scribe.done` to redo
  scribe's reading too), and run steps 2–4 for it with `--pages`.

Never edit `input/` on your own initiative.
