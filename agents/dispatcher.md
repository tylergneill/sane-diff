# Dispatcher

You coordinate Claude sub-agents over the page directories in `tmp/pages/`,
for one of two runs. You do not adjudicate anything yourself.

| run | sub-agent prompt | each sub-agent writes |
|---|---|---|
| `claude-vision` | `agents/claude-adjudicator.md` | `verdicts.json` |
| `claude-no-vision` | `agents/adjudicator-no-vision.md` | `verdicts.claude-no-vision.json` |

The user's request names the run, and may name the language of the texts
and how many sub-agents to keep in flight.

## What to do

1. Run `python3 scripts/pending.py --run <run> --list` to list the page
   directories that have a `diffs.json` but no verdict file for this run.
   If the request names pages, such as "pages 3-5", add `--pages 3-5` every
   time you run it, and dispatch nothing outside that range.
2. Fan out to sub-agents, one page directory each, up to twenty-five in
   flight at a time, or as many as the request names. Do it with workflows,
   so the sub-agents start in parallel:
   run `python3 scripts/workflow.py --run <run> --workers <n>`, adding
   `--pages` and `--language` as in step 1 and below. It writes the workflow
   script and prints one JSON list of page directories per line. In a single
   message, start one Workflow per line, each with the printed script's
   absolute path as `scriptPath` and that line as `args`. One workflow runs
   only about nine agents at once, which is why there are several.
3. Give each sub-agent exactly one page directory and nothing else. No shared
   state, no cross-page context, no mention of what any sibling is doing or
   found. That isolation is what makes the parallelism safe. The workflow
   script does this for you.
4. When the workflows return, list the pending pages again, and run step 2
   again for what is left. Repeat until nothing is pending.
5. Finish the run yourself, in this session: `make finish` for
   `claude-vision`, `make finish-claude-no-vision` for `claude-no-vision`.
   It writes `output/<run>/` and removes the page images. Finish even if some
   pages failed, so what did finish is written. Then tell the user the run is
   finished, or which pages failed, and show the report's summary.

## What each sub-agent is told

Run `python3 scripts/agent_prompt.py --run <run>` once, adding
`--language <language>` if the request names one. It prints the run's prompt
with the language filled in and `input/notes.md` appended when there is one.
Hand each sub-agent that output verbatim, followed by the path to its one
page directory, and nothing else. `scripts/workflow.py` builds this into the
workflow script for you, so you need not run `agent_prompt.py` yourself.

Do not paraphrase the prompt, do not add your own guidance about how to read
the page, and do not pass along anything you learned from another page. A
sub-agent that knows what its siblings decided is no longer an independent
reading.

## Resumability

A page is finished when it has this run's verdict file. If a run is
interrupted, start again from step 1 — finished pages drop off the pending
list on their own. Never re-dispatch a finished page, and never delete a
verdict file to force a redo unless the user asks for it.

## Failures

If a sub-agent returns without writing its verdict file, or writes something
that is not valid JSON, retry that page once. If it fails a second time, leave
it pending and report it to the user by page number. Do not write a
placeholder, and do not do the page yourself — an unfinished page is a visible
gap, while a fabricated one is not.
