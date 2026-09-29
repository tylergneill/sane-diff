# sane-diff
#
#   make init BASE=base.txt SUGGESTER=suggester.txt IMAGE=image.pdf
#   make prep-pending
#   make resolve                     # Claude, per item, with the page image
#   make resolve-claude-no-vision    # Claude, per item, without it
#   make resolve-gemini-no-vision    # Gemini API, whole pages, without it
#   make review-items                # or review-items-summary, and the same
#                                    # for the no-vision run
#
# Every target takes PAGES=3-5 to work on just those pages.
# prep-pending takes PDF_OFFSET=-2 when printed page 3 is the PDF's first
# page; later image extraction reuses the offset it recorded.
# resolve-claude-no-vision takes LANGUAGE=Latin for texts not in Sanskrit;
# the other two runs use their original prompts, which name Sanskrit.

PYTHON  ?= python3
PAGES   ?=
PDF_OFFSET ?= 0
BACKEND ?= claude
UNIT    ?= item
VISION  ?= yes
MODEL   ?= 2.5-flash
# Empty means the default in scripts/common.py (Sanskrit).
LANGUAGE ?=

RUN   := $(BACKEND)-$(if $(filter no,$(VISION)),no-vision,vision)
COMBO := $(BACKEND)-$(UNIT)-$(VISION)
BUILT := claude-item-yes claude-item-no gemini-page-no
pages_flag  = $(if $(PAGES),--pages $(PAGES))
pages_words = $(if $(PAGES), Only pages $(PAGES).)
lang_words  = $(if $(LANGUAGE), The texts are in $(LANGUAGE).)

.PHONY: init prep-pending resolve resolve-claude-no-vision resolve-gemini-no-vision \
        report review-items review-items-summary review-items-no-vision \
        review-items-no-vision-summary

init:
	$(if $(BASE),,$(error BASE= is required))
	$(if $(SUGGESTER),,$(error SUGGESTER= is required))
	$(PYTHON) scripts/init.py --base "$(BASE)" --suggester "$(SUGGESTER)" $(if $(IMAGE),--image "$(IMAGE)")

prep-pending:
	$(PYTHON) scripts/prep.py --pdf-offset $(PDF_OFFSET) $(pages_flag)
	$(PYTHON) scripts/pending.py --run $(RUN) $(pages_flag)

# resolve runs whichever of the combinations below BACKEND, UNIT and VISION
# name, then the report. The report runs even if the run was interrupted, so
# what did finish is reported.
resolve:
	$(if $(filter $(COMBO),$(BUILT)),,$(error BACKEND=$(BACKEND) UNIT=$(UNIT) VISION=$(VISION) is not built))
	-@$(MAKE) --no-print-directory resolve-$(COMBO)
	@$(MAKE) --no-print-directory report

resolve-claude-no-vision:
	@$(MAKE) --no-print-directory resolve VISION=no

resolve-gemini-no-vision:
	@$(MAKE) --no-print-directory resolve BACKEND=gemini UNIT=page VISION=no

resolve-claude-item-yes:
	$(PYTHON) scripts/images.py extract
	claude "Adjudicate the pending pages using subagents, following agents/dispatcher.md, for the run claude-vision.$(pages_words)"

resolve-claude-item-no:
	claude "Adjudicate the pending pages using subagents, following agents/dispatcher.md, for the run claude-no-vision.$(lang_words)$(pages_words)"

resolve-gemini-page-no:
	$(PYTHON) scripts/merge.py prep $(pages_flag)
	$(PYTHON) scripts/merge.py gemini --model $(MODEL) $(pages_flag)

# What a finished run leaves behind, in output/<run>/. Page images are
# removed afterwards; review brings them back.
report:
ifeq ($(UNIT),page)
	$(PYTHON) scripts/merge.py assemble --label gemini-$(MODEL) --out output/$(RUN)
	$(PYTHON) scripts/merge.py cost
else
	$(PYTHON) scripts/apply.py --run $(RUN)
	$(PYTHON) scripts/report.py --run $(RUN)
endif
	$(PYTHON) scripts/images.py clean

# Per-item review of the two Claude runs. The Gemini run rewrites whole
# pages, so it has no per-item verdicts to review; read it in meld.
review-items:
	$(PYTHON) scripts/images.py extract
	$(PYTHON) scripts/review.py --run claude-vision $(pages_flag)

review-items-summary:
	$(PYTHON) scripts/images.py extract
	$(PYTHON) scripts/review.py --run claude-vision --summary $(pages_flag)

review-items-no-vision:
	$(PYTHON) scripts/images.py extract
	$(PYTHON) scripts/review.py --run claude-no-vision $(pages_flag)

review-items-no-vision-summary:
	$(PYTHON) scripts/images.py extract
	$(PYTHON) scripts/review.py --run claude-no-vision --summary $(pages_flag)
