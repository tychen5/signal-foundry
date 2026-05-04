# TODO checklist

1. []
    1. [x] 請先查看了解 @_JobDescription.md 相關background與搜尋理解公司需要的方向
        - ✅ 已完成。VICI Holdings — 金融交易公司，LLM Agent + RL核心能力，交易自動化與市場洞察。
    2. [x] 接著查看此repo將要實作的三個項目之描述與目標預期 @_TaskDescription.md
        - ✅ 已完成。三項 tasks 需求全面理解。
    3. [x] 我在@_ThoughtsDraft.md裡面撰寫了很多我目前最初步粗略的想法跟思考
        - ✅ 已完成。Deep dive research + 所有ideas整合至 architecture_design_spec.md。
    4. [x] 創建此repo所有tasks所需要的架構skelton、目錄與檔案結構等等
        - ✅ **Phase 0 完成！** 建立完整 repo skeleton：
            - `src/` 完整 package structure（config, llm_provider, main, shared/, task1_cicd/, task2_browser/, task3_sec/）
            - `src/shared/` harness engine, evaluator, cost_tracker, logger, schemas — 全部可運行
            - 3 個 task routers with skeleton API endpoints
            - Unified FastAPI app with dashboard, health, metrics, model listing
            - `static/` + `templates/` with dark-theme UI
            - `evals/` with eval sets (5 T1 + 8 T2 + 8 T3)
            - `prompts/` with versioned prompt records
            - `.env` + `.env.example` + `zbpack.json` + `Dockerfile`
            - **18 tests all passing** ✅
    5. [x] 統整所有research撰寫成完整說明文件於 @architecture_design_spec.md
        - ✅ 已完成。完整架構設計規格書涵蓋：
            - System overview + architecture diagram
            - Technology stack with rationale
            - Shared infrastructure details（harness、evaluator、cost tracker、LLM provider）
            - Task 1/2/3 各自的技術設計（pipeline、schema、strategies）
            - Evaluation strategy + metrics
            - Engineering tradeoffs table
            - Security & safety
            - Deployment config
            - Innovation differentiators (vs OpenClaw/HermesAgent)
            - Future roadmap
    6. [x] 如果有什麼東西需要權限才能安裝等
        - ✅ 已獲得所有 API keys：OpenRouter, NVIDIA, GitHub PAT, LangSmith
        - ✅ Playwright 已安裝
        - ✅ Zeabur 已連接 GitHub repo (Pro plan, 2vcpu/4GB/50GB dedicated)
    7. [x] 撰寫CLAUDE.md
        - ✅ 已完成。含 tech stack, build commands, project structure, conventions, red lines (<200 lines)
    8. [x] 撰寫AGENTS.md
        - ✅ 已完成。含 repo layout, build/test/lint commands, engineering conventions, security constraints, testing standards, verification checklist, ExecPlan reference
    9. [x] 撰寫PLANS.md
        - ✅ 已完成。ExecPlan template with steps, pre/post-conditions, rollback
    10. [x] 撰寫code_review.md
        - ✅ 已完成。含 review checklist (correctness, security, cost discipline, observability, testing, code quality, architecture), severity levels, anti-patterns

2. 進行Phase 1 Task 3 的完整實作
   1. 目前於 @.agents/skills 與 @.claude/skills 已經安裝了許多可以去使用的skills說明 @skills-lock.json ，請依據你的需求以及情境來調用。
   2. 你需要做一個 pipeline：輸入一份 10-K（CIK + accession 或檔案 URL），輸出結構化 JSON，每個 item 包含 `part`、`item_number`、`item_title`、`content_text`、`char_range`、`status`（`extracted` / `incorporated_by_reference` / `not_applicable` / `reserved`）。在 Zeabur 部署為 API，面試官會用自己挑選的 filings 呼叫它。
   3. 請記得看要串聯好SEC 官方 API
   4. 請記得建好 evaluation set（涵蓋不同產業、年份、公司規模，包含一些舊格式），並報告準確度、失敗模式、以及成本/延遲。
   5. 可以參考做法 @notes/thoughts/_ThoughtsDraft.md 以及 github 上的相關實作例如 : https://github.com/dgunning/edgartools/tree/main 、 https://github.com/lefterisloukas/edgar-crawler 、 https://github.com/NataliaZarina/sec-10k-downloader 、 sec-10k-analysis skills 等等
   6. src/task3_sec/llm_refiner.py 當中用到的prompt要移動到 prompts 資料夾當中，並且最好可以建立versions等跡證，以及針對此項目建立相關的測試檔案。
   7. eval set的收集與下載分析應該要來自真實的SEC 官方 API 10k filing，而不是自己憑空創造的假sample資料。我希望這個eval set是真的有透過SEC API / edgar / xrbl所得到的真實資料。帶 `User-Agent` header、10 req/sec，可能需要更貼近真實瀏覽器樣貌以能夠真的順利爬到資料不會被阻擋。並且需要考量大概數十到數百MB檔案的處理下載與parsing過程(網速也可能很慢需要考量)，確保機制和流程是足夠robust的，可以應對實際上會遇到的edge cases的狀況。
   8. (為了讓整個流程更完整，你可以考慮在爬蟲部分以及下載10k filing的api建制一個簡單的html parser，能夠直接把html原始檔轉換成純文字，便於後續處理與使用。注意這樣會把檔案變大，請一併在後續處理上做優化。或是需要思考規畫其他更優的機制流程。) : 這是我的初步想法，你可以斟酌
   9. (在整個流程當中，你會發現你將會需要用到大量的skills以及llm api key的串接，請善用你目前已經安裝的skills，並且也要設計好prompts資料夾，把所有用到的prompt都放在裡面，並且要做好版本控管，方便後續修改與測試。) : 這是我的初步想法，你可以斟酌
   

---

## 🔄 當前狀態 (2026-05-04 12:40)

### ✅ Phase 0 完成
- 完整 repo skeleton 建立完畢
- 所有文件都已建立（CLAUDE.md, AGENTS.md, PLANS.md, code_review.md, architecture_design_spec.md）
- 4 個 Claude Skills（lint-and-test, build-and-release, dependency-audit, security-scan）
- Unified FastAPI app with 3 task routers (skeleton mode)
- Shared harness infrastructure（harness engine, evaluator, cost tracker, structured logging）
- LLM provider factory（OpenRouter + NVIDIA dual-backend, per-user API key support）
- Eval sets designed（5 + 8 + 8 = 21 cases）
- Prompt records（4 versioned files）
- Dark-theme dashboard UI
- 18 tests all passing
- Zeabur deployment config ready

### 🚧 接下來
- **Phase 1**: Task 3 — SEC 10-K Extraction pipeline implementation
- **Phase 2**: Task 2 — Browser Automation Agent implementation
- **Phase 3**: Task 1 — CI/CD Skills Engine implementation
- **Phase 4**: Evaluation runs + README polish + Zeabur deployment

---

## 💬 溝通紀錄

### Agent → User (2026-05-04 12:40)
- **Phase 0 全部完成！** 所有 checklist items 1-10 都已完成 ✅
- 18 個 tests 全部通過
- repo skeleton 完整可運行
- 接下來準備進入 Phase 1: Task 3 SEC 10-K 實作
