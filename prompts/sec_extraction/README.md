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

### v3 (Planned) — Few-Shot with Examples
- **Approach**: Add 3-4 concrete examples of boundary snippets with correct JSON output
- **Expected**: Reduce JSON parsing failures from ~8% to <2%

## Files
- `v2_boundary_refine.txt` — Current boundary refinement system prompt
- `v2_missing_item_detect.txt` — Current missing item detection template
- `v2_reflexive_validate.txt` — Current reflexive validation prompt (Stage 3 LLM-as-judge)
