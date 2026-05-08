# SEC 10-K Extraction Prompts — Version History

## Overview
Prompts used by the LLM refiner (Stage 2) and validator (Stage 3) for boundary detection,
missing item detection, and quality validation.

## Iteration Log

### v1 (Initial) — Naive Full-Document Approach
- **Approach**: Send entire normalized text to LLM asking it to identify all item boundaries
- **Problem**: Context length explosion (10-K filings are 100K+ chars), extreme cost (~$2-5/filing),
  and hallucination on boundary positions (LLM would invent char_range values not in source)
- **Decision**: Abandoned in favor of hybrid approach

### v2 (Current) — Context-Window Approach
- **Approach**: Only send ±500 char windows around uncertain boundaries
- **Change from v1**: 95% reduction in token usage. LLM only validates/refines, never segments from scratch.
- **Impact**: Cost dropped from ~$2.50 to ~$0.05 per filing for LLM-refined items

### v3 (Active) — Vision-Aware with Few-Shot Examples
- **Approach**: Added screenshot usage instructions for 3-tier snapshot (header/local/neighbor zones). Added status detection decision tree. Added explicit ToC vs heading discrimination rules.
- **Impact**: JSON parse failures dropped to <2%. Vision snapshots used by boundary refiner when `use_vision=True`.

### v4 (Active) — Edge-Case Hardening
- **Approach**: Added handling for combined items ("ITEMS 1 AND 2"), SPAC/blank-check N/A detection, early EDGAR ASCII format patterns, going-concern false-positive prevention, and confidence calibration guide.
- **Why**: New eval cases covering Enron 2000, WorldCom 2001, Lehman 2007, Sears 2017 (pre-bankruptcy filings with complex segments and going-concern language) required improved prompt guidance. SPAC/blank-check scenarios needed explicit N/A classification rules.
- **Impact**: Better confidence calibration on ambiguous cases; going-concern language no longer triggers false `not_applicable` status.

## Files
- `v2_boundary_refine.txt` — Legacy boundary refinement system prompt (archived)
- `v2_missing_item_detect.txt` — Missing item detection template
- `v2_reflexive_validate.txt` — Reflexive validation prompt (Stage 3 LLM-as-judge)
- `v3_boundary_refine.txt` — Vision-aware boundary refinement with few-shot examples
- `v4_boundary_refine.txt` — Edge-case hardened prompt (combined items, SPAC, early format, going concern)
