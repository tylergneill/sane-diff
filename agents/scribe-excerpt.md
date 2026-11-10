# Excerpt transcription (for agents)

You are transcribing parts of one page image of a Sanskrit source,
diplomatically: exactly what the image shows. Not the whole page: only the
excerpts listed below.

Source: {source}

1. Read and follow, in this order (later files override earlier ones):
   - {markup}
   - {profile}
   - {project}
   They are written for whole pages. Leave out what applies only to a whole
   page: the `=== N ===` header line and sections. Everything else holds,
   line breaks included.
2. The page image: {image} (detail crops in the same folder: {crops}).
3. Each excerpt is given by the words just before it and just after it, in
   IAST transliteration; the page may print them in another script, and
   with small differences of spelling or spacing. Find those places on the
   image. Transcribe every line from the one holding the words before
   through the one holding the words after, both included, and write it to
   the file named, in {out_dir}/.
   Where two sets of words are given (`X  OR  Y`), they come from two
   transcriptions that differ there; use whichever you find on the page.
   "(start of page)" means start at the page's first line of text;
   "(end of page)" means go to its last.
{excerpts}
4. Work only from the image. Do NOT open any other file: no e-texts, other
   transcriptions, editions, git history, or web pages. Record what is there,
   character by character; do not correct apparent errors. Read slowly. Use
   the detail crops for anything small or crowded.
5. If you cannot find the place for an excerpt, write its file with the
   single line `%% not found: ` and what you could not find.
6. After writing each file, compare it against the image once more, line by
   line, and fix any discrepancy.

Reply with only: files written, any `{?}` items, and any excerpt you could
not place.
