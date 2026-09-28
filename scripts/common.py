"""Helpers shared by the adjudicate and merge pipelines.

Both tasks take the same two inputs. The *base* is the text whose readings are
kept by default; the *suggester* is a second transcription that proposes
changes to it. Neither has to be OCR. What each one actually is belongs in
input/notes.md, not in the code.
"""

import re
import sys

# Page-marker formats that can be named instead of spelled out as a regex,
# which matters when the regex has to survive a shell or a Makefile.
MARKERS = {
    "p": r"^\s*<p\.(\d+)>\s*$",          # <p.12>
    "equals": r"^\s*===\s*(\d+)\s*===\s*$",  # === 12 ===
}
DEFAULT_MARKER = MARKERS["p"]


def marker_regex(value):
    """argparse type for --marker: 'auto', a name from MARKERS, or a regex."""
    return MARKERS.get(value, value)


def resolve_marker(marker, text, label, die):
    """Turn --marker auto into whichever named marker the text actually uses."""
    if marker != "auto":
        return marker
    for regex in MARKERS.values():
        pattern = re.compile(regex)
        if any(pattern.match(line) for line in text.splitlines()):
            return regex
    die(f"{label}: no page markers found; expected <p.12> or === 12 ===, "
        f"or pass --marker a regex")


# Where everything lives. tmp/ holds the page directories and the Gemini cost
# ledger; output/ holds one folder per run.
WORK = "tmp"
PAGES = "tmp/pages"

# An item-unit run is named for its backend and vision, and writes its own
# verdict file into each page directory, so runs never overwrite each other.
DEFAULT_RUN = "claude-vision"


def verdicts_name(run):
    return f"verdicts.{run}.json"


def add_run_arg(ap):
    ap.add_argument("--run", default=DEFAULT_RUN,
                    help=f"which run's verdicts: claude-vision (default) or claude-no-vision")

ROLES = ("base", "suggester")

# The language of the texts, as every prompt names it. Change it here to
# change the default, or pass LANGUAGE=... to any make resolve* run.
LANGUAGE = "Sanskrit"


def fill_language(prompt, language):
    """Put the language into a prompt template's {language} slots.

    A plain replace, not str.format: the prompts contain JSON examples whose
    braces format would try to read as fields.
    """
    return prompt.replace("{language}", language)


def add_language_arg(ap):
    ap.add_argument("--language", default=LANGUAGE,
                    help=f"the language of the texts, as the prompt names it "
                         f"(default: {LANGUAGE})")

try:
    from tqdm import tqdm
except ImportError:  # optional; the scripts stay runnable without it
    def tqdm(iterable=None, **kwargs):
        return _Counter(iterable, **kwargs)


class _Counter:
    """Enough of tqdm's interface for these scripts: iterate, or update by hand."""

    def __init__(self, iterable=None, desc="", total=None, **_):
        self.iterable = iterable
        self.desc = desc
        self.total = total if total is not None else len(iterable)
        self.n = 0
        self.postfix = ""
        self.live = sys.stderr.isatty()

    def __iter__(self):
        for item in self.iterable:
            yield item
            self.update(1)
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def update(self, n=1):
        self.n += n
        if self.live:
            print(f"\r{self.desc}: {self.n}/{self.total} {self.postfix}", end="",
                  file=sys.stderr, flush=True)

    def set_postfix_str(self, text):
        self.postfix = text

    def close(self):
        if self.live:
            print(file=sys.stderr)
        else:
            print(f"{self.desc}: {self.n}/{self.total} {self.postfix}", file=sys.stderr)


def split_pages(text, marker, label, die, markers=None):
    """Split a text into {page_number: [lines]} on its page markers.

    Pass a dict as `markers` to have it filled with {page_number: marker line},
    for writing the pages back out in the form they came in.

    Page numbers come from the marker's first capture group. A marker with no
    group numbers the pages 1, 2, 3... in the order they appear, so two texts
    split that way are paired by position rather than by printed number.

    Line numbers are 1-based within each page and count every line of the
    page block, blank lines included, so that base and suggester line numbers
    refer to the same printed line. Keep it that way: the line alignment in
    prep.py's page_diffs depends on both texts being numbered the same, and
    skipping blanks would desynchronize them.

    Because a text is often blank-line separated, these numbers run ahead of
    the printed line count on the scan. They are not a page coordinate, and
    an adjudicator reading the image should locate items by context rather
    than by counting lines down the page.
    """
    pattern = re.compile(marker)
    pages = {}
    current = None
    lines = []
    for raw in text.splitlines():
        m = pattern.match(raw)
        if m:
            if current is not None:
                pages[current] = lines
            current = int(m.group(1)) if pattern.groups else len(pages) + 1
            if current in pages:
                die(f"{label}: page {current} appears more than once")
            if markers is not None:
                markers[current] = raw
            lines = []
        else:
            lines.append(raw)
    if current is not None:
        pages[current] = lines
    elif lines:
        die(f"{label}: no page markers matched {marker!r}")
    return pages


def parse_page_selection(spec):
    """Parse '12-21' or '3,5,9' or a mix into a set of page numbers."""
    wanted = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            wanted.update(range(int(lo), int(hi) + 1))
        else:
            wanted.add(int(chunk))
    return wanted
