# Phase 6/7 Completion + Comprehensive Enhancement Plan

> Full-scope plan for: AGENTS.md/CLAUDE.md consolidation, live eval hardening, vision strengthening (Task 2 + Task 3), LLM module optimization, UI/UX polish, and README benchmark documentation.

## User Review Required

> [!IMPORTANT]
> This plan involves ~20+ file modifications across source, tests, evals, prompts, templates, and documentation. The scope is large but each part is independently verifiable. Please review whether any sections should be deferred or reprioritized.

> [!WARNING]
> Live eval runs (Parts 2, 7) require API keys and Playwright. Running the full vision benchmark across 3 models × 6+ cases will cost ~$2-5 on OpenRouter. Tests that hit SEC EDGAR are rate-limited to ≤10 req/sec.

## Open Questions

1. **Benchmark budget**: The vision on/off benchmark across all 3 OpenRouter models with expanded Task 2 (6+ vision cases) + Task 3 (4+ LLM-trigger cases) will cost ~$3-5. Should I run a subset or the full matrix?
2. **AGENTS.md vs CLAUDE.md split**: I propose CLAUDE.md = project-specific context (tech stack, structure, harness reference, red lines) and AGENTS.md = behavioral guidelines + per-task engineering notes. Does this split work, or would you prefer a different boundary?
3. **New v3 prompts**: I plan to create v3 versions of the browser agent actor/verifier prompts with enhanced vision instructions. Should I keep v2 as the active fallback or deprecate it?

---

## Proposed Changes

### Part 1: AGENTS.md / CLAUDE.md Consolidation

**Problem**: Both files currently contain an identical "CLAUDE.md behavioral guidelines" section (§1-4: Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution). The harness engineering quick reference in CLAUDE.md partially duplicates per-task notes in AGENTS.md.

#### [MODIFY] [CLAUDE.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/CLAUDE.md)
- **Keep**: Project architecture reference, tech stack, build/run, project structure, conventions, red lines, harness engineering quick reference
- **Remove**: The duplicate "# CLAUDE.md" section at line 90-155 (behavioral guidelines) — these already live in AGENTS.md
- **Add**: Cross-reference to AGENTS.md for per-task engineering notes and behavioral guidelines
- **Update**: Harness quick reference with latest vision/tracing/benchmark features

#### [MODIFY] [AGENTS.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/AGENTS.md)
- **Keep**: All per-task engineering notes (Task 1/2/3), harness engineering highlights, behavioral guidelines
- **Remove**: Duplicate build/test/lint commands (already in CLAUDE.md)
- **Update**: Per-task notes with latest vision multi-snapshot approach, expanded eval coverage, new LLM touch points
- **Add**: Testing standards that reference real live eval runs (not just smoke tests)

---

### Part 2: Real Live Eval Tests + Playwright Stability

**Problem**: Tests are mostly unit/schema smoke tests. Need to ensure Playwright screenshot tests don't hang, and eval runners actually exercise live paths.

#### [MODIFY] [tests/test_task2_browser.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/tests/test_task2_browser.py)
- Add `TestPlaywrightScreenshot` class with `pytest.mark.asyncio` tests that:
  - Launch headless Chromium, navigate to `data:text/html,...`, take screenshot, verify JPEG conversion doesn't hang
  - Test `capture_screenshot_b64()` with a timeout guard (8s max)
  - Test `render_text_to_jpeg_b64()` with timeout guard  
  - Use `asyncio.wait_for()` to prevent Playwright hangs
- Add `TestVisionMultiSnapshot` class:
  - Test `make_multimodal_message_history()` with multiple screenshots
  - Test `render_multi_snapshots()` produces 3 tiers
- Mark Playwright-heavy tests with `@pytest.mark.playwright` so they can be run separately

#### [MODIFY] [tests/test_task3_sec.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/tests/test_task3_sec.py)
- Add `TestVisionRendering` class:
  - Test `render_multi_snapshots()` with SEC-style text produces 3-tier snapshots
  - Test boundary highlight `mark_position` parameter
  - Test graceful degradation when Playwright unavailable
- Add live eval gated tests (`@pytest.mark.skipif(not os.environ.get("RUN_LIVE_EVAL"))`) that exercise the full pipeline against a cached/small filing

#### [MODIFY] [evals/task2/run_eval.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/evals/task2/run_eval.py)
- Add `--timeout` flag per case (default 120s) with `asyncio.wait_for()` wrapper
- Add `--vision` flag to run with `use_vision=True` for vision-capable models

#### [MODIFY] [evals/task3/run_eval.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/evals/task3/run_eval.py)
- Add `--force-llm` flag to force Stage 2 LLM refinement even for high-confidence filings
- Add `--vision` flag
- Add timeout guard around pipeline calls

---

### Part 3: Task 2 Vision Strengthening

**Goal**: Make `use_vision=true` demonstrably improve browser agent performance across more scenarios.

#### [MODIFY] [src/task2_browser/vision.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task2_browser/vision.py)
- Add `capture_full_page_screenshot_b64()` for below-the-fold content detection
- Add `capture_element_screenshot_b64(page, selector)` for focused element vision (e.g., a specific chart or table)
- Add `annotate_screenshot_with_markers()` — overlay numbered markers on interactive elements so the LLM can reference them by number (inspired by SeeAct / WebVoyager approaches)
- Increase `_MAX_VISION_HISTORY` consideration: allow configurable via env `T2_VISION_HISTORY_MAX`

#### [MODIFY] [src/task2_browser/agent.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task2_browser/agent.py)
- In the planned-steps phase (Phase 2), also capture screenshots when `use_vision=True` — currently only the reactive loop (Phase 3) captures them
- Add a `_detect_visual_elements()` helper that uses the screenshot to identify canvas/SVG/image elements that AOM can't describe
- Pass vision history to the healer's LLM diagnosis path too (currently only planner/verifier get screenshots)

#### [MODIFY] [src/task2_browser/planner.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task2_browser/planner.py)
- In `plan_task()`, when vision is available, include a system instruction about visual element identification
- In `_parse_verification()`, add confidence boost when vision confirms text-based verification

#### [NEW] [prompts/browser_agent/v3_actor.txt](file:///mnt/c/Users/leoqa/Documents/signal-foundry/prompts/browser_agent/v3_actor.txt)
Enhanced actor prompt with:
- Explicit instructions for chart/canvas/image interpretation when screenshots are present
- Color-state detection (red/green indicators, active/inactive tabs)
- Below-fold content awareness (scroll if key info might be below viewport)
- Multi-screenshot temporal reasoning ("the button was grey in step 3, now it's blue → click succeeded")

#### [NEW] [prompts/browser_agent/v3_verifier.txt](file:///mnt/c/Users/leoqa/Documents/signal-foundry/prompts/browser_agent/v3_verifier.txt)
Enhanced verifier prompt with:
- Screenshot-to-text cross-validation: when answer says "price is $150" but screenshot shows "$148", flag discrepancy
- Visual completion signals (success toast, green checkmark, loaded chart)
- Error detection from visual cues (red borders, error icons)

#### [MODIFY] [evals/task2/eval_set.json](file:///mnt/c/Users/leoqa/Documents/signal-foundry/evals/task2/eval_set.json)
Add 4+ new vision-benefiting cases:
- `t2_vision_color_indicator` — website with red/green status indicators; vision needed to read color state
- `t2_vision_canvas_data` — D3/chart.js rendered data points; AOM has no text
- `t2_vision_map_location` — Google Maps or similar; extract location from visual map
- `t2_vision_pdf_viewer` — embedded PDF in iframe; text extraction needs vision
- `t2_vision_captcha_detect` — page with visual CAPTCHA; vision helps classify and report inability

---

### Part 4: Task 3 Vision Enhancement for SEC Filing Variants

**Goal**: Make vision substantively help with format-variant filings: old plain-text, inconsistent HTML, ALL-CAPS headers, "incorporated by reference" with proxy mentions far into content.

#### [MODIFY] [src/task3_sec/vision.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/vision.py)
- Add `render_full_page_snapshot()` — render larger sections of filing (up to ±3000 chars) for layout analysis
- Add `render_comparison_snapshots()` — side-by-side render of two candidate boundaries for LLM to compare
- Add `render_with_html_structure()` — preserve original HTML formatting (bold, tables, indentation) instead of plain text rendering, so the LLM can see the actual visual styling that signals item boundaries
- Add browser reuse: keep a single browser instance open for multiple renders per filing instead of launching/closing per snapshot (fix potential Playwright hang from rapid launch/close cycles)

#### [MODIFY] [src/task3_sec/llm_refiner.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/llm_refiner.py)
- Pass the original HTML (not just plain text) to the vision renderer so typography information is preserved
- Add a `_classify_ambiguous_status()` LLM call for items where rule-based status detection has low confidence (e.g., content mentions both proxy reference and substantive text — which is it?)
- Add `_validate_boundary_with_vision()` — post-refinement verification using snapshot comparison

#### [NEW] [prompts/sec_extraction/v3_boundary_refine.txt](file:///mnt/c/Users/leoqa/Documents/signal-foundry/prompts/sec_extraction/v3_boundary_refine.txt)
If not already present, create/update with:
- Multi-snapshot analysis instructions (header zone / local / neighbor)
- Typography-based boundary signals (bold, ALL-CAPS, indentation changes, whitespace gaps)
- Status classification from visual context ("incorporated by reference" vs "extracted" vs "N/A")
- Explicit handling of edge cases: Part III proxy references, old plain-text formatting, Reserved items

#### [MODIFY] [evals/task3/eval_set.json](file:///mnt/c/Users/leoqa/Documents/signal-foundry/evals/task3/eval_set.json)
Add 4+ new LLM-trigger / vision-benefit cases:
- `t3_oldformat_plaintext_pre2000` — a very old plain-text filing (pre-HTML era) where rule parser confidence will be low, forcing LLM refinement
- `t3_ambiguous_proxy_mix` — filing where some Part III items have BOTH proxy reference AND substantive text
- `t3_unusual_heading_format` — filing with non-standard heading styles (e.g., "ITEM ONE" instead of "Item 1")
- `t3_very_large_filing` — a filing >5MB to test performance and vision rendering limits
- `t3_multi_document_sgml` — raw SGML submission with multiple documents where primary 10-K needs extraction

#### [MODIFY] [tests/test_task3_sec.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/tests/test_task3_sec.py)
- Add tests for new vision rendering functions
- Add regression test for ambiguous proxy/extracted classification

---

### Part 5: LLM Module/Prompt Optimization Across All Tasks

#### Task 1 Enhancements

#### [MODIFY] [src/task1_cicd/skill_registry.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task1_cicd/skill_registry.py)
- Add `_suggest_related_skills()` — when a skill runs, suggest complementary skills (e.g., after lint-and-test → "also consider dependency-audit")
- Improve fuzzy matching: add Levenshtein distance fallback when token overlap is inconclusive
- Add confidence calibration: track historical match accuracy per tier

#### [MODIFY] [src/task1_cicd/skill_engine.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task1_cicd/skill_engine.py)
- Add `execution_recommendations` field to result: post-run suggestions based on findings
- Add severity categorization for lint/security issues (critical/high/medium/low)

#### Task 2 Enhancements

#### [MODIFY] [src/task2_browser/healer.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task2_browser/healer.py)
- Add `login_wall` and `paywall` as explicit root cause classes (currently folded into `captcha_detected`)
- Add `content_loading` root cause for SPAs that haven't hydrated
- Pass screenshot to healer LLM diagnosis when vision is available
- Add `_suggest_alternative_url()` — when blocked by anti-bot, suggest alternative sources (e.g., Google cache, archive.org)

#### [MODIFY] [src/task2_browser/executor.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task2_browser/executor.py)
- Add `_handle_iframe_content()` — detect and switch to iframes for content extraction
- Add `_scroll_to_load_lazy_content()` — explicit lazy-loading handler for infinite-scroll pages
- Improve `_execute_select()` for complex dropdown menus (multi-select, searchable)

#### [MODIFY] [src/task2_browser/observer.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task2_browser/observer.py)
- Add `detect_page_type()` — classify page as SPA/MPA/static/error/login
- Add `extract_structured_data()` — detect and extract tables, lists, key-value pairs from page
- Add `detect_loading_state()` — check for spinner/skeleton/loading indicators

#### Task 3 Enhancements

#### [MODIFY] [src/task3_sec/rule_parser.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/rule_parser.py)
- Add pattern for "ITEM ONE" / "ITEM TWO" spelled-out numbers (some old filings)
- Add `_detect_section_break()` — use whitespace/divider patterns to validate boundaries
- Improve ToC deduplication with a smarter positional heuristic

#### [MODIFY] [src/task3_sec/normalizer.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/normalizer.py)
- Add `_preserve_formatting_hints()` — extract bold/italic/heading HTML tags as inline markers before stripping to plain text
- Improve handling of table-of-contents with page numbers in various formats

#### [MODIFY] [src/task3_sec/validator.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/validator.py)
- Add `_cross_validate_statuses()` — verify that incorporated-by-reference items in the same Part are consistent
- Add `_check_content_length_anomalies()` — flag items with suspiciously short/long content relative to peers

---

### Part 6: UI/UX Improvements

#### [MODIFY] [templates/task2.html](file:///mnt/c/Users/leoqa/Documents/signal-foundry/templates/task2.html)
- Add vision toggle with visual indicator (camera icon)
- Show vision history thumbnails in execution trace (small preview images)
- Add step-by-step timeline visualization instead of flat list
- Add collapsible sections for long accessibility trees
- Add "Copy as JSON" button for result data
- Show model capabilities (vision/text-only) next to model selector

#### [MODIFY] [templates/task3.html](file:///mnt/c/Users/leoqa/Documents/signal-foundry/templates/task3.html)
- Add visual diff between rule-based and LLM-refined boundaries
- Show stage progression as a pipeline diagram (stage 1 → 2 → 3 → 4)
- Add confidence heat-map for item boundaries
- Add item-level expandable cards with content preview
- Show incorporated-by-reference resolution chain

#### [MODIFY] [templates/index.html](file:///mnt/c/Users/leoqa/Documents/signal-foundry/templates/index.html)
- Add live status indicators for each task endpoint
- Add recent execution history (last 5 requests per task)
- Add model comparison quick-launch

#### [MODIFY] [static/style.css](file:///mnt/c/Users/leoqa/Documents/signal-foundry/static/style.css)
- Add timeline/progress-bar components
- Add thumbnail image preview styles
- Add confidence badge coloring (green/yellow/red)
- Add responsive improvements for mobile review

---

### Part 7: README Benchmark Documentation + Vision Benchmark Expansion

#### [MODIFY] [evals/run_vision_benchmark.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/evals/run_vision_benchmark.py)
- Expand default Task 2 cases: add the new vision-specific cases from Part 3
- Expand default Task 3 cases: add the new LLM-trigger cases from Part 4
- Add per-case answer quality scoring (not just status)
- Add Markdown report with side-by-side vision on/off comparison tables

#### [MODIFY] [README.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/README.md)
- Update test count from 193 to new count
- Update Task 2 case count from 33 to new count  
- Update Task 3 case count from 18 to new count
- Add expanded vision benchmark results table with all 3 models × all vision cases
- Add cost/quality analysis paragraph interpreting the benchmark
- Document new LLM features (related skill suggestions, severity categorization, etc.)
- Update architecture diagram if new components added
- Add section on "Vision Engineering Decisions" explaining the multi-snapshot approach

---

## Verification Plan

### Automated Tests
```bash
# 1. All existing tests still pass
pytest tests/ -v --cov=src

# 2. New Playwright tests pass without hanging (with timeout)
pytest tests/ -v -k "playwright or vision" --timeout=30

# 3. Lint clean
ruff check src/ tests/ evals/

# 4. Live eval (gated, needs API keys)
RUN_LIVE_EVAL=1 pytest tests/ -v -k "live_eval" --timeout=120
```

### Manual Verification
- Browser-test the UI changes at `http://localhost:8080/task2` and `/task3`
- Verify vision toggle works on Task 2 and Task 3 UI
- Run `python -m evals.run_vision_benchmark --task both` and verify results are generated
- Spot-check that new eval cases produce reasonable results
- Verify AGENTS.md and CLAUDE.md have no duplicate content
- Confirm README benchmarks match actual results

### Execution Order

1. **Part 1** — AGENTS.md / CLAUDE.md consolidation (smallest, foundational)
2. **Part 2** — Playwright stability + test infrastructure
3. **Part 3** — Task 2 vision strengthening  
4. **Part 4** — Task 3 vision enhancement
5. **Part 5** — LLM module optimizations (all 3 tasks)
6. **Part 6** — UI/UX improvements
7. **Part 7** — Benchmark runs + README updates (depends on 3-6)
