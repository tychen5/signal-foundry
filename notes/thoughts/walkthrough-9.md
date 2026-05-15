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