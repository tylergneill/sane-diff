# align-lines

You are running the step that lines the two texts in `input/` up line by
line: agents set out the base's lines from the page images, and a script
carries that layout over to the suggester. You start the agents, put the
result together, and talk it through with the user. You change nothing in
`input/` unless the user tells you to.

## Steps

1. Read `input/notes_lines.md` if it exists: the user's notes on the
   layout this text should have.
2. Run `python3 scripts/lines.py prep`, adding `--pages` if the request
   names pages, and `--model` if it names a model. It sets up each page in
   `tmp/lines/pages/NNNN/`, and prints the workflow script's path and a
   JSON list of the page directories still to do.
3. If the list is empty, go to step 4. Otherwise start one Workflow with
   that script as `scriptPath` and the list as `args`. It gives each page to
   a line setter (`agents/line-setter.md`). Do not set out pages yourself.
4. When the workflow is done, run `python3 scripts/lines.py apply`. It
   checks that each page changed only in whitespace, carries the base's
   layout over to the suggester, writes `tmp/lines/base.txt` and
   `tmp/lines/suggester.txt`, and prints `tmp/lines/report.txt`.
5. Read the report in full, and tell the user, briefly: how many pages were
   set out, how many now pair off line for line, any page refused and why,
   and what the agents' notes say that is worth a look. Then stop and wait.

## What the user may ask next

- **Take the result.** Copy `tmp/lines/base.txt` and `tmp/lines/suggester.txt`
  over the files in `input/`, only when the user says so. Then remind them
  to run `make prep-diffs` before `resolve`.
- **Fix a page together.** Edit `tmp/lines/pages/NNNN/base.txt` as agreed
  (whitespace only), and run `python3 scripts/lines.py apply` again: the
  suggester follows on its own.
- **Redo a page.** Delete its `done.json`, and run steps 2–4 for it with
  `--pages`.

Never edit `input/` on your own initiative.
