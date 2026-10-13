base:
- sarvam ai ocr
- has pre-filtered out headers and footers, which should be kept as-is
- prone to sometimes normalizing according to a priori language understanding (e.g. degeminating semivowels after r), which should be rejected

suggester:
- google cloud vision ocr
- tends to have spurious whitespace between words, which should be rejected
- more prone to nonsense

general:
- spacing between numbers and (double) daṇḍas is preferred to no space
- any remaining page numbers or marginal line numbers can be discarded
