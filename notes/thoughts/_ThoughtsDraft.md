# Thoughts:
* 這不僅是 3 個功能，也是 3 種 failure pattern
| Task          | Failure 類型                   |
| ------------- | ---------------------------- |
| CI/CD Skills  | deterministic system failure |
| Browser Agent | interactive uncertainty      |
| 10-K parsing  | messy data ambiguity         |
* wrapper（harness）才是真正的護城河，不是模型本身。
* 一個精心設計的 harness——涵蓋 belief tracking、declarative planning、symbolic reflection、LLM-backed revision——可以在同樣的 base model 下讓 end-to-end 表現提升數倍。

# Goals:
* AI Reliability Platform (LLM Agent 在不確定世界中如何變得可靠)
* 讓 AI 系統「可驗證 + 可維護 + 可進化」
* 要做AI systems、嚴謹軟體工程思維
* 請思考要如何將不確定性（LLM 的幻覺、網頁的變動、財報的髒資料）轉化為確定性（Systematic, Reliable, Low-latency）
* 核心策略必須是「混合架構 (Hybrid Architecture)」與「駕馭工程 (Harness Engineering)」
* 建立防護網、回饋迴圈，並在成本與速度間做出精準的工程權衡。
* 展現你對系統穩定性、邊界情況的掌控力，以及利用先進技術解決髒資料的巧思
* 以「AI‑first、分層容錯、可觀測性」為核心的系統設計
* 強調 驗證回路、可審計 prompt、故障回滾、成本上限，並在 repo 提供 prompts/、CI replay、Zeabur demo URL 與清楚的 failure case 分析
* 展現出系統性思考、工程權衡（tradeoffs）、高品質人-AI 協作（Harness Engineering），以及對金融交易場景的連結
* 架構強調紀律、權衡、迭代，實作導向、目標驅動、行動優先、當責心態，highlight Harness Engineering 與 人-AI 協作過程。

## Tech Stack參考
* 主要程式語言: anaconda python 
* 主要使用agent框架: langchain eco system (需要可以支援使用langchain-openrouter與langchain_nvidia_ai_endpoints來呼叫LLM。系統要能夠可以很輕易的依據使用者所輸入的模型名稱來切換model，最好是可以有個下拉式選單主要會用到openai/gpt-5.5、anthropic/claude-opus-4.7、google/gemini-3.1-pro-preview、moonshotai/kimi-k2.6、z-ai/glm-5.1、deepseek-ai/deepseek-v4-pro、minimaxai/minimax-m2.7等主流旗艦LLM)
    * [optional] deepagents (https://docs.langchain.com/oss/python/deepagents/overview)
    * [optoinal] langsmith (https://docs.langchain.com/langsmith/observability-quickstart、https://docs.langchain.com/langsmith/evaluation-quickstart#sdk)
        * Agent Evals: https://docs.langchain.com/oss/python/langchain/test/evals
    * Memory: https://docs.langchain.com/oss/python/langchain/long-term-memory 、 https://docs.langchain.com/oss/python/langchain/short-term-memory 
    * context engineering: https://docs.langchain.com/oss/python/langchain/context-engineering#state
    * [optoinal] Model Context Protocol (MCP): https://docs.langchain.com/oss/python/langchain/mcp
    * human in the loop: https://docs.langchain.com/oss/python/langchain/human-in-the-loop 
        * middleware: https://docs.langchain.com/oss/python/langchain/middleware/built-in 
* [optional] Frontend UI: Generative UI (https://docs.langchain.com/oss/python/langchain/frontend/generative-ui、https://docs.langchain.com/oss/python/langchain/frontend/integrations/openui)
* [optional] Retrieval - Hybrid RAG/Agentic RAG: https://docs.langchain.com/oss/python/langchain/retrieval#hybrid-rag 、 https://docs.langchain.com/oss/python/langchain/rag 、 https://docs.langchain.com/oss/python/langchain/knowledge-base
    * [optional] vector store / knowledge base: https://docs.langchain.com/oss/python/langchain/knowledge-base
* [optional] multi-agents / skills: https://docs.langchain.com/oss/python/langchain/multi-agent/skills-sql-assistant 、 https://docs.langchain.com/oss/python/langchain/multi-agent/skills 

# Notes (draft thoughts inference only):
* 因為需要部署到Zeabur，所以可能需要先搜尋相關的best practice、依照並遵循指定需求設計建構出合適的repo架構，把整套 skeleton 架好以讓repo的結構是好擴展且易讀易懂好修改的，盡可能讓系統是可靠的。
    * 主要會以python來進行開發。你需要設計「整個 repo 架構」、寫 evaluation engine、設計 browser agent loop
    * 做README至少要包含: 架構圖、tradeoffs、failure cases、evaluation method、how to run, key design decisions, where LLM involved等等資訊、把整個專案 blueprint 做到 production-level
        * 設計 repo 結構（production-grade）、寫 Zeabur-ready boilerplate、設計 Claude Skills schema、寫 evaluation framework
        * LLM vs rule-based、multi-step agent vs single shot、retry vs redesign、哪些 case 目前會 fail、failure taxonomy + metrics、未來roadmap優化
    * 建議 monorepo (例如可用 ZBPACK_APP_DIR 指定)、zbpack.json、同一 repo：api service/web service/worker service/... 每個都可以選不同目錄
    * idempotent（同 repo 多次跑結果一致 same repo + same commit → same result）、timeout control、sandbox（避免任意 code execution、Docker / isolated runtime）、Skill composition(build-and-release = lint + test + build)、AI trigger design(skill mapping)、...
    * headless browser: Playwright（Zeabur 支援）、輸入 prompt → 執行 → 顯示 browser log、Plan → Act → Planning → Execution → Reflection loop (Observe → Reflect → Re-plan)、Multi-strategy selector(優先順序：1. semantic match 2. text match 3. visual hint 4. fallback heuristic)、Self-healing (selector fail →
→ analyze DOM change → regenerate selector...)、State verification (目標狀態達成)、Evaluation(10~20 個 task 登入網站、搜尋商品、填表單、分頁跳轉...) ...
    * chunking strategy、retry + fallback、evaluation metrics（很重要。怎麼知道系統是對的？）、1. Raw fetch 2. HTML normalize 3. Rule-based section split 4. LLM refine 5. Post-validation、Cross-validation(XBRL data section、 length sanity check)、Heuristic validation(Item 1A 應該包含 risk keywords)、Coverage check (   16 items 是否都有？)、  Special cases (- incorporated by reference - not applicable - reserved ..)...
    * 三題共用整合的可能性: 例如frontend: Skills Runner、Browser Agent、 SEC Analyzer、...；例如backend: Skill Engine、 Agent Engine、Extraction Engine、...
                ┌────────────────────┐
                │     Web UI         │
                │ (Task Runner)      │
                └────────┬───────────┘
                         │
                ┌────────▼────────┐
                │ Orchestrator    │  ← 核心（最重要）
                │ (Agent Engine)  │
                └────────┬────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────▼───────┐ ┌──────▼────────┐ ┌────▼────────┐
│ CI/CD Skills  │ │ Browser Agent │ │ 10-K Parser │
│ (Task 1)      │ │ (Task 2)      │ │ (Task 3)    │
└───────┬───────┘ └──────┬────────┘ └────┬────────┘
        │                │               │
        └────────┬───────┴───────┬───────┘
                 ▼               ▼
          Evaluation Engine   Logging/Tracing


Task 1
GitHub CI/CD as Skills
Skill harness + sandbox
Multi-agent reviewer
Idempotency + dry-run
Cost + token ledger
Task 2
Browser Automation Agent
AOM > DOM > screenshot
Planner/Executor/Healer
Semantic state tracker
Silent-failure detector
Task 3
SEC 10-K Extraction
Rule + LLM hybrid
Reflexive validation loop
Cross-XBRL verification
Cost/latency discipline

->
Shared harness infrastructure
Context engineering · Eval set · Observability · Prompt ledger · LLM-as-judge

->
Evaluation discipline (the real differentiator)
Edge-case eval set · Failure mode taxonomy · Held-out test resilience

->
Innovation angles (vs OpenClaw/HermesAgent baseline)
Harness > model · AOM locators · Reflexive arch · Intent + spec engineering

✅ 統一 Evaluation Framework
{
  "task_id": "...",
  "input": "...",
  "expected_behavior": "...",
  "actual_output": "...",
  "confidence_score": 0.82,
  "failure_type": "hallucination | parsing_error | timeout",
  "retry_count": 2
}
1️⃣ Self-evaluation
LLM 評估 LLM（但有 guardrail）
2️⃣ Deterministic check

例如：

CI/CD → exit code
10-K → section coverage
Browser → DOM state
3️⃣ Failure taxonomy
- hallucination
- partial extraction
- wrong navigation
- stale selector

prompts/
 ├── skill_design.md
 ├── agent_planning.md
 ├── failure_analysis.md
 ├── eval_design.md
 ...
 Given a failed browser action,
analyze whether the failure is due to:
1. selector mismatch
2. page load issue
3. logic error

Return structured diagnosis.



CLAUDE.md: 
The Project Brain Auto-loaded every session. Contains your architecture, tech stack, conventions, and workflow rules. 
→ Hierarchy: root 
→ subdirectory 
→ child (loaded on demand) 
→ Run /init to auto-generate it

CLAUDE.local.md: 
Personal Overrides Gitignored. Your local environment paths, debugging shortcuts, and private preferences. 
→ Never committed to the repo, stays on your machine

.claude/settings.json: 
Permissions & Hooks Tool access, allowed commands, hook configurations, and environment variables. 
→ Committed to git and shared across the team

skills/: 
Reusable Expertise Auto-invoked when task context matches the skill description. 
→ YAML frontmatter makes each skill also a /slash-command 
→ Can fork into a subagent for parallel execution

agents/: 
Subagents Isolated context windows with their own worktree. 
→ Frontmatter defines name, description, tools, and model 
→ 3 built-in modes: Explore (Haiku), Plan, General 
→ Set worktree isolation for parallel development

agent-memory/: 
Persistent Knowledge Across Sessions What Claude remembers between sessions lives here.

worktrees/: 
Git-level Isolation for Parallel Agents Each agent gets its own branch and filesystem. 
→ .claude maps to worktree task name

.mcp.json: 
External Tool Connections JIRA, GitHub, Slack, databases, any API. 
→ Committed to git for team sharing 
→ Channels push messages into live sessions

.claudeignore: 
Context Boundaries Files Claude should never read. 
→ Critical for large monorepos to keep context clean

plugins/: 
Bundled Distribution Skills, agents, and commands packaged for teams. 
→ Install scripts auto-detect and copy to the right locations

my-project/
├── CLAUDE.md                ← Project Brain
├── CLAUDE.local.md          ← Personal Overrides（gitignored）
├── .claude/
│   ├── settings.json        ← Permissions + Hooks + Env Vars
│   ├── skills/              ← Reusable Expertise
│   │   └── review/
│   │       └── SKILL.md
│   ├── agents/              ← Subagents
│   │   └── code-reviewer.md
│   ├── agent-memory/        ← Persistent Knowledge Across Sessions
│   └── worktrees/           ← Git-level Isolation for Parallel Agents
├── .mcp.json                ← External Tool Connections
├── .claudeignore            ← Context Boundaries
└── plugins/                 ← Bundled Distribution

CLAUDE.md (root)          ← 整個專案
  └── 子目錄/CLAUDE.md   ← 子模組專屬規則（按需載入）
        └── 更深層/CLAUDE.md

 CLAUDE.md 包含：Tech Stack 與版本、開發命令（npm run dev、npm run lint）、Architecture decisions、API 設計規範、不能踩的紅線（例如「不經確認不能 commit」、「必須先寫測試」）。
 Skills 本質上是 CLAUDE.md 的模組化切片。與其讓 Claude 每次任務都審閱一個巨大的文件，不如讓它只在任務 context 匹配時載入特定的 skill 指令。更好的 context 效率，相同的自動行為。
 .claude/skills/
└── review/
    ├── SKILL.md         ← 主 prompt（必需，< 5000 字）
    ├── scripts/         ← 複雜邏輯用 Python/Bash
    ├── references/      ← 文件、JSON schema、config template
    └── assets/          ← Templates and binary files
Skills 可以：Claude 根據 task context 自動 invoke（auto-invoke）、用 /skill-name 手動觸發、或兩者皆可。對危險操作（如 deploy）設 disable-model-invocation: true，強制要求人工確認。
Subagent 是定義在 Markdown 檔案（含 YAML frontmatter）裡的代理程式。frontmatter 定義 metadata 和 config，body 成為引導 subagent 行為的 system prompt。Subagent 只接收這個 system prompt（加上基本環境資訊），不會接收完整的 Claude Code system prompt。
三種內建 Subagent 類型（不需設定檔）

Explore（Haiku，快速唯讀）：用來探索 codebase
Plan（研究和架構，唯讀）：用來規劃複雜任務
General（完整工具存取）：通用目的

Subagents vs Skills vs Agent Teams
Subagent 是把任務 委派 給下屬。Agent Teams 則是 協作——多個 Claude session 作為同級 peers，互傳訊息、共享任務列表。每個 team member 有自己的 context window，共享 1M token context。
Worktree Isolation（關鍵）
設定 isolation: worktree，subagent 就在臨時 git worktree 中執行，file edits 寫入隔離的 copy 而非你的主工作目錄。若沒有變更則自動清理；有變更則回傳 worktree path 和 branch。 GitHub
多個 subagent 同時 edit 不同 feature，互不衝突。
Fork Subagent（成本最佳化）
Fork 的 system prompt 和 tool definitions 跟 parent 完全一致，所以第一個 request 可以 重用 parent 的 prompt cache，比 spawning 全新 subagent 便宜。用 CLAUDE_CODE_FORK_SUBAGENT=1 啟用。
Hooks 是 event-driven scripts，在 Claude Code 有事情發生時執行。與 prompts 依賴模型解讀不同，hooks 執行確定性程式碼。它們不會 hallucinate。 沒有 hooks，每個防護都取決於模型理解你的指令。有了 hooks，你在系統層面強制執行規則。            

* 同時開發時就要思考該怎麼去做驗證、evaluation、testing，最好可以有個benchmark/matrix以能夠知道如果未來演算法去做修改更動的時候，是否真的可以針對設計的那些metrics、performance進行improve，並且避免regression errors。
* README 的寫法參考:
    * 開宗明義畫出架構圖（用 Mermaid 語法直接畫在 Markdown 裡）。
    * 設立一個 "Design Trade-offs" 區塊。誠實地寫下：「在 Task 3 中，我原本嘗試讓 LLM 直接切分文本，但發現 Token 成本過高且有 5% 機率產生幻覺。因此我退而求其次，改用 Regex 定位大框架，僅用 LLM 處理 edge cases。這讓準確率提升到 98%，成本下降 80%。」這種話語權重極高。
    * 展示 AI 協作 (Claude Code 應用):
        * 在 README 中開一區 "AI Collaboration Log"。
        * 舉例說明：「我在設計 Task 2 的狀態機時卡住了，我讓 Claude Code 幫我寫了測試框架的骨架，但我親自 review 並修改了 Exception Handling 的機制，因為 AI 忽略了 Playwright 的 silent failure 問題。」這證明你是主導者，AI 是你的工具。
* Agentic AI 與 Harness Engineering 成為主流：模型本身是 commodity，harness（約束、feedback loops、evaluator 分離、自改進機制）決定成敗。LangChain 等透過 harness 優化，在 TerminalBench 等 benchmark 提升 20%+ 而無需換 model。
* Claude 系列強勢（Opus 4.x 在 agentic/coding 領先），支援 Skills 系統，讓 agent 自動載入領域專長。
* GraphRAG / Knowledge Graph + LLM：大幅改善複雜推理、減少 hallucination，尤其適合金融（實體關係、事件鏈）。
* 多模態、長上下文、MoE、量化/蒸餾：推理模型（reasoning models）進化，hallucination 降低；open-weight 模型（如 DeepSeek 系列）性價比高。
* 自修正與自我維護：Reflection、ReAct、MCTS 等模式；browser agent 從純 selector 轉向 semantic/visual + dynamic repair。
* MLOps：容器化、版本控制、A/B 測試、observability 已成標配。
我的 side project 連結（建議你實際做或模擬）：我有開源/個人 project 使用 LangGraph + GraphRAG 建金融事件 agent（event-driven notification），或 browser agent 結合 Playwright + reflection loop。強調 2 年+ LLM 經驗（PyTorch 微調 LoRA/SFT/DPO）、Kaggle/開源貢獻、或 NeurIPS 相關閱讀。實際成就舉例：成功將 prototype 轉 production（降低延遲 40%、提升準確率 25% via hybrid）。        
* 先做 MVP（能跑的基本版），再加 harness/eval/innovation。Commit 過程透明。


# High-level 粗略思維參考事項/想法草稿
* Repo 必須展現強大的「工程紀律」
* 在 prompts/ 裡，不要只放最終版的 prompt。放 v1_naive.txt、v2_added_constraints.txt、v3_few_shot_eval.txt，並在 README 說明你為何改版（例如：發現 LLM 會在沒有資料時產生幻覺，因此加上了強制回傳 Null 的 constraint）
* LLM as a Judge (Evaluation Harness)：這是超越一般 Agent 的關鍵。為每個任務寫一個簡單的評估腳本，用另一個 LLM（或嚴格的規則）來打分。例如 Task 3，寫腳本自動比對擷取出的 char_range 是否真的能對應到原始文本
* 效能與快取 (Latency & Caching)：系統設計上，可以考慮將頻繁讀取的測試資料（例如 SEC API 回應）進行 In-Memory 快取機制。這不僅能嚴格遵守 SEC 的 10 req/sec 限制，也能大幅加速你在開發與 CI/CD 測試時的評估速度，展現你對系統 I/O 與底層效能的敏銳度。
* AI‑first workflow：把驗證（tests、screenshots、golden outputs）當作第一等公民，讓模型能自我驗證與回滾。
* 分層容錯：短路（fast fail）、重試、策略替換（selector fallback / alternative skill）三層。
* 可觀測性與可審計：每次 Skill/Agent 行為記錄 input/prompt、LLM 回應、執行結果、metrics（latency/cost/error）。
* Evaluation Discipline：如何驗證系統正確（自建 eval set + held-out 測試 + failure mode 分析）。
* Systematic Thinking：面對模糊/真實資料（GitHub repo 變動、網站 UI 變動、10-K 格式極大變異）的分解能力。
* Engineering Tradeoffs：成本（token/延遲）、可靠性（self-correction）、可觀測性（logging/observability）、安全性（auth、sandbox）。
* AI Collaboration Quality：Prompt 紀錄、commit history 反映迭代過程（而非一鍵生成）；善用 Claude Code Skills、Harness Engineering（2026 熱門概念：agent harness 比單一 model 更重要，透過結構化約束、feedback loop、evaluator 分離等提升可靠性）。
* Innovation：超出一般 OpenClaw/HermesAgent 的地方，例如引入 GraphRAG、multi-agent harness、self-improving loop、與公司交易系統連結的想法（即使沒完全實作，也寫在 README/Notes）。
* Repo 結構：單一 monorepo 或三個子目錄（task1/、task2/、task3/）。根目錄有 prompts/（分類存主要 prompts + skills）、evals/（測試集 + 結果報告）、docs/（設計決策）。
* Commit History：反映真實過程 — e.g., "feat: initial prototype with Claude", "refactor: add self-correction harness", "test: expand eval set with edge cases", "opt: reduce latency via hybrid rules+LLM"。
* Deployment：Zeabur（GitHub integration ）。每個 task 獨立 service 或單一 dashboard（用 FastAPI/Streamlit/Gradio），附公開 URL。加上 observability（e.g., Prometheus + Grafana 或簡單 logging to file/endpoint）。
* README：執行方式、設計決策與權衡（為何選 hybrid 而非 pure LLM）、AI 如何協助（哪些部分用 Claude Code 快速從 0 到 1，哪些人類 review）、創新點與未來優化方向（連結到公司 LLM 代理、RL、事件驅動交易）。
    * 每個 README 都寫「此系統如何支援公司 LLM 代理（RAG、工具使用、任務規劃）、金融文本微調、事件分析、交易訊號生成」。
    * 未來優化方向（寫在 repo）：
        * Multi-agent system：Planner + Extractor + Verifier + Notifier。
        * Self-improving harness：定期用新 eval data 優化 prompts/skills。
        * 整合公司 infra：GPU/FPGA 加速 inference、低延遲 pipeline。
        * 金融特定：情緒分析、因子建模連結、A/B 測試交易訊號。
* Prompt 管理：用 Claude Skills（SKILL.md + YAML frontmatter）封裝可重用能力。Skills 描述要精準 trigger（包含 trigger phrases）。
* Harness Engineering：將 agent 包在嚴格 harness 中（execution loop + tool registry + context manager + evaluator + lifecycle hooks）。關鍵趨勢，能大幅提升可靠性，而非依賴 model 本身。
* Observability & Production Mindset：全系統加 structured logging、trace、metrics（latency、token usage、success rate）。強調可觀測性與可操作性。
* 自動化 eval harness 設計: 建議用 LLM-as-judge 搭配 15 個 ConversationalGEval metrics；關鍵發現是 evaluator 模型的能力很重要——llama-3-3-70b 能抓到所有已知失敗，小型模型會漏掉 4-5 個。 你可以在 eval harness 裡加入 automatic failure taxonomy，讓每次 eval run 自動產生 failure_modes.md，幫助你和面試官快速看到系統的弱點分佈。
* Context engineering over prompt engineering: 五個 production-grade context quality criteria：relevance（相關性）、sufficiency（充分性）、isolation（隔離性）、economy（精簡性）、provenance（來源追蹤）。 你的每個 system 都要在 README 中明確說明你的 context engineering 決策——什麼放進 context、什麼故意排除、為什麼。
*  Prompt ledger（prompts/ 資料夾的做法）: 不只是存 prompts，要存：prompt version、使用場景、對應 eval 結果、iteration log（為什麼從 v1 改到 v2）。這讓面試官真正看到你的 AI collaboration 品質。
* 與 OpenClaw/HermesAgent 的差異化: 你要在 README 特別寫一個 section：「為什麼我的設計優於通用 agent？」主要論點：
    * 針對 domain 的 harness（不是通用 tool loop）
    * 明確的 failure taxonomy 和 recovery 策略
    * Cost discipline（通用 agent 不計成本地呼叫 API）
    * 可重現的 eval 框架（通用 agent 無法量化可靠性）
* 開發優先順序建議
    * 先把三道題目的 eval set 設計好，再開始實作——這強迫你思考「什麼叫成功」
    * Task 3 先做（最有明確的輸入輸出規範，容易展示系統性思考）
    * Task 2 次之（技術難度最高，但有 browser-use 等開源 library 可以快速起步）
    * Task 1 最後（Claude Skills 生態系最新，但文件最完整）
* 每道題目的 prompts/ 資料夾要在開發過程中持續更新，不要事後補。commit message 要反映真實的 iteration 過程，不要一次大 commit。
* Subagents 在自己的 context 中運行，具有自己的一組允許的工具。它們對於讀取許多文件或需要專門關注而不會使主對話變得混亂的任務很有用。Plugins 將 skills、hooks、subagents 和 MCP servers 捆綁到來自社區和 Anthropic 的單個可安裝單元中。如果您使用類型化語言，請安裝 代碼智能 plugin 以為 Claude 提供精確的符號導航和編輯後的自動錯誤檢測。當您需要快速、專注的工作者時，使用 subagent：研究問題、驗證聲明、審查檔案。Subagent 執行工作並返回摘要。您的主要對話保持乾淨。當隊友需要共享發現、相互質疑和獨立協調時，使用 agent team。Agent teams 最適合具有競爭假設的研究、並行程式碼審查，以及每個隊友擁有單獨部分的新功能開發。轉換點： 如果您運行並行 subagents 但遇到上下文限制，或者您的 subagents 需要相互通訊，agent teams 是自然的下一步。
* Skill 是一個包含知識、工作流程或指令的 markdown 檔案。您可以使用像 /deploy 這樣的命令調用 skills，或者 Claude 可以在相關時自動載入它們。Skills 可以在您目前的對話中運行，或通過 subagents 在隔離的上下文中運行。
* MCP 給予 Claude 與外部系統互動的能力。沒有 MCP，Claude 無法查詢您的資料庫或發佈到 Slack。Skills 給予 Claude 關於如何有效使用這些工具的知識，以及您可以使用 /<name> 觸發的工作流程。Skill 可能包括您的團隊資料庫架構和查詢模式，或具有您的團隊訊息格式規則的 /post-to-slack 工作流程。範例：MCP 伺服器將 Claude 連接到您的資料庫。Skill 教導 Claude 您的資料模型、常見查詢模式，以及用於不同任務的表格。
* 一旦工作流程變得可重複，就不要再依賴冗長的提示或重複的溝通。使用技能（Skill）將指令、上下文和支援邏輯打包到 SKILL.md 檔案中。每項技能都應限定於一項工作。首先列出 2 到 3 個具體的用例，明確定義輸入和輸出，並撰寫描述，說明該技能的功能和適用場景。同時，也要包含使用者實際會使用的觸發短語。不要試圖一開始就考慮到所有極端情況。先從一個代表性的任務入手，確保它運作良好，然後將該工作流程培養成一項技能，並在此基礎上不斷改進。只有當腳本或額外資源能夠提高可靠性時，才應該添加它們。一個很好的經驗法則是：如果你不斷重複使用相同的提示或糾正相同的工作流程，那麼它很可能就會成為一項技能。技能對於以下重複性工作特別有用：日誌分類、發布說明撰寫、根據清單進行公關審查、移民規劃、遙測或事件摘要、標準調試流程
* README.md files are for humans: quick starts, project descriptions, and contribution guidelines.


## Task 1: GitHub CI/CD as Claude Skills
* Skills 使用特定於您的項目、團隊或域的信息擴展 Claude 的知識。Claude 在相關時自動應用它們，或者您可以使用 /skill-name 直接調用它們。通過將目錄與 SKILL.md 添加到 .claude/skills/ 來創建 skil。Skills 也可以定義您直接調用的可重複工作流。
* Using the ci-cd-pipeline-builder skill
* 將常見 CI/CD 封裝成可重用、精準觸發的 Skills，demo 能對真實 repo 執行。
* 把 CI/CD 封裝成 LLM 可靠呼叫的工具。看重的是邊界、安全、與冪等性 (Idempotency)。把 Claude Skills 做成明確邊界的可重用服務。
* Skill Schema 設計：不要讓 LLM 直接下 bash command。提供結構化的 Skill，例如 run_linter(target_dir, fix=True/False)。
* Dry-Run 機制：所有的修改型 Skill (如 build-and-release 或自動修復程式碼) 都必須有一個 dry_run 參數。要求 LLM 在正式執行前，先以 dry_run=true 執行並檢視執行計畫，人類或系統確認後再實際 apply。
* 狀態與冪等性：如果 LLM 執行 dependency-audit 兩次，結果必須一致且不會搞壞環境。每次執行都應產生一個唯一的 Execution ID 供追蹤。
* 導入 MCP (Model Context Protocol) 概念：即使不用官方框架，也請實作類似的標準化介面。讓 Skill 具備自我描述能力（Discoverability），當 LLM 詢問「你能做什麼」時，系統能回傳精確的 JSON Schema 與權限邊界。
* Security Boundary：在設計中說明，這些 Skills 會在隔離的 Container (Docker-in-Docker) 或沙盒環境中執行，防止 LLM 生成惡意指令破壞主機環境。
* Skill interface：inputs、outputs、安全邊界（只讀/可寫 repo 範圍）、idempotency token。
* Auth：短期 token + least‑privilege GitHub App；所有 write 操作 require human approval webhook。
* 運作流程：Plan Mode → dry‑run (lint/test in sandbox) → gated release (manual approval) → audit log。
* Demo：Web UI 顯示 skill run trace、prompt、artifacts、replay 按鈕。
* Skills 定義（skills/ 目錄，每個是資料夾含 SKILL.md）：
    * lint-and-test：輸入 repo URL/branch、output 報告。包含安全邊界（只讀權限）、idempotency（重跑不重複執行）。
    * build-and-release：觸發條件 "ship it / deploy / release"。
    * dependency-audit、security-scan（整合 Dependabot/CodeQL 想法）。
* Demo 服務：FastAPI + Web UI（或簡單 API）。使用者輸入 repo + task description → Claude（或你的 agent）自動 trigger 對應 Skills → 執行 GitHub API / Actions（需 OAuth token，嚴格 scope 限制：repo:read + workflow）。
* 安全與權衡：
    * Auth：GitHub App 或 fine-grained PAT，sandbox execution（Docker 或 GitHub-hosted runner 模擬）。
    * Error handling：明確 status（success/partial/fail）、retry with backoff。
    * Idempotency：使用 cache key（commit SHA）。
* Harness：外層 harness 管理 tool calling、logging、cost tracking。Evaluator 檢查輸出是否符合預期 schema。
* Skills description 寫得極精準（trigger phrases + examples），讓 Claude 低誤觸。
* 整合 observability：每步 log + trace ID。
* 創新：提出「CI/CD Agent Swarm」——多 Skills 組成 graph（LangGraph），自動診斷 failing workflow 並 propose fix（連結公司快速迭代文化）。未來可接 LLM 代理自動優化交易系統的 CI/CD。
* Eval：自建 5-10 個 repo scenarios（簡單 Python、複雜 monorepo、failing cases），報告 success rate、平均時間。
* Skill harness: Skill 的結構應遵循三層設計：SKILL.md（主 prompt，控制在 5000 字以內防止 context 爆炸）、scripts/（複雜邏輯用 Python/Bash 腳本，而非把所有細節塞進 prompt）、references/（文件、JSON schema、config template，動態注入 context 而非靜態寫死）。
* Skill 設計的 4 個原則：
    *  Skill boundary precision（邊界切割）: 每個 skill 要有精確的 trigger 描述，讓 Claude 能精準 invoke，不會誤觸。設計四個核心 skill：
        * lint-and-test：觸發詞 = "test this", "run tests", "check code quality"
        * build-and-release：觸發詞 = "release", "publish", "deploy artifact"
        * dependency-audit：觸發詞 = "audit deps", "check vulnerabilities", "update packages"
        * security-scan：觸發詞 = "scan for secrets", "SAST", "check CVEs"
    * 安全沙箱（Sandbox execution boundary）: 每個 skill 執行前先產生一個 dry-run plan，列出將要執行的操作，讓使用者確認後才真正執行。另外加入 blocklist（禁止 force push、禁止 prod deploy、禁止 IAM 更動）。Circuit breaker 機制：連續 3 次 block 或單次 session 累積 20 次 block，自動暫停回到手動確認模式。
    *  Idempotency: 每次 skill 執行前先 check 狀態（例如 lint 是否已通過、tag 是否已存在），避免重複操作。用 GitHub API 的 commit status / check runs 做狀態鎖。
    * Multi-agent review: 用 /code-review 做 multi-agent PR analysis——每個 finding 都在獨立的 context window 裡被驗證，防止 one agent bias。你可以設計一個 orchestrator skill → 拆解成 code-reviewer subagent + security-scanner subagent + test-engineer subagent，各自獨立分析後合成 final report。這比單一 agent 分析可靠得多。
    * Cost + token ledger（成本意識）: 每次 skill 執行後，記錄 tokens used、API calls、execution time，expose 為 Zeabur 的 /metrics endpoint。面試官會需要看到你對 cost discipline 的重視。

## Task 2: Generalized Browser Automation Agent
* Using playwright-skill
* AOM > DOM > Screenshot。Accessibility Object Model (AOM)。最可靠的 agent 不是解析 DOM 或看截圖，而是讀 Accessibility Tree。一個 target "Role: button, Name: Checkout" 的 agent，比用 div.checkout-btn-v3 的 agent 穩定 10 倍。
    * 三層 fallback 策略（ self-correction）：
        * Layer 1: AOM locator (by role + label + state)
    → 失敗時 fallback ↓
Layer 2: Semantic DOM (aria-label, data-testid, semantic HTML)
    → 失敗時 fallback ↓
Layer 3: Vision mode (screenshot + coordinate)
    → 失敗時觸發 Healer agent
* 自然語言任務 → 可靠跨網站執行 + self-correction + self-maintenance。
* 打造能容忍 UI 變動、能自我糾錯的網頁自動化代理。瀏覽器 Agent 採用 self‑healing + MPC（Model‑Control）模式。
* 捨棄純 DOM 依賴，採用混合定位 (Hybrid Locators)：這是打敗一般 Agent 的關鍵。單純依賴 XPath 或 CSS Selector 只要網站一改版就會爛掉。
* Observe-Think-Act 迴圈 (LangGraph 狀態機)：
    * Observe：擷取當前 DOM 樹，過濾掉不可互動的元素（清洗 HTML），並同時截圖。
    * Think：LLM 決定下一步動作，如果上一步失敗，必須讀取錯誤訊息（如 ElementNotInteractableException）並提出新策略。
    * Act：透過 Playwright 執行，並捕獲 Exception 丟回狀態機。
* Set-of-Mark (SoM) 視覺標註技術：不要讓 LLM 去猜 CSS Selector。在截圖時，利用 Playwright 將畫面上所有可互動的元素（按鈕、輸入框）畫上帶有編號的紅色方框，再把截圖餵給具有視覺能力的 LLM。LLM 只需要回答「點擊編號 5」，系統再將編號對應回實際的 DOM 元素。這大幅降低了 LLM 的理解難度與出錯率。
* 自我維護機制 (Self-Healing)：建立一個資料庫紀錄「任務 - 成功時的元素特徵 (文字、相對位置、DOM 結構)」。當原 Selector 失敗時，觸發 Self-Healing 流程，將舊特徵與當前頁面比對，用 LLM 找出「長得最像」的新元素，並自動更新策略庫。
* 架構：LLM（決策） + Control 層（orchestrator） + Playwright/Chromium（執行）。採 MCP 分工。
* 自我糾錯：失敗時收集 DOM/screenshot → LLM 建議替代 selector 或流程改寫 → replay。
* 自我維護：持續學習 domain‑skills（agent‑workspace），成功策略自動存成 site‑skill。
* Core Engine：Playwright（或 Puppeteer）作為 browser tool。Agent 用 LangGraph 或自訂 ReAct loop。
* Self-Correction Harness：
    * Reflection loop：Action 後 → Observer（screenshot + DOM summary + console log）→ Diagnoser（LLM 分析失敗原因：selector 失效？network？UI change？）→ Strategy Selector（fallback：semantic search locator、visual similarity、retry with different prompt）。
    * 避免 silent failure：強制 post-action verification（e.g., "確認任務完成指標"）。
* Self-Maintenance：
    * Dynamic locator：不依賴硬 coded CSS/XPath，用 LLM 生成 semantic description（如 "login button with text 'Sign In'"）→ 運行時 re-resolve。
    * History-based repair：存過去成功模式，當偵測變動（DOM diff 或 visual hash）時自動適應。
* Evaluation Set：深度設計 — 涵蓋不同 domain（e-commerce、banking、news、Google、複雜 SPA）、task type（form fill、scrape、multi-step navigation）、edge cases（CAPTCHA 提示、login wall、JS heavy site、mobile view）。至少 20-30 cases，分 success/partial/fail + 人工驗證 ground truth。
* Deployment：Zeabur 上 FastAPI/Streamlit 介面，輸入 natural language task → 執行 → 返回 trace（steps + screenshots + reasoning）+ final result。
* Harness 重點：分離 Generator Agent + strict Evaluator Agent（Evaluator 更 ruthless，避免 self-leniency）。引入 MCTS 或 guided search 提升探索。
* 權衡：Pure agent（靈活但不穩） vs Hybrid（deterministic script + agent fallback for recovery） — 推薦後者，生產適用。
* 創新：連結金融 — "監控特定交易網站事件並通知"；提出 visual+semantic hybrid（用 multimodal model 如 Gemini/Claude 分析 screenshot）。未來與公司低延遲 stack 整合（e.g., agent 觸發 FPGA 加速策略）。
* 報告：可靠性指標（success rate across domains）、failure modes（分類：UI change、network、LLM misjudge）、latency/cost。
* Planner / Executor / Healer 三層架構。Playwright AI ecosystem 的核心是三個協作層：Playwright Engine 負責瀏覽器操作，LLM Layer 理解 DOM 結構和 app 行為，Orchestration Loop 協調整個流程。你的架構要更進一步——加上 Semantic State Tracker：
    * Planner：將自然語言任務分解成 step sequence，並預判可能的 failure point
    * Executor：執行 AOM-first 的操作，記錄每步的 before/after state diff
    * Healer：當 Executor 失敗時，分析 accessibility snapshot，識別 root cause（selector 改變 vs 流程改變 vs 網路問題），再試不同策略
    * Semantic State Tracker：這是創新點——不只記錄「按了什麼按鈕」，而是記錄「頁面的業務語義狀態」（例如：cart_has_items=true, checkout_initiated=false），防止 silent failure
* Silent failure 防範
    * Silent failure 是最難防的——agent 以為成功了，實際上什麼都沒發生（例如表單送出後顯示 error toast，agent 卻已繼續下一步）。你的解法：
        * 每個 step 後做 intent verification：問 LLM「根據截圖，這個操作是否真的成功？」
        * 建立 success signal taxonomy：對不同類型的操作定義什麼算真正成功（button click → URL change or DOM mutation, form submit → confirmation message or redirect）
        * 設計 confidence score：每步操作後產生 0-1 信心分數，低於閾值自動觸發 Healer
* Eval set 設計:
    * 分成四個難度維度：
        * Domain diversity：電商/金融/新聞/政府網站
        * Task complexity：單步/多步/需要 login/需要等待 async response
        * Failure injection：故意注入 selector 不穩定、網路延遲、CAPTCHA
        * Edge cases：SPA 路由、iframe 嵌套、shadow DOM、動態載入
* 根據實測，self-healing 可以正確解決約 65% 的 broken selector 問題；剩下 35% 需要人工介入，通常是因為 UI 改變反映了真正的功能變更，而非只是 selector 更新。 你要在 repo 中誠實記錄這個數字，比你隱藏問題更欣賞你的誠實。    

## Task 3: SEC 10-K Item-level Structured Extraction
* 可以參考做法: https://github.com/dgunning/edgartools/tree/main 、 https://github.com/lefterisloukas/edgar-crawler 、 https://github.com/NataliaZarina/sec-10k-downloader 、 sec-10k-analysis skills
* Rule + LLM 混合，成本放在刀口上。10-K item segmentation 傳統上用規則型方法（regex + HTML parsing），但這些方法很脆弱、難維護，因為 item 標題格式、排序、文件格式變異極大。LLM 在這方面有更好的語義理解，但直接套用在長文件上有 context length 和 hallucination 的問題。
* 處理極高格式變異的 10-K → 結構化 JSON（per Item: part, item_number, title, content_text, char_range, status）。
* 從極度不規則的長文本中，精準抽出結構化資料，並確保沒有幻覺。採用 rule+LLM 混合、明確 status 標記與評估集。
* 分層解析策略 (Tiered Parsing Routing)：千萬不要把整份財報塞進 LLM。這既昂貴又慢。
    * Tier 1 (Rules/Regex/BeautifulSoup)：先用傳統 NLP 找目錄 (Table of Contents) 與超連結錨點。很多新版 10-K 可以直接靠 HTML Tag 完美切分。
    * Tier 2 (Small LLM Router)：如果 HTML 髒亂，用較快、便宜的模型（切塊閱讀）判斷這段文字屬於哪個 Item。
    * Tier 3 (Heavy LLM Extractor)：只有在遇到極度模糊或找不到邊界的段落時，才動用大模型進行精準切分。
* 防範幻覺 (Grounding)：題目要求輸出 char_range。你必須強制 LLM 輸出的文字能在原文中用 indexOf 找到。如果找不到，自動觸發 Retry 或標記狀態為 requires_human_review。
* 處理 Incorporated by Reference 的自動追蹤：很多公司的 Part III 會寫 "Incorporated by reference to the Proxy Statement (DEF 14A)"。一般的做法是標記狀態就結束了；你的 Agent 如果能自動從 SEC API 抓取同一間公司同年度的 DEF 14A 檔案，並從中抽出對應的董監事酬勞資訊，面試官絕對會對你的領域知識 (Domain Knowledge) 與系統完整度刮目相看。
* 成本與延遲監控 (Cost/Latency Dashboard)：在 API 的 Response 中，除了資料本身，附帶一個 metadata 欄位，精確計算這次 parsing 消耗了多少 Token、花了多少毫秒、啟動了哪幾個 Tier 的 Parser。這展現了量化交易公司最重視的「成本紀律」。
* Pipeline：fetch (SEC API) → normalize HTML→ heading detection (rules + regex + ML) → item segmentation → LLM structured generation → post‑validation (char_range, cross‑check XBRL)。
* Status handling：extracted / incorporated_by_reference / not_applicable / reserved；對引用情況自動追蹤並 fetch 參照文件。
* Eval：設計含舊格式、incorporated、非標題化案例的 testset，報告 precision/recall、平均延遲與 token 成本。
* Pipeline：
    * Input Handling：支援 CIK+accession 或 URL。使用 SEC 官方 API（Submissions、search-index、raw file download）。記得 User-Agent header + rate limit（asyncio + semaphore）。
    * Pre-processing：下載 HTML/文本 → 清理（remove noise、normalize headings）。對舊格式（純文本）用不同 parser。
    * Parsing Strategy — Hybrid（規則 + LLM）：
        * 規則層（高效、確定性）：Regex/BeautifulSoup 找標準 headings（如 "Item 1. Business"）、table extraction（pandas-read_html 或專用 table parser）、XBRL 交叉驗證（companyfacts API 拿財務事實）。
        * LLM 層（處理變異）：Chunk document（logical sections 或 fixed size + overlap）→ Structured Output（JSON mode / Pydantic / Outlines）提取 Item。
        * Status 判斷：偵測 "incorporated by reference"（找 proxy statement 連結）、"Not Applicable"、"Reserved"。
    * Post-processing：Validation（char_range 一致性、content 非空檢查）、GraphRAG 增強（建簡單 KG 連結 Item 間關係，提升事件理解）。
* Output：Array of items JSON。
* Eval Set：刻意挑 edge cases — 不同產業（tech、finance、energy）、年份（舊 vs 新）、公司規模、格式（HTML 變異、純文本、tables heavy、incorporated cases）。無公開 ground truth → 自驗證方法：cross-validation（多 model 投票）、XBRL 事實比對、人工抽樣 review、consistency checks（同一公司多 filing 趨勢合理性）。報告 accuracy（per item / overall）、failure modes（heading variation、table parsing、long content truncation）、cost/latency（優化 chunking + cheaper model for simple cases）。
* 權衡明確：Pure rules（快但 brittle） vs Pure LLM（靈活但貴+hallucinate） vs Hybrid（最佳）。用 rules 處理 80% 常見 case，LLM 只處理 ambiguous chunks。
* Harness：外層 verifier agent 檢查輸出 schema + semantic consistency。引入 GraphRAG 提升金融事件理解（連結公司、事件、風險）。
* 創新與公司連結：輸出可直接 feed 公司 event-driven trading notification system 或 金融事件 ETL pipeline。提出 Knowledge Graph 整合（prompt tuning + entity linking）來強化 LLM 在情緒/事件推論。未來：與 RL 結合，extraction 結果作為 state 優化交易策略。成本紀律：fallback to open-weight model、caching、batch processing。
* MLOps：Docker + CI/CD（連結 Task 1）、model versioning、feature store 想法。
* 混合策略：
    * Stage 1：Rule-based pre-segmentation（便宜、快速）
        * 先用 regex + HTML parser 掃描 <a name="item..."> 錨點、目錄結構、標題格式，取得候選邊界。這一步 0 cost，覆蓋 ~70% 的現代 filing。
    * Stage 2：LLM boundary refinement（只用在困難案例）
        * 對 Stage 1 信心低的邊界（例如沒有錨點、純文字 filing、格式不規則），用 few-shot LLM 做語義邊界偵測。模型只看 ±500 chars 的邊界 context，不需要整份文件。
    * Stage 3：Reflexive validation（LLM-as-judge）
        * 最新 benchmark 研究（2026）發現：reflexive 架構（LLM 自我驗證循環）達到最高的 field-level F1 (0.943)，但成本是 sequential baseline 的 2.3 倍；hierarchical 架構在 cost-accuracy Pareto frontier 上表現最佳（F1 0.921，僅 1.4 倍成本）。 arxiv
        * 你的設計：採用 hierarchical + selective reflexion——只對 status 為 incorporated_by_reference 或 not_applicable 的 item 觸發 reflexive validation，其餘直接通過。
    * Stage 4：XBRL cross-validation
        * 用 SEC 官方 XBRL Company Facts API 交叉驗證財務數字，如果 Item 8 抽取的數字跟 XBRL 對不上，自動標記 needs_review。
* Incorporated by reference 處理
    * 當 Item 說 "incorporated by reference from the Proxy Statement"，你要：
        * 偵測到這個 pattern
        * 嘗試找到同公司同年度的 DEF 14A（Proxy），用 SEC submissions API
        * 如果找得到，抽取對應段落，status 改為 incorporated_and_resolved
        * 如果找不到，status 保持 incorporated_by_reference，content_text 填入原始引用文字   
* Eval set edge case 設計：
    * 1993 年以前的純文字 filing（極舊格式）
    * Part III 大量 incorporated by reference 的 filing
    * 超大型公司（蘋果、微軟）vs 微型公司
    * 外國私人發行人的 20-F（格式完全不同）
    * 破產申報、特殊目的公司             
* 成本報告
    * 設計 cost_tracker.py，記錄每份 filing 的：tokens in/out、LLM calls 次數、rule-only vs hybrid 比例、總成本。目標是大多數現代 filing 能用 rule-only（$0 LLM cost），只有少數困難 case 才花錢。
