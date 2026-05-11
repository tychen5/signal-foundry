  Summary                                                                                                                                                                                                                                                                                                                                                       
                                                                                                                                                                                                                                                                                                                                                                
  Auto-Router for Task 1 — natural-language CI/CD orchestration via LLM-driven skill chaining. When the user asks a fuzzy question like "are there any vulnerable deps or leaked secrets?", a Router LLM autonomously plans a skill sequence, executes each via the existing 13-step engine, reflects after every result (continue / pivot / stop), and         
  synthesizes a single answer.                                                                                                                                                                                                                                                                                                                                  
                                                                                                                                                                                                                                                                                                                                                                
  What was added / changed                                                                                                                                                                                                                                                                                                                                      
                                                                                                                                                                                                                                                                                                                                                                
  ┌────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐                           
  │     Layer      │                                                                                                                                                     Change                                                                                                                                                     │                           
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                           
  │ Backend module │ src/task1_cicd/auto_router.py — PEPS loop (Plan → Execute → Postmortem → Synthesize) with hard caps (iteration cap, $0.30 budget cap, write-skill gate, exclude-hint hard block, dedup)                                                                                                                        │
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Schemas        │ AutoRouterRequest, AutoRouterStep, AutoRouterResult added to src/task1_cicd/schemas.py. The result surfaces a top-level skill_executed field for reviewer demo evidence                                                                                                                                        │                           
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                           
  │ API endpoints  │ POST /api/v1/skills/auto/run and POST /api/v1/skills/auto/stream (SSE) wired into src/task1_cicd/router.py                                                                                                                                                                                                     │                           
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                           
  │ Prompts        │ Three versioned prompts in prompts/cicd/: v1_auto_router_plan.txt, v1_auto_router_decide.txt, v1_auto_router_synthesize.txt                                                                                                                                                                                    │
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                           
  │ Frontend       │ templates/task1.html rewritten with Auto/Manual toggle, NL query textarea + suggestion chips, mutually-exclusive include/exclude hint chips, plan strip, live iteration timeline (per-step status, decision pill, summary), final synthesis box, SSE live-trace, demo-highlight strip surfacing skill_executed │
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                           
  │ Tests          │ 37 new tests covering the plan sanitiser invariants, helper functions, schema validation, prompt files, end-to-end loop with mocked LLM (continue / pivot / iteration cap / skill failure / include-hint reorder), and the auto API. Suite is 326 green with 0 lint errors                                     │
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤                           
  │ Docs           │ README "What's new (Phase 10)" + 90-line Auto-Router section with reviewer demo curl examples and future-extension notes; prompts/cicd/README.md ledger fully updated                                                                                                                                          │
  └────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘                           
                                                            
  Defensive layers (the agentic-doesn't-mean-unsafe table)                                                                                                                                                                                                                                                                                                      
  │ Schemas        │ AutoRouterRequest, AutoRouterStep, AutoRouterResult added to src/task1_cicd/schemas.py. The result surfaces a top-level skill_executed field for reviewer demo evidence                                                                                                                                        │
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ API endpoints  │ POST /api/v1/skills/auto/run and POST /api/v1/skills/auto/stream (SSE) wired into src/task1_cicd/router.py                                                                                                                                                                                                     │
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Prompts        │ Three versioned prompts in prompts/cicd/: v1_auto_router_plan.txt, v1_auto_router_decide.txt, v1_auto_router_synthesize.txt                                                                                                                                                                                    │
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Frontend       │ templates/task1.html rewritten with Auto/Manual toggle, NL query textarea + suggestion chips, mutually-exclusive include/exclude hint chips, plan strip, live iteration timeline (per-step status, decision pill, summary), final synthesis box, SSE live-trace, demo-highlight strip surfacing skill_executed │
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Tests          │ 37 new tests covering the plan sanitiser invariants, helper functions, schema validation, prompt files, end-to-end loop with mocked LLM (continue / pivot / iteration cap / skill failure / include-hint reorder), and the auto API. Suite is 326 green with 0 lint errors                                     │
  ├────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Docs           │ README "What's new (Phase 10)" + 90-line Auto-Router section with reviewer demo curl examples and future-extension notes; prompts/cicd/README.md ledger fully updated                                                                                                                                          │
  └────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  Defensive layers (the agentic-doesn't-mean-unsafe table)

  - Plan sanitiser: drops unknown skills, dedupes, hard-blocks excluded skills, refuses build-and-release unless the NL query carries release intent
  - Iteration cap (default 4, max 6) and budget cap ($0.30/req) — terminate even if the LLM keeps saying "continue"
  - Idempotency: same skill never executes twice in one loop; reuses the existing SHA cache key, so repeated runs against the same commit hit cache for $0
  - Empty-plan fallback: [dependency-audit, security-scan] defaults if the LLM returns garbage

  Demo verification at /task1

  Reviewer can paste a query like "please check if there are any vulnerable dependencies or leaked credentials" and watch the SSE stream render: plan_done → iteration_start (dependency-audit) → iteration_skill_done → iteration_decision (continue) → iteration_start (security-scan) → iteration_skill_done → iteration_decision (stop) →
  synthesize_done → result. The skill_executed: ["dependency-audit", "security-scan"] field appears in both the on-screen demo-highlight strip and the raw JSON.

  ---

    Summary                                                                                                                                                                                                                                                                                                                                    
                                                                                                                                                                                                                                                                                                                                               
  Made the NL query fully optional end-to-end. The user can now run the auto-router by just toggling include/exclude chips (or even leaving everything blank — falls back to a safe default health-check pair).                                                                                                                              
                                                                                                                                                                                                                                                                                                                                               
  Changes                                                                                                                                                                                                                                                                                                                                      
                                                                                                                                                                                                                                                                                                                                               
  ┌────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐   
  │         Layer          │                                                                                                                                                 What changed                                                                                                                                                  │   
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Schema (schemas.py)    │ Dropped min_length=3 and ... on natural_language_query — defaults to "".                                                                                                                                                                                                                                      │ 
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤   
  │ Pipeline               │ Added _derive_default_plan() + _is_release_intent_explicit(). The main loop now branches on has_query: if empty, skips the plan LLM call entirely and uses the include chips (or the safe default pair, minus excludes) as the plan. The _llm_decide and _llm_synthesize prompts receive a synthesized intent │
  │ (auto_router.py)       │  string when the query is blank so they stay coherent.                                                                                                                                                                                                                                                        │   
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤   
  │ Release-intent gate    │ The write-capable build-and-release skill is now allowed through when the user either types release keywords in the query or ticks the build-and-release chip — the chip click counts as explicit consent. Applied uniformly in _sanitise_plan, the _llm_decide scrub, and _derive_default_plan.              │   
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤   
  │ API (router.py)        │ No endpoint changes needed — the existing /auto/run + /auto/stream now accept requests with an empty query.                                                                                                                                                                                                   │   
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤   
  │ Frontend (task1.html)  │ NL textarea relabeled "optional", helper text rewritten, ⊘ clear-query example added. Removed the validation alert. Added a live run-preview panel that mirrors the server's branching logic in real time as the user types or toggles chips ("LLM-routed", "Hint-only run (no LLM plan call)", "Default      │ 
  │                        │ run", or "⚠ Nothing to run"). The run button label updates too: 🚀 Run Auto-Router / Run selected skills / Run default health check.                                                                                                                                                                          │   
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤ 
  │ Tests                  │ Replaced test_request_rejects_short_query with three tests covering empty/missing/no-intent payloads. Added TestAutoRouterDerivedPlan (9 tests) and TestAutoRouterEmptyQueryLoop (4 e2e tests with mocked LLM stages). 14 new tests total. Suite is 133/133 green, ruff clean.                                │   
  ├────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Docs                   │ README gets a routing-modes table + 4-mode curl example block. prompts/cicd/README.md ledger explains the new "chip-only mode saves the plan LLM call" cost-discipline note.                                                                                                                                  │   
  └────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘   
                                                                                                                                                                                                                                                                                                                                             
  Reviewer demo paths now possible at /task1                                                                                                                                                                                                                                                                                                   
                                                                                                                                                                                                                                                                                                                                             
  1. Pure NL — type a fuzzy query, leave chips alone. Existing flow.                                                                                                                                                                                                                                                                           
  2. Hybrid — type a query AND tick some chips. Chips pin to the front of the LLM-derived plan.                                                                                                                                                                                                                                              
  3. Chip-only — leave query empty, tick include chips. Auto-router skips the plan LLM call and runs only the ticked skills.                                                                                                                                                                                                                   
  4. Defaults — leave everything empty. Runs dependency-audit + security-scan as a safe baseline.                                                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                                                                                               
  In every mode the response still surfaces a top-level skill_executed field for one-glance reviewer verification.   

  ---

目前重點變更如下：



已盤點並強化主要 user-facing APIs：


Task 1: /api/v1/skills/run, /stream, /auto/run, /auto/stream

Task 2: /api/v1/browser/execute, /stream

Task 3: /api/v1/sec/extract, /stream

Task 3 aux APIs /filings/{cik}、/company/{cik} 不用 LLM，所以不套 LLM key/model validation。





新增共用 LLM validation：


src/shared/llm_validation.py (line 93)

驗證 model_id 必須是 publisher/model-name

支援 free-text model IDs，不再被 MODEL_REGISTRY whitelist 擋住

支援 model.provider = "openrouter" | "nvidia" hint

upfront 檢查 OpenRouter/NVIDIA key 是否存在，缺 key 回 HTTP 400 且指出欄位





修正 provider routing：


src/config.py (line 163)

src/llm_provider.py (line 44)

get_llm() 現在吃 provider_hint / contextvar，不會未知 model 就 fallback default model。





強化 provider error propagation：


src/shared/llm_errors.py (line 57)

會抽出 401 Unauthorized, 404 Not Found, 429 Rate Limit Exceeded, 502 Bad Gateway, 503 Service Unavailable 等 status label

新增 stage-attributed envelope，例如 browser_plan, auto_router_synthesize, stage2.boundary_refine.item_7

non-stream API 放在 cost_metadata.llm_error

stream API 以 SSE error event 回傳





前端三個 task UI 已改成可輸入 free-text model ID，並新增 provider hint：


templates/task1.html (line 268)

templates/task2.html (line 112)

templates/task3.html (line 127)

UI 現在會顯示 stage / provider / model / upstream status / raw error。





README API Reference 已更新：


README.md (line 162)

補上 shared model block、validation error shape、provider failure envelope、stream endpoints、auth notes。





新增測試：


tests/test_shared.py (line 256)

tests/test_llm_errors.py (line 113)

tests/test_api.py (line 153)





Verification:


ruff check src/ tests/ passed

python -m pytest tests/ -q passed: 351 passed, 7 skipped

