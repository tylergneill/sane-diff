#!/usr/bin/env python3
"""Print the full sub-agent prompt for a Claude run.

The run's prompt file with the language filled in, followed by
input/notes.md under "Editor's notes" when that file exists. The dispatcher
hands this output to every sub-agent verbatim, so the prompt is assembled
by code rather than by an agent's reading of instructions.

  agent_prompt.py --run claude-vision [--language Latin]
"""

import argparse
import sys
from pathlib import Path

from common import DEFAULT_RUN, add_language_arg, fill_language

AGENTS = Path(__file__).resolve().parent.parent / "agents"
PROMPTS = {
    "claude-vision": AGENTS / "adjudicator.md",
    "claude-no-vision": AGENTS / "adjudicator-no-vision.md",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default=DEFAULT_RUN, choices=sorted(PROMPTS))
    add_language_arg(ap)
    ap.add_argument("--notes", default=Path("input/notes.md"), type=Path)
    args = ap.parse_args()

    prompt = fill_language(PROMPTS[args.run].read_text(encoding="utf-8"), args.language)
    if args.notes.exists():
        prompt = (prompt.rstrip() + "\n\n## Editor's notes\n\n"
                  + args.notes.read_text(encoding="utf-8").strip() + "\n")
    sys.stdout.write(prompt)


if __name__ == "__main__":
    main()
