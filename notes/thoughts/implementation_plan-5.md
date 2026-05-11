# Phase 10 — Remaining TODO Verification & Implementation

Complete all unchecked Phase 10 items from `progress_notes.md`, verify each is 100% implemented, and fix any gaps.

## Current State

- **351 tests pass**, 7 skipped (live-LLM-gated), **0 lint errors**
- Backend auto-router (`auto_router.py`, 949 lines) is fully implemented with PEPS loop, empty-query support, include/exclude hints, budget caps
- Frontend (`task1.html`, 1138 lines) has auto/manual mode, NL query input, hint chips, SSE streaming, iteration timeline
- LLM validation (`llm_validation.py`) has shape check, provider inference, key presence check
- LLM errors (`llm_errors.py`) has 10 categories, HTTP status extraction, stage attribution, `LLMStageError` class
- Config (`config.py`) has `get_model_info` supporting free-text model IDs with heuristic + hint routing
- All 3 task routers validate models upfront via `_validate_llm_model_or_400`

## Phase 10 Items Analysis

### Item 10.1 — Task 1 Auto-Router NL Query Feature
**Status: ✅ ALREADY IMPLEMENTED**

Verified in code:
- `AutoRouterRequest.natural_language_query` is `default=""` (optional) ✅
- `auto_router.py` has `has_query = bool(query_stripped)` branching — empty query skips the LLM plan call, uses `_derive_default_plan()` ✅
- `_derive_default_plan()` respects include/exclude hints deterministically ✅
- `_is_release_intent_explicit()` treats include-hint chip as equivalent to NL release intent ✅
- `_llm_decide` substitutes `overall_intent` as proxy when query is empty ✅
- `_llm_synthesize` generates a chip-based paraphrase when query is empty ✅
- `auto_result.query` keeps raw user input ✅
- Frontend (`task1.html`) has NL query textarea, hint chips, mode toggle, run-preview, NL examples ✅
- Prompts (`v1_auto_router_plan.txt`, `v1_auto_router_decide.txt`, `v1_auto_router_synthesize.txt`) exist ✅
- Backend endpoint `POST /api/v1/skills/auto/run` and `POST /api/v1/skills/auto/stream` exist ✅

### Item 10.2 — API Audit: LLM Key/Model Validation + Error Propagation
**Status: ✅ ALREADY IMPLEMENTED**

Verified:
- `validate_model_selection()` does shape check, provider resolution, key presence check ✅
- All 3 task routers call `_validate_llm_model_or_400()` as the first step ✅
- Free-text model IDs supported via `get_model_info()` prefix heuristic + provider hint ✅
- `LLMStageError` carries stage/provider/model_id through the pipeline ✅
- `classify_with_stage()` extracts HTTP status codes from provider error strings ✅
- `ModelSelectionRequest` has `provider` hint field ✅
- All 3 task FEs send `model.provider` when set ✅
- Error envelopes include `stage`, `provider`, `model_id`, `status_code`, `status_label`, `category`, `user_message`, `suggested_action`, `raw_error` ✅

### Item 10.3 — Task 2 Vision Default for OpenRouter + cnyes Example
**Status: ⚠️ NEEDS FIXES**

Issues found:
1. **Vision checkbox default**: The `use-vision` checkbox is always `unchecked` regardless of whether the user has an OpenRouter key. Should default to checked when an OpenRouter model is selected (those are the vision-capable ones).
2. **cnyes example**: Line 83 in task2.html still sends `'前往鉅亨網並擷取台股加權指數最新點位'` which may hit CAPTCHA. Need to replace with a CAPTCHA-free alternative to fetch the Taiwan weighted index.

### Item 10.4 — Full UI/UX Audit + Quick Launchpad Redesign
**Status: ⚠️ NEEDS FIXES**

Issues found:
1. **Quick launchpad** on index.html (lines 94-103) is just a flat list of links — duplicates footer links (Health, Metrics, Models at lines 107-110). Per the user's request, this should be redesigned to show rich status cards with brief descriptions, not just buttons, and should not duplicate the footer.
2. **Hero stats** show hardcoded `289 unit tests` but we now have `351` tests.
3. **Eval cases** show `89` but actual counts may differ — need to verify.
4. **Index page** `nvidia-key` input doesn't persist to `sessionStorage` in the task1 template's `hydrateSharedControls()`.

## Proposed Changes

### Fix 1: Task 2 Vision Default + cnyes Example
#### [MODIFY] [task2.html](file:///mnt/c/Users/leoqa/Documents/signal-foundry/templates/task2.html)
- Add JS logic to auto-check `use-vision` when user has an OpenRouter key entered AND the selected model is an OpenRouter model (vision-capable)
- Replace cnyes example with TWSE (Taiwan Stock Exchange) direct URL or another CAPTCHA-free finance source

### Fix 2: Index Page Quick Launchpad Redesign + Stats Update  
#### [MODIFY] [index.html](file:///mnt/c/Users/leoqa/Documents/signal-foundry/templates/index.html)
- Redesign quick-actions as rich mini-cards with icons, descriptions, and status
- Remove duplicate links from footer (keep only essential system links)
- Update hero stats to reflect current test count (351) and eval cases
- Persist nvidia-key in sessionStorage consistently

### Fix 3: Task 1 template nvidia-key persistence
#### [MODIFY] [task1.html](file:///mnt/c/Users/leoqa/Documents/signal-foundry/templates/task1.html)
- Add nvidia-key sessionStorage persistence in `hydrateSharedControls()`

## Verification Plan

### Automated Tests
- `pytest tests/ -q` — all pass, no regressions
- `ruff check src/ tests/` — all pass

### Manual Verification  
- Start dev server, visit `/`, `/task1`, `/task2`, `/task3` — verify all UI flows
- Check vision checkbox auto-enables for OpenRouter models on task2
- Check cnyes replacement demo works without CAPTCHA
- Verify quick launchpad redesign renders correctly
