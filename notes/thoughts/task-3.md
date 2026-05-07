# Phase 6/7 Execution Tracker

## Part 1: AGENTS.md / CLAUDE.md Consolidation
- [/] Rewrite CLAUDE.md — project-specific context only (remove behavioral guidelines §1-4)
- [/] Rewrite AGENTS.md — universal agent instructions + per-task notes + behavioral guidelines (remove duplicate build/test)
- [ ] Verify no duplicate content between files

## Part 2: Live Eval + Playwright Stability
- [ ] Add Playwright screenshot tests with timeout guards to test_task2_browser.py
- [ ] Add vision multi-snapshot tests
- [ ] Add live eval gated tests for Task 3
- [ ] Add --timeout/--vision flags to eval runners

## Part 3: Task 2 Vision Strengthening
- [ ] Enhance vision.py (full-page screenshots, element screenshots, annotated markers)
- [ ] Update agent.py to pass vision to healer + planned-steps phase
- [ ] Create v3_actor.txt and v3_verifier.txt prompts
- [ ] Add 4+ new vision eval cases to eval_set.json

## Part 4: Task 3 Vision Enhancement
- [ ] Enhance vision.py (HTML rendering, comparison snapshots, browser reuse)
- [ ] Update llm_refiner.py for HTML pass-through + ambiguous status classification
- [ ] Add 4+ new LLM-trigger eval cases to eval_set.json
- [ ] Add tests for new vision rendering functions

## Part 5: LLM Module Optimizations
- [ ] Task 1: Skill suggestions, severity categorization
- [ ] Task 2: Healer expansion (login_wall/paywall), iframe/lazy-load handling
- [ ] Task 3: Spelled-out heading patterns, formatting hints, cross-validation

## Part 6: UI/UX Improvements
- [ ] Task 2 template: vision toggle, timeline, thumbnails
- [ ] Task 3 template: pipeline diagram, confidence heat-map
- [ ] Dashboard template: status indicators, recent history

## Part 7: Benchmark + README
- [ ] Expand vision benchmark runner
- [ ] Update README with new counts and results
- [ ] Run full benchmark when ready
