# sane-diff
#
#   make init BASE=base.txt SUGGESTER=suggester.txt IMAGE=image.pdf
#   make prep-images                 # page images, kept until clean-up
#   make align-pages                 # complete page markers (SOURCE=suggester)
#   make prep-diffs                  # again whenever the texts change
#   make fix-gaps                    # close the big gaps, then prep-diffs again
#   make resolve                     # Claude, per item, with the page image
#   make resolve-claude-no-vision    # Claude, per item, without it
#   make resolve-gemini-no-vision    # Gemini API, whole pages, without it
#   make review-items                # or review-items-summary, and the same
#                                    # for the no-vision run
#   make report                      # after settling verdicts in review;
#                                    # VISION=no for the no-vision run
#   make clean-up                    # delete the page images
#   make renumber FILE=corrected.txt OFFSET=151
#                                    # page markers + OFFSET, at the very end
#
# Every target takes PAGES=3-5 to work on just those pages.
# prep-images takes PDF_OFFSET=-2 when printed page 3 is the PDF's first
# page, but only if the page markers already give printed page numbers. If
# they count PDF pages from 1, leave PDF_OFFSET out and renumber the markers
# at the end with make renumber (see README). Later image extraction reuses
# the offset prep-images recorded.
# resolve-claude-no-vision takes LANGUAGE=Latin for texts not in Sanskrit;
# the other two runs use their original prompts, which name Sanskrit.
# Every resolve* run takes WORKERS=10 to change how many pages run at once:
# Claude sub-agents in flight (default 25) or Gemini calls (default 20).

PYTHON  ?= python3
PAGES   ?=
PDF_OFFSET ?= 0
BACKEND ?= claude
UNIT    ?= item
VISION  ?= yes
MODEL   ?= 2.5-flash
# Empty means the default in scripts/common.py (Sanskrit).
LANGUAGE ?=
# Empty means each run's default: 25 in agents/dispatcher.md, 20 in merge.py.
WORKERS ?=

RUN   := $(BACKEND)-$(if $(filter no,$(VISION)),no-vision,vision)
COMBO := $(BACKEND)-$(UNIT)-$(VISION)
BUILT := claude-item-yes claude-item-no gemini-page-no
pages_flag  = $(if $(PAGES),--pages $(PAGES))
pages_words = $(if $(PAGES), Only pages $(PAGES).)
lang_words  = $(if $(LANGUAGE), The texts are in $(LANGUAGE).)
workers_flag  = $(if $(WORKERS),--workers $(WORKERS))
workers_words = $(if $(WORKERS), Keep up to $(WORKERS) sub-agents in flight at a time.)

.PHONY: init prep-images align-pages prep-diffs fix-gaps resolve resolve-claude-no-vision \
        resolve-gemini-no-vision report review-items review-items-summary review-items-no-vision \
        review-items-no-vision-summary clean-up renumber

init:
	$(if $(BASE),,$(error BASE= is required))
	$(if $(SUGGESTER),,$(error SUGGESTER= is required))
	$(PYTHON) scripts/init.py --base "$(BASE)" --suggester "$(SUGGESTER)" $(if $(IMAGE),--image "$(IMAGE)")

prep-images:
	$(PYTHON) scripts/images.py prep --pdf-offset $(PDF_OFFSET) $(pages_flag)

# align-pages: complete page markers, in a Claude session that checks the
# flagged pages against their images and talks the result through. SOURCE is
# base, suggester, or a path to a text with the complete set; TARGET defaults
# to the other input (both, for a path). Writes tmp/align/; input/ changes
# only when you say so in the session.
SOURCE ?= suggester
TARGET ?=
align-pages:
	claude "Align the page markers following agents/align-pages.md, with source $(SOURCE)$(if $(TARGET), and target $(TARGET))."

prep-diffs:
	$(PYTHON) scripts/prep.py $(pages_flag)
	$(PYTHON) scripts/pending.py --run $(RUN) $(pages_flag)

# fix-gaps: close the big gaps (passages one text lacks, lines the OCR
# repeated), in a Claude session that runs scribe and a settler agent per
# page and talks the result through. Writes tmp/gaps/; input/ changes only
# when you say so in the session. SCRIBE_PROFILE is scribe's profile for
# the edition.
SCRIBE_PROFILE ?= deva_print
fix-gaps:
	claude "Close the big gaps between the two texts following agents/fix-gaps.md, with scribe profile $(SCRIBE_PROFILE). Use a workflow.$(pages_words)"

# resolve runs whichever of the combinations below BACKEND, UNIT and VISION
# name. Each run writes its report itself: a Claude run inside its Claude
# session, as its prompt tells it to, and the Gemini run as its last step.
resolve:
	$(if $(filter $(COMBO),$(BUILT)),,$(error BACKEND=$(BACKEND) UNIT=$(UNIT) VISION=$(VISION) is not built))
	@$(MAKE) --no-print-directory resolve-$(COMBO)

resolve-claude-no-vision:
	@$(MAKE) --no-print-directory resolve VISION=no

resolve-gemini-no-vision:
	@$(MAKE) --no-print-directory resolve BACKEND=gemini UNIT=page VISION=no

resolve-claude-item-yes:
	$(PYTHON) scripts/images.py extract
	claude "Adjudicate the pending pages using subagents, following agents/dispatcher.md, for the run claude-vision. Use a workflow.$(pages_words)$(workers_words) When the run is done, even with failed pages, run make report."

resolve-claude-item-no:
	claude "Adjudicate the pending pages using subagents, following agents/dispatcher.md, for the run claude-no-vision. Use a workflow.$(lang_words)$(pages_words)$(workers_words) When the run is done, even with failed pages, run make report VISION=no."

resolve-gemini-page-no:
	$(PYTHON) scripts/merge.py prep $(pages_flag)
	-$(PYTHON) scripts/merge.py gemini --model $(MODEL) $(pages_flag) $(workers_flag)
	@$(MAKE) --no-print-directory report BACKEND=gemini UNIT=page VISION=no

# report writes a run's output/<run>/ from every page done so far. Each
# resolve run ends with it; run it again after settling verdicts in review.
# The Gemini run reports even if some pages failed, so what did finish is
# written.
report:
ifeq ($(UNIT),page)
	$(PYTHON) scripts/merge.py assemble --label gemini-$(MODEL) --out output/$(RUN)
	$(PYTHON) scripts/merge.py cost
else
	$(PYTHON) scripts/apply.py --run $(RUN)
	$(PYTHON) scripts/report.py --run $(RUN)
endif

# Per-item review of the two Claude runs. The Gemini run rewrites whole
# pages, so it has no per-item verdicts to review; read it in meld.
# The walks extract any page image that is missing (after clean-up, say).
review-items:
	$(PYTHON) scripts/images.py extract
	$(PYTHON) scripts/review.py --run claude-vision $(pages_flag)

review-items-summary:
	$(PYTHON) scripts/review.py --run claude-vision --summary $(pages_flag)

review-items-no-vision:
	$(PYTHON) scripts/images.py extract
	$(PYTHON) scripts/review.py --run claude-no-vision $(pages_flag)

review-items-no-vision-summary:
	$(PYTHON) scripts/review.py --run claude-no-vision --summary $(pages_flag)

# clean-up deletes the page images, the bulk of tmp/, and the crops agents
# made. Run it when you are done with the text.
clean-up:
	$(PYTHON) scripts/images.py clean

# renumber adds OFFSET to every page marker in FILE, writing
# <name>.renumbered<ext> beside it, for texts whose markers count PDF pages
# from 1. OFFSET is the opposite sign of the PDF_OFFSET prep would have taken.
renumber:
	$(if $(FILE),,$(error FILE= is required))
	$(if $(OFFSET),,$(error OFFSET= is required))
	$(PYTHON) scripts/renumber.py "$(FILE)" --offset $(OFFSET)
