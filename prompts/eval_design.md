# Evaluation Design Prompts

## Philosophy
Eval sets are designed BEFORE implementation (eval-first development).
Edge cases are intentionally stressed to expose failure modes early.

## Task 1 Eval Scenarios
- Clean Python project (should pass lint + tests)
- Monorepo with mixed languages
- Project with known CVEs in dependencies
- Repo with failing tests (should report accurately)
- Empty repo (graceful error)
- Very large repo (timeout handling)

## Task 2 Eval Dimensions
- Domain: e-commerce, news, Wikipedia, Google, form sites
- Complexity: single-step → multi-step → requires scrolling → pagination
- Failure injection: dynamic selectors, slow loading, pop-ups
- Edge: SPA, iframe, shadow DOM, mobile viewport

## Task 3 Eval Coverage
- Modern large-cap (Apple, MSFT — clean HTML)
- Small-cap (messier formatting)
- Old filings (pre-2005 plain text)
- Heavy incorporated by reference (Part III)
- Industry diversity (tech, finance, energy, healthcare)
- Edge: "Not Applicable", "Reserved" items

## LLM-as-Judge Rubric
```
Rate the extraction quality on these dimensions (1-5):
1. Completeness: Are all 16 items accounted for?
2. Accuracy: Do char_ranges match actual content?
3. Status correctness: Are incorporated/NA/reserved correctly identified?
4. Content quality: Is extracted text clean (no HTML artifacts)?
5. Boundary precision: Are item boundaries at the right positions?
```
