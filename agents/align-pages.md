# align-pages

You are running the first step of getting the two texts in `input/` to line
up: giving one of them (or both) a complete set of page markers, taken from
a source whose markers are complete. The placing is done by a script. Your
job is to check its result against the page images and talk it through with
the user. You change nothing in `input/` unless the user tells you to.

## Steps

1. Read `input/notes_markers.md` if it exists. It is the user's notes for
   this text: which side's markers to trust, known misnumberings, pages
   missing from one side, and so on. Where it contradicts this file, it
   wins.
2. Run the script with the arguments you were given:
   `python3 scripts/align.py --source <source> [--target <target>]`.
   It writes `tmp/align/<role>.txt` for each target and
   `tmp/align/report.txt`.
3. Read `tmp/align/report.txt`. It starts with a summary per target, then
   lists every page, worst first. Pages that agree with an old marker are
   fine and need no look.
4. If the report says `LOST`, stop there: the transfer lost its place,
   usually because one text lacks a passage the other has. Tell the user
   where (the report names the pages), and that the gap has to be closed
   first, by fix-gaps or by hand. Do not check images for the pages after
   the lost point; every marker there is unreliable.
5. Otherwise look at each flagged page (moved, differs, a low score, a
   marker the target lacked) in its image, `tmp/pages/NNNN/page.jpg`, NNNN
   being the page number, zero-padded to four digits. Check that the new
   marker sits where the printed page really begins: the report shows the
   text after the new marker, and after the old one if there was one;
   compare that with the first line printed on the page. Look at the page
   before as well when the break is in doubt. If there is no image for a
   page, say so and judge from the texts.
   With more than 20 flagged pages, look at the 20 worst and say how many
   you left.
6. Report to the user, briefly and plainly:
   - what the run did: how many markers it placed, how many agree with the
     old ones, how many it moved or renumbered;
   - the flagged pages, grouped by what happened (the old markers were
     misnumbered, a marker was missing, the transfer was unsure but right,
     the transfer looks wrong), each with the page numbers and one line of
     evidence from the image;
   - anything that looks wrong, with what you think the right placement
     is.
   Then stop and wait. The user decides what happens next.

## What the user may ask next

- **Take the result.** Copy `tmp/align/<role>.txt` over `input/<role>.txt`
  for each target, only when the user says so, and only those targets.
- **Run again with both texts as targets** (`--target both`), when the
  source's own markers look wrong in places, or with another source.
- **Fix a marker by hand** in `tmp/align/<role>.txt`. Change only the
  marker line, never the text around it, and keep the spacing: a marker
  with no blank line around it means prose running on across the page
  break, and that has to survive.

Never edit `input/` on your own initiative, and never change anything but
marker lines.
