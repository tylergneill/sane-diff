#!/usr/bin/env python3
"""Page unit: a model rewrites each page whole from the two transcriptions.

Where the item unit asks a model only about the listed disagreements, here
it reads both versions of a page and writes the merged page out in full. The base is preferred where nothing else decides; the
suggester proposes changes to it.

Each page can be merged by more than one backend, and each backend's result
is kept under its own label, so outputs can be compared page by page:

  gemini-<model>   written by `merge.py gemini`, over the Gemini API
  claude           written by Claude Code sub-agents; see agents/dispatcher.md

Every backend gets the same prompt, which `merge.py prompt` prints.

Subcommands:

  prep      split the inputs into tmp/pages/NNNN/
  prompt    print the exact prompt for one page
  pending   show progress per label, or list a label's unfinished pages
  gemini    merge pending pages over the Gemini API, recording cost
  cost      total the Gemini spend recorded in the ledger
  assemble  join each label's pages into <out>/<label>.txt
  compare   score how far two labels (or base/suggester) differ, per page
"""

import argparse
import difflib
import json
import math
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import gemini
from common import ROLES, WORK, marker_regex, parse_page_selection, resolve_marker, split_pages, tqdm

REPO = Path(__file__).resolve().parent.parent
# The notebook's prompt, verbatim: two {} slots, filled with the base's page
# and then the suggester's by str.format, exactly as the notebook did it.
PROMPT = REPO / "agents" / "gemini-harmonizer.md"

# Output-budget estimate, the notebook's: visible tokens per character of the
# base's page, times a generous allowance for thinking, plus a buffer. It sets
# the first attempt's cap; a page that runs out is retried at double.
CHAR_TO_VISIBLE_TEXT_TOK = 0.9
COMPLETION_PER_VISIBLE_TEXT = 8.5
BUFFER = 1.2


def estimate_max_output_tokens(base_text):
    # The same operations in the same order as the notebook, so the float
    # rounds the same way and the request carries the same maxOutputTokens.
    visible_text_tokens_est = len(base_text) * CHAR_TO_VISIBLE_TEXT_TOK
    completion_tokens_est = visible_text_tokens_est * COMPLETION_PER_VISIBLE_TEXT
    return int(math.ceil(completion_tokens_est * BUFFER))


def die(msg):
    print(f"merge.py: {msg}", file=sys.stderr)
    sys.exit(1)


# --- work directory ----------------------------------------------------------

def page_dirs(work, only=None):
    pages = work / "pages"
    if not pages.is_dir():
        die(f"no pages at {pages}; run `merge.py prep` first")
    dirs = sorted(p for p in pages.iterdir() if p.is_dir() and p.name.isdigit())
    if only is not None:
        dirs = [d for d in dirs if int(d.name) in only]
    return dirs


def output_path(page_dir, label):
    return page_dir / "merged" / f"{label}.txt"


def labels_in(work):
    found = set()
    for d in page_dirs(work):
        found.update(p.stem for p in (d / "merged").glob("*.txt"))
    return sorted(found)


def write_atomic(path, text):
    """Write via a temporary file, so an interrupted run never leaves a
    half-written page that would then count as done."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def page_text(page_dir, role):
    return (page_dir / f"{role}.txt").read_text(encoding="utf-8")


# --- prep --------------------------------------------------------------------

def cmd_prep(args):
    texts, markers = {}, {}
    for role, path in (("base", args.base), ("suggester", args.suggester)):
        if not path.exists():
            die(f"missing input file: {path}")
        found = {}
        text = path.read_text(encoding="utf-8")
        marker = resolve_marker(args.marker, text, path.name, die)
        texts[role] = split_pages(text, marker, path.name, die, found)
        markers[role] = found

    base, sugg = texts["base"], texts["suggester"]
    only_b = sorted(set(base) - set(sugg))
    only_s = sorted(set(sugg) - set(base))
    if only_b or only_s:
        print(f"merge.py: warning: pages only in base: {only_b or 'none'}; "
              f"only in suggester: {only_s or 'none'}", file=sys.stderr)

    shared = sorted(set(base) & set(sugg))
    if args.pages:
        wanted = parse_page_selection(args.pages)
        shared = [p for p in shared if p in wanted]
    if not shared:
        die("no pages in common between the two texts")

    # Rewriting a page's inputs under results made from the old ones would
    # leave those results describing text that is no longer there.
    stale = []
    pages_root = args.work / "pages"
    for n in shared:
        d = pages_root / f"{n:04d}"
        for role in ROLES:
            f = d / f"{role}.txt"
            if f.exists() and f.read_text(encoding="utf-8") != _page_body(texts[role][n]):
                if any((d / "merged").glob("*.txt")):
                    stale.append(n)
                break
    if stale:
        die(f"input text changed on {len(stale)} page(s) that already have merged "
            f"output ({', '.join(map(str, stale[:10]))}{'...' if len(stale) > 10 else ''}); "
            f"delete {args.work} to start over")

    for n in shared:
        d = pages_root / f"{n:04d}"
        d.mkdir(parents=True, exist_ok=True)
        for role in ROLES:
            (d / f"{role}.txt").write_text(_page_body(texts[role][n]), encoding="utf-8")

    manifest_path = args.work / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("markers", {}).update({str(n): markers["base"][n] for n in shared})
    manifest.update({"base": str(args.base), "suggester": str(args.suggester)})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

    print(f"pages prepared: {len(shared)}")
    print(f"wrote {pages_root}/")


def _page_body(lines):
    return "\n".join(lines).strip() + "\n"


# --- prompt ------------------------------------------------------------------

def build_prompt(page_dir):
    """The whole prompt for one page. No notes and no language: the prompt
    carries its own, as it did in the notebook."""
    return PROMPT.read_text(encoding="utf-8").format(
        page_text(page_dir, "base").strip(), page_text(page_dir, "suggester").strip())


def resolve_page(work, spec):
    """A page number or a page directory path -> the page directory."""
    path = Path(spec)
    if path.is_dir():
        return path
    if spec.isdigit():
        d = work / "pages" / f"{int(spec):04d}"
        if d.is_dir():
            return d
    die(f"no such page: {spec}")


def inputs_agree(page_dir):
    """True when the base and the suggester give the same page, so there is
    nothing for a model to settle. Compared as the prompt would carry them."""
    paths = [page_dir / f"{role}.txt" for role in ROLES]
    if not all(p.exists() for p in paths):
        return False
    return page_text(page_dir, "base").strip() == page_text(page_dir, "suggester").strip()


def cmd_prompt(args):
    sys.stdout.write(build_prompt(resolve_page(args.work, args.page)))


# --- pending -----------------------------------------------------------------

def cmd_pending(args):
    dirs = page_dirs(args.work, parse_page_selection(args.pages) if args.pages else None)
    if args.label:
        todo = [d for d in dirs if not output_path(d, args.label).exists()]
        if args.list:
            for d in todo:
                print(d)
            return
        if todo:
            print(f"{args.label}: {len(todo)} of {len(dirs)} page(s) pending")
        else:
            print(f"{args.label}: all {len(dirs)} page(s) merged")
        return
    labels = labels_in(args.work)
    if not labels:
        print(f"{len(dirs)} page(s) prepared, none merged yet")
        return
    width = max(len(l) for l in labels)
    for label in labels:
        done = sum(1 for d in dirs if output_path(d, label).exists())
        print(f"{label:<{width}}  {done}/{len(dirs)} page(s)")


# --- gemini ------------------------------------------------------------------

def ledger_path(work, label):
    return work / "usage" / f"{label}.jsonl"


class Ledger:
    """Append-only record of every billed Gemini response, failed ones too.

    Each line keeps the usage as reported alongside the cost worked out from
    it and the price used, so a total can always be traced back to what the
    provider reported, and a later price change never rewrites past spend.
    """

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry):
        line = json.dumps(entry, ensure_ascii=False)
        with self.lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class PageFailed(Exception):
    """A page that could not be merged, carrying what it cost anyway: every
    billed attempt before the failure is real spend."""

    def __init__(self, message, spent):
        super().__init__(message)
        self.spent = spent


def merge_one(page_dir, prompt, model, price, key, ledger, run_id, args):
    """Merge one page, retrying as needed. Returns (text, seconds, cost), or
    raises PageFailed with the cost so far."""
    spent = [0.0]
    try:
        return _merge_one(page_dir, prompt, model, price, key, ledger, run_id, args, spent)
    except PageFailed:
        raise
    except Exception as exc:
        # e.g. a billed attempt ran out of budget, then the retry hit a rate
        # limit that never cleared: the first attempt still has to be counted.
        raise PageFailed(f"{type(exc).__name__}: {exc}", spent[0]) from exc


def _merge_one(page_dir, prompt, model, price, key, ledger, run_id, args, spent):
    budget = min(gemini.MAX_OUTPUT_CAP,
                 estimate_max_output_tokens(page_text(page_dir, "base").strip()))
    bad_finishes = 0
    t0 = time.time()
    for attempt in range(1, args.max_retries + 1):
        try:
            r = gemini.generate(model, prompt, key=key, temperature=args.temperature,
                                max_output_tokens=budget)
        except gemini.GeminiError as exc:
            # No response came back, so there is nothing to bill or record.
            if not exc.retryable or attempt == args.max_retries:
                raise
            time.sleep(args.backoff ** attempt)
            continue

        usd, upper = gemini.cost(r.usage, price)
        spent[0] += usd
        ledger.record({
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run": run_id,
            "page": int(page_dir.name),
            "attempt": attempt,
            "model": gemini.model_id(model),
            "model_version": r.model_version,
            "finish_reason": r.finish_reason,
            "max_output_tokens": budget,
            "prompt_tokens": r.usage.prompt,
            "cached_tokens": r.usage.cached,
            "output_tokens": r.usage.candidates,
            "thought_tokens": r.usage.thoughts,
            "cost_usd": round(usd, 8),
            "cost_is_upper_bound": upper,
            "price": gemini.price_dict(price),
            "usage": r.usage_raw,
        })

        if r.finish_reason == "stop" and r.text.strip():
            return r.text, time.time() - t0, spent[0]
        if r.finish_reason == "length" and budget < gemini.MAX_OUTPUT_CAP:
            # Usually thinking ate the budget before the answer was done.
            budget = min(gemini.MAX_OUTPUT_CAP, budget * 2)
            continue
        bad_finishes += 1
        if bad_finishes >= 2:
            break
    raise PageFailed(f"gave up after attempt {attempt}: finish_reason {r.finish_reason}",
                     spent[0])


def cmd_gemini(args):
    for model in args.model:
        if gemini.price_for(model) is None and not args.allow_unpriced:
            die(f"no price configured for {gemini.short_name(model)} in scripts/gemini.py; "
                f"add one, or pass --allow-unpriced to run and record its cost as $0")

    key = gemini.api_key()
    if not key:
        die(f"no GEMINI_API_KEY in the environment or in {gemini.ENV_FILE}")

    only = parse_page_selection(args.pages) if args.pages else None
    dirs = page_dirs(args.work, only)
    failed_any = False

    for model in args.model:
        label = f"gemini-{gemini.short_name(model)}"
        price = gemini.price_for(model) or gemini.ModelPrice(0.0, 0.0)
        pending = [d for d in dirs if not output_path(d, label).exists()]
        # A page the two inputs agree on, including one both leave empty, has
        # nothing to merge: its text goes to the output as it is, without a
        # call, so the assembled file keeps every page. It still counts as
        # handled on the progress bar.
        same = [d for d in pending if inputs_agree(d)]
        todo = [d for d in pending if d not in same]
        print(f"\n*** {label}: {len(pending)} of {len(dirs)} page(s) to merge"
              + (f", {len(same)} of them skipped, the inputs agreeing" if same else "")
              + " ***", flush=True)
        if not pending:
            continue

        ledger = Ledger(ledger_path(args.work, label))
        run_id = uuid.uuid4().hex[:8]
        done, errors, secs = 0, {}, []
        run_cost = 0.0
        t_start = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as ex, \
                tqdm(total=len(pending), desc=label, unit="page") as bar:
            for d in same:
                write_atomic(output_path(d, label), page_text(d, "base").strip() + "\n")
            bar.set_postfix_str(f"skipped={len(same)}", refresh=False)
            bar.update(len(same))
            futures = {
                ex.submit(merge_one, d, build_prompt(d), model, price, key,
                          ledger, run_id, args): d
                for d in todo
            }
            for fut in as_completed(futures):
                d = futures[fut]
                try:
                    text, dt, usd = fut.result()
                    write_atomic(output_path(d, label), text.strip() + "\n")
                    done += 1
                    secs.append(dt)
                    run_cost += usd
                except PageFailed as exc:  # report every page, keep going
                    errors[int(d.name)] = f"{exc} (${exc.spent:.4f} spent on this page)"
                    run_cost += exc.spent
                post = f"ok={done} err={len(errors)} skipped={len(same)} cost=${run_cost:.4f}"
                if secs:
                    post += f" med={median(secs):.1f}s"
                bar.set_postfix_str(post, refresh=False)
                bar.update(1)

        # The ledger is the authority; the bar's running figure should agree
        # with it. Failed attempts include the first tries of pages that
        # later succeeded, e.g. one that ran out of budget and was retried.
        entries = [e for e in read_ledger(ledger.path) if e["run"] == run_id]
        run_total = sum(e["cost_usd"] for e in entries)
        wasted = sum(e["cost_usd"] for e in entries if e["finish_reason"].lower() != "stop")
        print(f"{label}: {done} merged, {len(same)} skipped, {len(errors)} failed, "
              f"{time.time() - t_start:.1f}s")
        print(f"  cost this run: ${run_total:.4f}"
              + (f" (of which ${wasted:.4f} on failed attempts)" if wasted > 5e-7 else ""))
        for page, msg in sorted(errors.items()):
            print(f"  page {page}: {msg}", file=sys.stderr)
        failed_any = failed_any or bool(errors)

    print()
    cmd_cost(args)
    if failed_any:
        sys.exit(1)


# --- cost --------------------------------------------------------------------

def read_ledger(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def cmd_cost(args):
    usage_dir = args.work / "usage"
    ledgers = sorted(usage_dir.glob("*.jsonl")) if usage_dir.is_dir() else []
    if getattr(args, "label", None):
        ledgers = [p for p in ledgers if p.stem == args.label]
    if not ledgers:
        print("no Gemini spend recorded")
        return

    header = ["label", "pages", "calls", "failed", "prompt tok", "output tok",
              "thought tok", "cost USD"]
    body = []
    grand, upper_any = 0.0, False
    for path in ledgers:
        entries = read_ledger(path)
        # Case-insensitive, so entries written before the switch to LiteLLM
        # ("STOP") still read as successes.
        ok = [e for e in entries if e["finish_reason"].lower() == "stop"]
        usd = sum(e["cost_usd"] for e in entries)
        upper = any(e.get("cost_is_upper_bound") for e in entries)
        grand += usd
        upper_any = upper_any or upper
        body.append([path.stem,
                     str(len({e["page"] for e in ok})),
                     str(len(entries)),
                     str(len(entries) - len(ok)),
                     f"{sum(e['prompt_tokens'] for e in entries):,}",
                     f"{sum(e['output_tokens'] for e in entries):,}",
                     f"{sum(e['thought_tokens'] for e in entries):,}",
                     f"{'≤' if upper else ''}{usd:.4f}"])
    widths = [max(len(r[i]) for r in [header] + body) for i in range(len(header))]
    fmt = lambda row: "  ".join(c.ljust(w) if i == 0 else c.rjust(w)
                                for i, (c, w) in enumerate(zip(row, widths)))
    print(fmt(header))
    for row in body:
        print(fmt(row))
    if len(body) > 1:
        print(f"total: ${grand:.4f}")
    if upper_any:
        print("≤ some prompt tokens were served from cache at a rate not in the price "
              "table, and were charged at the full input rate")


# --- assemble ----------------------------------------------------------------

def cmd_assemble(args):
    manifest_path = args.work / "manifest.json"
    markers = json.loads(manifest_path.read_text(encoding="utf-8"))["markers"] \
        if manifest_path.exists() else {}
    dirs = page_dirs(args.work)
    labels = args.label or labels_in(args.work)
    if not labels:
        die("nothing merged yet")
    args.out.mkdir(parents=True, exist_ok=True)
    for label in labels:
        chunks, missing = [], []
        for d in dirs:
            n = int(d.name)
            out = output_path(d, label)
            marker = markers.get(str(n), f"<p.{n}>")
            # A missing page keeps its marker, so the assembled files for two
            # labels stay page-aligned in a diff viewer.
            body = out.read_text(encoding="utf-8").strip() if out.exists() else ""
            if not out.exists():
                missing.append(n)
            chunks.append(f"{marker}\n\n{body}" if body else marker)
        dest = args.out / f"{label}.txt"
        dest.write_text("\n\n".join(chunks) + "\n", encoding="utf-8")
        note = f" ({len(missing)} page(s) missing: {_short_list(missing)})" if missing else ""
        print(f"wrote {dest}{note}")


def _short_list(pages, n=10):
    return ", ".join(map(str, pages[:n])) + ("..." if len(pages) > n else "")


# --- compare -----------------------------------------------------------------

def label_text(page_dir, label):
    path = page_dir / f"{label}.txt" if label in ROLES else output_path(page_dir, label)
    return path.read_text(encoding="utf-8") if path.exists() else None


def cmd_compare(args):
    only = parse_page_selection(args.pages) if args.pages else None
    rows, skipped = [], []
    for d in page_dirs(args.work, only):
        a, b = label_text(d, args.a), label_text(d, args.b)
        if a is None or b is None:
            skipped.append(int(d.name))
            continue
        aw, bw = a.split(), b.split()
        m = difflib.SequenceMatcher(a=aw, b=bw, autojunk=False)
        changed = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in m.get_opcodes()
                      if tag != "equal")
        chars = difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio()
        rows.append((int(d.name), changed, chars, len(aw)))

    if not rows:
        die(f"no page has both {args.a} and {args.b}")

    identical = sum(1 for r in rows if r[1] == 0 and r[2] == 1.0)
    words = sum(r[3] for r in rows)
    diffs = sum(r[1] for r in rows)
    print(f"{args.a} vs {args.b}: {len(rows)} page(s) compared, {identical} identical")
    print(f"  words differing: {diffs} of {words} ({100 * diffs / max(words, 1):.1f}%)")
    if skipped:
        print(f"  skipped {len(skipped)} page(s) missing from one side: {_short_list(skipped)}")

    worst = sorted((r for r in rows if r[1] or r[2] < 1.0), key=lambda r: (r[2], -r[1]))
    if worst:
        print(f"\nmost divergent pages (of {len(worst)} that differ):")
        print("  page  words≠  similarity")
        for page, changed, ratio, _ in worst[:args.top]:
            print(f"  {page:>4}  {changed:>6}  {ratio:>9.3f}")

    manifest_path = args.work / "manifest.json"
    inputs = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    side = lambda l: inputs.get(l, l) if l in ROLES else f"{args.out}/{l}.txt"
    print(f"\nto read the differences: meld {side(args.a)} {side(args.b)}")
    if any(l not in ROLES for l in (args.a, args.b)):
        print("(run `merge.py assemble` first if those files are missing or stale)")


# --- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=Path(WORK), type=Path,
                    help="working directory (default: tmp)")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="SUBCOMMAND")

    p = sub.add_parser("prep", help="split the inputs into per-page directories")
    p.add_argument("--base", default=Path("input/base.txt"), type=Path)
    p.add_argument("--suggester", default=Path("input/suggester.txt"), type=Path)
    p.add_argument("--marker", default="auto", type=marker_regex,
                   help="page marker: auto (default: <p.12> or === 12 ===, detected per "
                        "file), or a regex whose group 1 is the page number")
    p.add_argument("--pages", help="restrict to these pages, e.g. 12-21 or 3,5,9")
    p.set_defaults(func=cmd_prep)

    p = sub.add_parser("prompt", help="print the exact prompt for one page")
    p.add_argument("page", help="a page number, or a page directory")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("pending", help="progress per label, or one label's unfinished pages")
    p.add_argument("--label", help="e.g. claude or gemini-2.5-flash")
    p.add_argument("--list", action="store_true",
                   help="with --label, one pending page directory per line")
    p.add_argument("--pages")
    p.set_defaults(func=cmd_pending)

    p = sub.add_parser("gemini", help="merge pending pages over the Gemini API")
    p.add_argument("--model", action="append", required=True,
                   help="e.g. 2.5-flash; repeat to run several models in turn")
    p.add_argument("--pages")
    p.add_argument("--workers", type=int, default=20)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--max-retries", type=int, default=5)
    p.add_argument("--backoff", type=float, default=2.0,
                   help="seconds are backoff ** attempt after a rate limit or outage")
    p.add_argument("--allow-unpriced", action="store_true",
                   help="run a model with no price configured, recording $0")
    p.set_defaults(func=cmd_gemini)

    p = sub.add_parser("cost", help="total the Gemini spend recorded so far")
    p.add_argument("--label")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("assemble", help="join each label's pages into one file")
    p.add_argument("--label", action="append", help="default: every label found")
    p.add_argument("--out", default=Path("output/gemini-no-vision"), type=Path)
    p.set_defaults(func=cmd_assemble)

    p = sub.add_parser("compare", help="how far two labels differ, page by page")
    p.add_argument("a", help="a label, or base / suggester for the inputs")
    p.add_argument("b")
    p.add_argument("--pages")
    p.add_argument("--top", type=int, default=15, help="how many divergent pages to list")
    p.add_argument("--out", default=Path("output/gemini-no-vision"), type=Path)
    p.set_defaults(func=cmd_compare)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
