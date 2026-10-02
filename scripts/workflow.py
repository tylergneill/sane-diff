#!/usr/bin/env python3
"""Write the workflow that fans a Claude run out over its pending pages.

Writes tmp/workflows/<run>.js, a Workflow script with the run's sub-agent
prompt built in (from agent_prompt.py, never retyped), which starts one
sub-agent per page directory it is given. Then splits the pending pages
into groups and prints one JSON list of page directories per line. The
dispatcher starts one workflow per line, all at once.

A single workflow runs at most min(16, CPUs - 2) agents at a time, so the
pages are split into as many workflows as it takes to reach --workers
agents in flight.

  workflow.py --run claude-vision [--language Latin] [--pages 3-5] [--workers 100]
"""

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from common import PAGES, add_language_arg, parse_page_selection
from pending import pending_pages

SCRIPTS = Path(__file__).resolve().parent
OUT = Path(PAGES).parent / "workflows"

TEMPLATE = """export const meta = {
  name: 'adjudicate-pages',
  description: 'One adjudicator sub-agent per page directory',
  phases: [{ title: 'Adjudicate' }],
}
const PROMPT = %s
phase('Adjudicate')
await parallel(args.map(dir => () =>
  agent(PROMPT + '\\n' + dir, { label: dir.split('/').pop(), phase: 'Adjudicate', agentType: 'general-purpose' })))
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, choices=["claude-vision", "claude-no-vision"])
    add_language_arg(ap)
    ap.add_argument("--pages", help="only these pages, e.g. 12-21 or 3,5,9")
    ap.add_argument("--workers", type=int, default=25,
                    help="sub-agents in flight across all workflows (default 25)")
    args = ap.parse_args()

    cmd = [sys.executable, str(SCRIPTS / "agent_prompt.py"), "--run", args.run]
    if args.language:
        cmd += ["--language", args.language]
    prompt = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

    OUT.mkdir(parents=True, exist_ok=True)
    script = OUT / f"{args.run}.js"
    script.write_text(TEMPLATE % json.dumps(prompt, ensure_ascii=False), encoding="utf-8")

    only = parse_page_selection(args.pages) if args.pages else None
    dirs = [str(d.resolve()) for d, _ in pending_pages(Path(PAGES), args.run, only)]
    per_workflow = max(1, min(16, (os.cpu_count() or 4) - 2))
    groups = min(len(dirs), math.ceil(args.workers / per_workflow))

    print(f"script: {script}")
    print(f"{len(dirs)} pending page(s) in {groups} workflow(s), "
          f"up to {per_workflow} agents each")
    for i in range(groups):
        print(json.dumps(dirs[i::groups]))


if __name__ == "__main__":
    main()
