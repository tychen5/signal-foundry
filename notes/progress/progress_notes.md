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
