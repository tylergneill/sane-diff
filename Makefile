# sane-diff
#
#   make init BASE=base.txt SUGGESTER=suggester.txt IMAGE=image.pdf
#   make prep-pending
#   make resolve                     # Claude, per item, with the page image
#   make resolve-claude-no-vision    # Claude, per item, without it
#   make resolve-gemini-no-vision    # Gemini API, whole pages, without it
#   make review                      # or review-summary
#
# Every target takes PAGES=3-5 to work on just those pages.
# resolve-claude-no-vision takes LANGUAGE=Latin for texts not in Sanskrit;
# the other two runs use their original prompts, which name Sanskrit.

PYTHON  ?= python3
PAGES   ?=
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
        report review review-summary

init:
	$(if $(BASE),,$(error BASE= is required))
	$(if $(SUGGESTER),,$(error SUGGESTER= is required))
	$(PYTHON) scripts/init.py --base "$(BASE)" --suggester "$(SUGGESTER)" $(if $(IMAGE),--image "$(IMAGE)")

prep-pending:
	$(PYTHON) scripts/prep.py $(pages_flag)
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

review:
	$(PYTHON) scripts/images.py extract
	$(PYTHON) scripts/review.py --run $(RUN) $(pages_flag)

review-summary:
	$(PYTHON) scripts/images.py extract
	$(PYTHON) scripts/review.py --run $(RUN) --summary $(pages_flag)
