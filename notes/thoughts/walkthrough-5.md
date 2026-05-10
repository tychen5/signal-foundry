目前主要改動包含：


/health、/metrics、/api/v1/models 現在瀏覽器開啟會顯示友善 HTML dashboard，API clients 仍拿 JSON： src/main.py, system.html

Task 2 UI 修正 execution trace 顯示 [object Object] 的問題，改成 action/target/confidence/error 可讀展示；example chips 也會自動填入 URL： task2.html

Task 3 UI 修正 direct filing URL payload：file_url → filing_url，加上 use_vision toggle、stages 顯示、IBM/TSMC edge-case examples： task3.html

Dashboard 加 reviewer launchpad，Task pages 共享 session-level model/API key controls： index.html

新增 OpenRouter vision on/off benchmark runner 與 live benchmark 結果： run_vision_benchmark.py, vision result

README 已補上目前 Task 2 33-case set、Task 3 18/18、UI tweaks、vision benchmark 結果與解讀： README.md


Vision benchmark slice 結果已寫入 README：


Gemini：vision on/off 幾乎無差，AOM/text 已足夠。

Claude：Task2 image-caption 從 partial, 15 steps, $0.782, 118.9s 改成 success, 3 steps, $0.0487, 27.5s。

GPT-5.5：從 5 steps, $0.0675, 93.4s 改成 4 steps, $0.0353, 49.8s。

Task3 Apple 2005：三個模型 vision on/off 都是 18/23 items, $0, 0 LLM calls，符合 Stage 2 未觸發時 vision no-op 的成本紀律。


Verification：


ruff check src/ tests/ evals/run_vision_benchmark.py passed

Focused tests passed: TestHealthAndSystem, Task2 regressions + vision helper tests, selected Task3 regression

HTML negotiation smoke passed: /health returns HTML for browser Accept; /api/v1/models returns JSON for JSON Accept

Live OpenRouter benchmark slice completed and result committed under evals/vision_results/


目前完成項目包含：


Task 2：確認 v3 actor/verifier prompt 已啟用；強化 use_vision snapshot 流程、元素截圖、full-page/sparse-AOM 判斷與 screenshot timeout 測試。

Task 3：新增/修正 force_llm eval/API path；vision renderer 改成更安全的 Playwright lifecycle，避免 Chromium 啟動或 cleanup 卡住；LLM refinement 現在會保留 rule-parser 已知 item number，避免 LLM 把 Item 1 錯改成 Item 1A 後造成 cascade miss。

Eval/benchmark：Task 2/3 eval runner 都有 timeout guard；benchmark runner 可用 --force-llm-task3 真的觸發 Task 3 LLM/vision path。

README：補上 live eval 指令、Task 3 force_llm schema、vision engineering decisions、Task 2/3 vision on/off benchmark 結果與 reviewer demo 建議。


新的 Task 3 forced-LLM OpenRouter vision benchmark 已產出：


vision_benchmark_20260507T084355Z.md

vision_benchmark_20260507T084355Z.json


重點結果：


Gemini 3.1 Pro：vision off/on 都 23/23 items；cost 約 $0.00204 / $0.00206

Claude Opus 4.7：vision off/on 都 23/23 items；cost 約 $0.02424 / $0.02537

GPT-5.5：vision off/on 都 23/23 items；cost 約 $0.00816 / $0.00828


驗證已跑過：


ruff check src/ tests/ evals/run_vision_benchmark.py evals/task2/run_eval.py evals/task3/run_eval.py

pytest tests/ -q → 219 passed, 7 skipped

real Chromium screenshot/render focused tests passed

opt-in live eval quick slice passed：RUN_LIVE_EVALS=1 pytest tests/test_live_evals.py -q → 2 passed

git diff --check passed



  Eval set expansion (+11 cases, 270 tests pass):                                                                         
  Eval set expansion (+11 cases, 270 tests pass):
  - T3 (+3): Realty Income REIT · Ares Capital BDC · Coinbase crypto — all verified live on Zeabur, $0 cost, ~1.2-1.7s
  - T2 (+4): DuckDuckGo · npm.js · Wayback Machine · HN threaded comments
  - T1 (+3): polyglot non-Python repo · idempotent replay (cache_hit live-confirmed) · adversarial security-scan repo

  Harness guards (each with regression tests):
  - T2 stuck-loop guard breaking out of 3-identical-action-on-same-URL loops
  - Per-request budget cap with BudgetExceededError (T3 wired) — spec's "$0.50/filing" now enforced, not just logged
  - NVIDIA-key contextvar plumbing through set_user_keys() + 4 contextvar tests
  - 3 new LLM error categories (context_length, model_not_found, content_filter)
  - Multilingual hedge phrases (zh-CN, JP, CF interstitial English) and CMP/Turnstile/geo-block URL markers
  - Strict-mode + element-detached healer paths (new SELECTOR_AMBIGUOUS root cause)

  Parser fixes:
  - T3 normalizer windows widened (5 kB → 50 kB / 10 kB → 80 kB) for SGML preambles
  - T3 reserved-status alt phrasings ("Removed and Reserved.", "Item is reserved.")
  - T3 accession shape check (catches typos before SEC roundtrip; verified on live deploy)
  - T1 GitHub URL parser (tree/blob/pull/issues + scheme-less + SSH form)
  - T2 verifier word-boundary regex (kills "incomplete" silent-success false-positive)
  - SSE queue.put_nowait() so disconnected consumers don't wedge the engine
  - 5 more CMPs + DE/ES/FR/KR cookie banner patterns

  Live deploy verified — accession shape rejection works end-to-end, new T3 cases extract correctly via SSE stream.


    Key changes made:                                                                                                                                                                                                                                                                                                                                
                                                                                                                                                                                                                                                                                                                                                   
  Eval set corrections (3 wrong CIKs fixed):                                                                                                                                                                                                                                                                                                       
  - t3_enron_2000_complex_segments: Wrong CIK 0000101830 (Sprint LLC) → correct 0001024401 (ENRON CORP/OR/) + accession 0001024401-01-500010
  - t3_worldcom_2001_telco_pre_fraud: Wrong accession 0000928385-02-001285 (DIGEX subsidiary) → correct 0001005477-02-001226                                                                                                                                                                                                                       
  - t3_lehman_2007_investment_bank: Wrong CIK 0000806548 (not found) → correct 0000806085 + accession 0001104659-08-005476  
                                                                                                                                                                                                                                                                                                                                                   
  Two infrastructure bugs fixed:                                                                                                                                                                                                                                                                                                                   
  1. fetcher.py: Raised ValueError before checking older submissions pages — blocked Lehman/Enron whose 10-Ks predate the 1,000-filing recent window                                                                                                                                                                                               
  2. llm_refiner.py: _detect_missing_items was silently skipped when all found boundaries were high-confidence (even if only 3 items found) — now fires whenever items_found < 10                                                                                                                                                                  
                                                                                                                                                                                 
  New v4 prompt (prompts/sec_extraction/v4_boundary_refine.txt): handles combined items ("ITEMS 1 AND 2"), SPAC N/A detection, early EDGAR ASCII format, going-concern false-positive prevention, confidence calibration guide.                                                                                                                    
                                                                                                                                                                                                                                                                                                                                                   
  Results: 35 cases covering modern mega-caps, legacy 1994/2000 filings, pre-bankruptcy era (Enron/WorldCom/Lehman), foreign issuers (20-F), SPVs, amendments — all passing at $0 cost on the rule-only path.  



    Vision benchmark results (saved to evals/vision_results/vision_benchmark_20260508T102614Z.md):                                                                                                                                                                                                                                                   
  - kimi-k2.6 + vision=True: 5/5 success, $0, 23.8s avg — best on this slice
  - kimi-k2.6 + vision=False: 3/5 success, $0.022, 131.4s                                                                                                                                                                                                                                                                                          
  - Asset-Backed Trust + Kingsoft Cloud: 0 → 16-20 items extracted with vision on
  - Gemini 3.1 Pro regressed slightly with vision (4/5 → 3/5) — recorded honestly                                                                                                                                                                                                                                                                  
                                                                                                                                                                                                                                                                                                                                                   
  Critical bugs fixed:                                                                                                                                                                                                                                                                                                                             
  1. T1 streaming visibility — panel now shows immediately on Run Skill click                                                                                                                                                                                                                                                                      
  2. T2 Wikipedia hang — added 90s frontend watchdog + retry-on-transient on backend                                                                                                                                                                                                                                                               
  3. T2 Yahoo Finance 429 — replaced with Google Finance demo                       
  4. T1 encode/httpx 422 — default_branch now honoured (master vs main)                                                                                                                                                                                                                                                                            
  5. T1 LangSmith 404 — replaced with copy-trace-id chip                                                                                                                                                                                                                                                                                           
  6. T3 Microsoft / Abbott 404 — real accessions pinned                                                                                                                                                                                                                                                                                            
  7. T2 Wikipedia parse failure — robust JSON extractor                                                                                                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                                                                                                   
  LLM strengthening (Phase 9):                                                                                                                                                                                                                                                                                                                     
  - extract_json_object / extract_json_array — handle ```json fences, smart quotes, balanced braces, truncated streams (13 tests)                                                                                                                                                                                                                  
  - get_llm(json_mode=True) with safe-list — applies to 5 plain models, skips thinking-mode glm-5.1 / deepseek-v4-pro (6 tests)                                                                                                                                                                                                                    
  - 180s LLM request timeout default                                                                                                                                                                                                                                                                                                               
  - Single retry-on-transient (timeout/5xx/429) on all 3 T2 LLM call sites                                                                                                                                                                                                                                                                         
  - T3 vision: heading-emphasis renderer that bolds ITEM/PART headings in JPEG snapshots                                                                                                                                                                                                                                                           
                                                                                                                                                                                                                                                                                                                                                   
  BYOK + UX:                                                                                                                                                                                                                                                                                                                                       
  - Homepage now accepts OpenRouter + NVIDIA + LangSmith keys (sessionStorage-only)                                                                                                                                                                                                                                                                
  - Live key-config hint banner — colour-coded chip warns when selected model needs missing key                                                                                                                                                                                                                                                    
  - All 3 task SSE streams embed final result event (no more redundant POST)                   
                                                                                                                                                                                                                                                                                                                                                   
  Test count: 270 → 289 (+19) all passing. Deployment at https://signal-foundry.zeabur.app/ healthy on all routes. progress_notes.md Phase 7 + Phase 9 marked [x].    


    Confirmed deployed and working at https://signal-foundry.zeabur.app/:                                                                                                                                                                                                                                                                            
  - All 4 endpoints (/, /task1, /task2, /task3) returning HTTP 200                                                                                                                                                                                                                                                                                 
  - Latest max-steps options (5/10/20-default/40) live on Task 2                                                                                                                                                                                                                                                                                   
  - All 7 models in the dropdown                                                                                                                                                                                                                                                                                                                   
  - 289 unit tests in the codebase                                                                                                                                                                                                                                                                                                                 
                                                                                                                                                                                                                                                                                                                                                   
  ---                                                                                                                                                                                                                                                                                                                                              
  T2 Wikipedia infobox stuck-loop — full root-cause analysis & fix:                                                                                                                                                                                                                                                                                
                                                                                                                                                                                                                                                                                                                                                   
  ┌─────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐ 
  │                  Issue                  │                                     Root cause                                      │                                                                                                    Fix                                                                                                     │   
  ├─────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤ 
  │ Agent kept scrolling looking for        │ Wikipedia infobox is a right-side sidebar widget, not below-fold content            │ v3_actor.txt rule 9b: explicit guidance to use extract not scroll for infoboxes; demo button task description rewritten to instruct extract-first flow                                                     │
  │ population                              │                                                                                     │                                                                                                                                                                                                            │
  ├─────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤   
  │ LLM couldn't see infobox in context     │ Context window only had 2 500 char a11y + 800 char visible_text — infobox content   │ Bumped to 5 000 a11y / 3 500 visible_text; observer raw limits 4 K → 8 K (a11y) and 2 K → 6 K (text)                                                                                                       │   
  │                                         │ was past truncation                                                                 │                                                                                                                                                                                                            │   
  ├─────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤   
  │ EXTRACT action did nothing              │ Was a no-op that just re-ran observe() with same truncated state                    │ Real _execute_extract() runs JS in-page: pulls .infobox innerText (≤4 KB), or any <table> matching keywords, or label-with-number kv pairs. New StepResult.extracted_data field carries the structured     │
  │                                         │                                                                                     │ snippet to the next step's [EXTRACTED: ...] log.                                                                                                                                                           │   
  ├─────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Repeated scrolls weren't detected as    │ Scroll always returned success even when scrollY didn't change                      │ _execute_scroll now compares before/after scrollY and returns scroll_no_change error so the healer can switch strategy at attempt #2 instead of waiting for the 3-identical guard at attempt #4            │
  │ no-op                                   │                                                                                     │                                                                                                                                                                                                            │   
  ├─────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Default max_steps was too low for       │ UI default was 10, backend was 15                                                   │ UI default 20, new 40 option for complex multi-page flows; backend default also 20                                                                                                                         │   
  │ complex flows                           │                                                                                     │                                                                                                                                                                                                            │   
  └─────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                                                                                                                                                                                                                                                                                                                   
  Last-step LLM call hangs / empty output:                                                                                                                                                                                                                                                                                                         
  - LLM_REQUEST_TIMEOUT_S=180 (was 90) — first-token latency tax on NIM / thinking-mode no longer false-fires
  - Single-retry-on-transient on all 3 T2 LLM call sites (planning, deciding, verifying) — Gemini 3.1 Pro thinking-mode hiccup at the last step now gets one retry before bailing                                                                                                                                                                  
  - Frontend SSE watchdog: 90s no-event abort with clear "stream ended unexpectedly" status (was: spinner forever)                                                               
  - T2 stream emits agent_complete even when nothing was extracted, so the UI never stays on RUNNING                                                                                                                                                                                                                                               
                                                                                                                                                                                                                                                                                                                                                   
  Phase 7 + Phase 9 marked [x] in notes/progress/progress_notes.md. Phase 8 items 1, 2, 4 done; item 3 (deeper Task Description analysis) noted ongoing.   