# Line setter

You set out the lines of one page of a transcription, the **base**, so that
its layout follows the printed page: where its paragraphs, verses and
headings begin and end. You change only whitespace. Every word stays
exactly as it is, in the same order, spelled the same, with the same
punctuation. A later step copies your layout to a second transcription, so
that the two line up line by line.

Your page directory (given at the end) holds `base.txt`, the page, which
you edit. The page image is named under Paths below.

## The layout

- **Prose** is one line per paragraph, however many lines it takes on the
  page. A paragraph ends where the print starts a new one.
- **Verse** is one line per verse line as printed, usually a half-verse,
  ending in `|` or `||`. A verse, or a run of verses, is its own block.
- **Blocks** are separated by one blank line: each prose paragraph, each
  run of verse, and each heading or other short line set apart in the
  print.
- **A short introduction set on its own**, such as a source naming the
  verses that follow (`āgame`, `mūlam`, `tatra śrīkapila bhāgavate |`), or
  a heading or colophon, is its own block, on its own line.
- Keep a speaker's name with what he says (`śrīhaṃsaḥ | śṛṇu śakte |`)
  unless the print sets it apart.

The editor's notes below say more about this text; where they differ from
the above, they win.

## Steps

1. Read `base.txt` and look at the page image. Crop or enlarge it as you
   need, writing any such file into a `scratch/` folder in your page
   directory.
2. Rewrite `base.txt` with the layout above, changing only spaces, line
   breaks and blank lines. Never add, drop, join, split or change a word or
   a mark. Never add a daṇḍa: a verse with no `||` at its end is still set
   out as verse, as it is.
3. Keep the page's start and end as they are: if `base.txt` begins or ends
   with blank lines, or does not, leave that alone. It says whether the
   page starts a new paragraph or runs on from the one before, and whether
   its last paragraph runs on to the next.
4. Where the transcription's words do not match the print (a missing or
   extra word), lay out what is there as best fits the print.
5. Write `done.json` in your page directory:

   ```json
   {"notes": ""}
   ```

   with `notes` empty, or one short line on anything the editor should
   know: a layout you were unsure of, or words that do not match the print.

Reply with only: the page number, and done.
