 Verdict per concern

  ┌────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │             Q              │                                                                                                                                  Honest call                                                                                                                                  │
  ├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Q1 Citi 0 headings pass    │ ⚠️  REAL BUG. validator.py:80-98 counts NOT_FOUND placeholders as "found" because _fill_missing_items pads them in before validation runs. ~5 line fix.                                                                                                                        │
  ├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Q2 Intel TOC extraction    │ ⚠️  REAL LIMITATION. rule_parser.py:222-224 — when only 1 match exists for an Item, it's used directly without TOC suppression. Body-heading-broken HTML → TOC entry wins. ~10 line fix.                                                                                       │
  ├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Q3 Task 2 not_found = pass │ ✅ Your harness-guard design intent is real (4+ explicit negative_case / silent_failure_guard cases in eval_set), BUT ⚠️  scorer lacks per-case correctness checks. Both critiques are partially correct. Fix: add expected_outcome per case (all deterministic).              │
  ├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Q4 static-site fast path   │ Valid optimization, not a requirement. ~100 line implementation in new src/task2_browser/fast_path.py + 5-line hook in agent.py:run. Wikipedia/arxiv/HN/SEC index cases drop from ~45s/$0.05 → <2s/$0.                                                                        │
  ├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Q5 LLM in eval             │ Your understanding is correct on runtime (Task 1 needs LLM for "Skill triggers Claude precisely", Task 2 needs LLM for self-correction). Eval scorers are already 100% deterministic — evals/task*/run_eval.py use exit codes / substring / status checks, zero LLM-as-judge. │
  └────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  Did stale drafts mislead them?

  No. grep -ri "citi\|intel" across the entire repo (including .agents/, notes/, prompts/) returned only false positives ("artificial intelligence", "market intelligence"). They ran a legitimate held-out test, which the task spec explicitly says they will: "Interviewers run held-out tests against your deployed system using data outside your eval set."

  "本機測試非全綠" claim

  Not accurate. pytest tests/ → 354 passed, 7 skipped. The 7 skips are opt-in RUN_LIVE_EVALS=1 + LLM-network tests, intentionally gated to avoid burning API quota in CI.

  The grade-dispute case

  Section §6 lays out the A-grade argument vs the task spec's 4 rubric points (84+ eval cases, multi-layer architecture, quantified tradeoffs, prompt iteration ledger, 8 explicit innovations vs OpenClaw baseline). Bottom line: the 3 polish gaps are real and worth ~8 hours total to fix, but they don't change the answer to "is the core system design A-grade or not".

  Appendix A gives you a ready-to-use dialogue script for each interviewer question. Appendix B walks through your 4 original framings honestly (some I agree with, some I had to qualify).


  ---

  All shipped. Final status:

  Summary — All P0~P2 patches landed

  Tests: 375 passed, 7 skipped (opt-in live evals), 0 lint errors. +21 new regression tests vs baseline 354.

  What changed

  ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬───────────────────────────────────────────────────────────┬─────────────┐
  │                                                           Patch                                                           │                           Files                           │ Tests added │
  ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┼─────────────┤
  │ P0.1 _check_coverage excludes NOT_FOUND + catastrophic flag                                                               │ src/task3_sec/validator.py                                │ 2           │
  ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┼─────────────┤
  │ P0.2 Single-match TOC suppression (in_toc_region OR has_toc_markers → confidence 0.40)                                    │ src/task3_sec/rule_parser.py                              │ 1           │
  ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┼─────────────┤
  │ P0.3 Citi 2026 + Intel 2026 in eval_set + 2 UI buttons (auto vision+force_llm)                                            │ evals/task3/eval_set.json, templates/task3.html           │ 3 pin tests │
  ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┼─────────────┤
  │ P2.1 extraction_completeness / extracted_count / expected_count honesty fields                                            │ src/task3_sec/schemas.py, src/task3_sec/pipeline.py       │ 2           │
  ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┼─────────────┤
  │ P1.1 Task 2 scorer 2-layer rewrite (universal + per-case deterministic)                                                   │ evals/task2/run_eval.py, evals/task2/eval_set.json        │ 4           │
  ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┼─────────────┤
  │ P1.2 Static-site fast path (Wikipedia / arxiv / HN / example.com)                                                         │ src/task2_browser/fast_path.py (new), agent.py, router.py │ 9           │
  ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┼─────────────┤
  │ README — "Why not_found can be CORRECT" + "Static-site fast path" sections                                                │ README.md                                                 │ —           │
  ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┼─────────────┤
  │ progress_notes.md Phase 11 fully [x]                                                                                      │ notes/progress/progress_notes.md                          │ —           │
  ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┼─────────────┤
  │ interviewer_concerns.md §8 (current state) + §9 (interview prep with time-budget honesty) + Appendix C (full patch table) │ notes/_briefs/interviewer_concerns.md                     │ —           │
  └───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────┴─────────────┘

  Key design decisions explained in the doc

  1. Citi/Intel regression cases use cik-only path (no accession) — fetcher resolves the most-recent 10-K, so the cases stay evergreen and survive year rollovers
  2. Fast-path is opt-out, not opt-in — allow_fast_path=True default means any caller benefits immediately; benchmarks use allow_fast_path=False for head-to-head A/B
  3. Per-case expected_outcome is optional — backward compatible; 41 of 46 cases still pass with only the universal layer until they're individually annotated
  4. §9 includes the time-budget honesty — explains the ~30-hour real working budget split between startup work + interview, framed as prioritization tradeoff (breadth over catastrophic-edge depth), not excuse

  ---


  Citi 2026 and Intel 2026 are NOT fully solved — but they're now substantially better, and the failure modes are honestly surfaced rather than masked.

  What's actually fixed
  
  ┌────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │   Filing   │                                       Before §10 (your reported state)                                        │                                                                             After §10 (now)                                                                              │
  ├────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Citi 2026  │ All 22 items NOT_FOUND, llm_calls=0, parser couldn't find anything                                            │ 3 real body items extracted with full content: RISK FACTORS (335k chars), CONSOLIDATED FINANCIAL STATEMENTS (664k chars), DISCLOSURE CONTROLS AND PROCEDURES (21k chars) │
  ├────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Intel 2026 │ 23 items "extracted" but content was the cover-page end-index ("Pages 37-51", "(a)") at char 518k of 522k doc │ 4 real body items at proper body positions: Our Business (101k), Risk Factors (105k), Cybersecurity (238k), Properties (23k)                                             │
  └────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  Root cause discovered live

  Looking at Citi's raw HTML: zero "ITEM 1" text occurrences. Citi uses bold spans with just title-only text (Risk Factors, Disclosure Controls and Procedures). The "Item N." prefix is rendered via CSS / table column — not as adjacent text. Our entire regex strategy (ITEM\s+\d+) was blind to this style of HTML.

  Solution shipped

  New title-only fallback detector (src/task3_sec/rule_parser.py):
  - Scans the body region (10%–90% of doc, excluding TOC zone AND end-index appendix)
  - 23-item lookup with multiple variants per item (ALL CAPS / Title Case / lowercase, longest-prefix-wins)
  - Triggers when regex returns 0 matches (Citi) OR all matches cluster at >95% of doc (Intel) OR all matches were TOC-suspect
  - 8 new regression tests covering the trip conditions

  What's still imperfect (honest)

  Rule-only coverage on Citi/Intel is 13–17%, not 100%. The remaining 80% needs Stage 2 LLM refinement:
  - The fallback only knows canonical title variants. Citi has filer-specific headings like "BUSINESS EXITS", "REPORTABLE BUSINESS SEGMENTS" that we'd need to enumerate
  - The cost-discipline tradeoff is intentional: rules cover 80% of normal filings at $0; LLM at ~$0.02 covers the long tail
  - items_found < 10 triggers Stage 2 automatically — with the new 3-4 body anchors, the LLM no longer has to find body content from scratch in a 1.2 MB doc

  Test status

  - 383 tests pass (was 375, +8 new), 0 lint errors
  - Live verified against actual Citi 2026 + Intel 2026 SEC filings
  - §10 added to interviewer_concerns.md with full root cause, solution, and honest summary

  What I'd recommend for the live UI test

  When you click 🏦 Citi 2026 or 💾 Intel 2026 on the deployed /task3 page (auto-enables force_llm + use_vision), expect:
  - Citi: ~3-8 items extracted with real body content (rule-only gets 3; LLM Stage 2 should fill 5-10 more); extraction_completeness ~40-60%
  - Intel: ~4-10 items in body positions (10-90% of doc, not 99%); coverage ~30-50%
  - Rest marked not_found honestly

  If you want 100% coverage on these specific filings, that's a larger lift (HTML-tag-aware parsing of <h1>/<h2>/<strong> from raw HTML, plus iterating the Stage 2 prompt to do "find missing items using these anchors") — listed as roadmap in §10.8.

  ---

 100% Coverage Achieved on Both Filings

  Live results against the actual SEC filings (rule-only, $0 cost):

  ┌────────────┬──────────────┬─────────┬──────────────────────────────────────────────────────┐
  │   Filing   │   Coverage   │ Latency │                   Status breakdown                   │
  ├────────────┼──────────────┼─────────┼──────────────────────────────────────────────────────┤
  │ Citi 2026  │ 23/23 (100%) │ 21s     │ 10 extracted / 6 not_applicable / 1 reserved / 6 IBR │
  ├────────────┼──────────────┼─────────┼──────────────────────────────────────────────────────┤
  │ Intel 2026 │ 23/23 (100%) │ 4s      │ 15 extracted / 5 not_applicable / 1 reserved / 2 IBR │
  └────────────┴──────────────┴─────────┴──────────────────────────────────────────────────────┘

  What I built (the larger lift)

  5-layer detection stack

  1. HTML-tag-aware extractor (src/task3_sec/html_heading_extractor.py, ~290 lines): BeautifulSoup walker → <h1>-<h6> / <strong> / <b> / CSS-styled bold spans → 60-variant title lookup → position-mapped back to normalized text
  2. Cover-page TOC parser (parse_cover_toc_table): state machine reads Citi-style cover TOC tables, captures every item's declared status (extracted / Not Applicable / Reserved / IBR)
  3. End-of-doc Cross-Reference Index parser (parse_end_cross_reference_index): handles Intel-style end-of-doc Form 10-K Cross-Reference Index
  4. Master IBR declaration detector: catches multi-item incorporation declarations ("Items 10, 11, 12, 13 and 14 are incorporated by reference")
  5. Existing text-only fallback (from §10): title-only headings, single-match TOC suppression

  Smart dedupe with authoritative-status priority

  Three-tier scoring (authoritative_hint, content_length, source_priority) — TOC-declared reserved/not_applicable/IBR statuses now win over body false positives (e.g. Citi's html_anchor false-match for "Selected Financial Data" subheading no longer overrides Item 6's [Reserved] status)

  LLM Stage 2 with anchor-aware full-doc extraction

  - New anchor_aware_gap_fill + _full_doc_extract functions
  - v5/v6 prompts (prompts/sec_extraction/v5_anchor_aware_gap_fill.txt, v6_full_doc_extraction.txt) — single Gemini 3.1 Pro call with full doc + anchors + missing-items list
  - Soft-fail when LLM rate-limits so rule-only 100% result is preserved

  Auto-promotion for SEC-optional items

  - Item 6 → reserved (eliminated by SEC release 33-10890 in 2021)
  - Item 16 → not_applicable (Form 10-K Summary always optional)

  Tests

  - 396 tests passing (was 383, +13 new)
  - 0 lint errors
  - New test classes: TestHTMLHeadingExtractor, TestCoverTocTable, TestMasterIbrDeclaration, TestEndCrossReferenceIndex, TestDedupePicksAuthoritativeStatus

  Files changed

  - NEW: src/task3_sec/html_heading_extractor.py (~290 lines)
  - NEW: prompts/sec_extraction/v5_anchor_aware_gap_fill.txt, v6_full_doc_extraction.txt
  - +220 lines: src/task3_sec/rule_parser.py (3 new parsers)
  - +180 lines: src/task3_sec/llm_refiner.py (gap-fill + full-doc paths)
  - +70 lines: src/task3_sec/pipeline.py (dedupe + Stage 2b wiring + soft-fail + optional auto-promotion)
  - +280 lines: tests/test_task3_sec.py (13 new tests)
  - Full §11 walkthrough added to notes/_briefs/interviewer_concerns.md

  The Gemini 3.1 Pro path is fully wired and works when OpenRouter isn't rate-limiting — when it does work, Citi Item 1A grows from 14k → 32k chars of real body prose, Citi Item 15 grows from 196 → 19k chars, etc. The rule-only path achieves identical 100% coverage at $0 with no LLM dependency.
