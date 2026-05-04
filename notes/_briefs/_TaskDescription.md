# Requirements for AI Coding Test 

## About This Test關於這份測驗

這份測驗不是要看你能不能產出可跑的程式碼。面試官想看的是：你面對**模糊、混亂、需要判斷**的問題時，如何讓人類可以與 AI 完美協作，並把一次性原型轉成可靠系統。

面試官在意的幾件事：

- **評估紀律**：你怎麼知道自己做的系統是對的
- **系統性思考**：面對會失敗的真實資料時的分解能力
- **工程權衡**：對成本、延遲、可靠性的判斷
- **AI 協作品質**：人類跟 AI 工具的互動能不能放大你的產出

This test is not about whether you can produce working code — AI tools have made that relatively easy. What interviewers want to see is how human collaborate with AI to turn one-off prototypes into reliable systems when facing **ambiguous, messy, judgment-requiring** problems.

A few things we care about:

- **Evaluation discipline** — how you know your system is correct
- **Systematic thinking** — decomposing messy real-world data that fails in many ways
- **Engineering tradeoffs** — judgment about cost, latency, and reliability
- **AI collaboration quality** — whether your interaction with AI amplifies your output

## Tasks 題目

以下三題，請好好思考該怎麼設計架構以下這幾題該怎麼實作:

- 題目一：GitHub CI/CD as Claude Skills
- 題目二：泛用瀏覽器自動化 Agent
- 題目三：SEC 10-K 財報 Item-level 結構化抽取

Three tasks below. completing all below:

- Task 1: GitHub CI/CD as Claude Skills
- Task 2: Generalized Browser Automation Agent
- Task 3: SEC 10-K Item-level Structured Extraction

## Common Requirements 共通要求

1. **AI 協作為主**：建議使用 Claude Code，善用 Skills 加分。參考：[https://kaochenlong.com/claude-code-skills](https://kaochenlong.com/claude-code-skills)
2. **Git**：公開 repo，commit history 要能反映真實開發過程
3. **Zeabur 部署**：所有題目須部署為可公開存取的服務（[https://zeabur.com/](https://zeabur.com/docs/zh-TW/deploy/how-deploys-work)），並附上 URL
4. **Prompt 紀錄**：在 repo 根目錄建 `prompts/` 資料夾保存主要 prompt
5. **README**：如何執行、主要設計決策、AI 在哪些環節協助了你

1. **AI-first workflow** — Claude Code preferred; using Skills is a plus. Reference: [https://kaochenlong.com/claude-code-skills](https://kaochenlong.com/claude-code-skills)
2. **Git** — public repo with commit history that reflects your actual development process
3. **Zeabur deployment** — all tasks must be deployed as publicly accessible services ([https://zeabur.com/](https://zeabur.com/docs/zh-TW/deploy/methods/github-integration)); include the URL
4. **Prompt records** — keep a `prompts/` folder in the repo root with your key prompts — interviewers will actually read them
5. **README** — how to run, key design decisions, where AI helped you
---

## Task 1: GitHub CI/CD as Claude Skills 題目一：GitHub CI/CD as Claude Skills

把常見的 GitHub CI/CD 工作流程封裝為幾個可重用的 Claude Skills（例如 lint-and-test、build-and-release、dependency-audit、security-scan）。每個 Skill 應有清楚的輸入輸出、安全邊界、錯誤處理。

在 Zeabur 部署一個 demo（Web UI 或 API），讓我們能看到 Skills 在真實 repo 上實際跑起來。

**開發重點**：Skill 邊界切得好不好、認證與安全意識、idempotency、Skill description 能否被 Claude 精準 trigger。

Package common GitHub CI/CD workflows into a few reusable Claude Skills (e.g. lint-and-test, build-and-release, dependency-audit, security-scan). Each Skill should have clear inputs and outputs, safe execution boundaries, and proper error handling.

Deploy a demo on Zeabur (Web UI or API) that lets us see your Skills running against a real repo.

**What interviewers will look at**: how you drew Skill boundaries, auth and safety awareness, idempotency, and whether your Skill descriptions trigger Claude precisely.

---

## Task 2: Generalized Browser Automation Agent 題目二：泛用瀏覽器自動化 Agent

做一個接收**自然語言任務描述**的瀏覽器 agent，能在不同網站上可靠執行。除了基本執行，agent 需要展現：

- **自我糾錯**：失敗時能診斷原因並嘗試不同策略
- **自我維護**：UI 或 selector 變動時能偵測並動態調整

自建一組 evaluation set 測試它的可靠性（涵蓋不同網域與任務類型），在 Zeabur 部署可接收任務的介面。面試官會用自己設計的任務驗證它在未見過的情境下的表現。

**開發重點**：系統自我糾錯與自我維護的實質性（不是只做 try/except 重試）、evaluation set 的深度、silent failure 的防範。LLM agent要有能力可以來回迭代試錯實驗操作瀏覽器。

Build a browser agent that accepts **natural language task descriptions** and reliably executes them across different sites. Beyond basic execution, the agent should demonstrate:

- **Self-correction** — diagnose the cause on failure and try different strategies
- **Self-maintenance** — detect UI or selector changes and adjust locator strategies dynamically

Build your own evaluation set to test reliability (covering diverse domains and task types), and deploy on Zeabur with an interface that accepts tasks. Interviewers will verify with their own unseen tasks.

**Tips**: substance of the self-correction / self-maintenance mechanisms (not just try/except retries), depth of the evaluation set, silent-failure prevention.

---

## Task 3: SEC 10-K Item-level Structured Extraction 題目三：SEC 10-K 財報 Item-level 結構化抽取

10-K 有 SEC 規範的結構（Part I–IV 底下的 Item 1–16），但實際格式變異極大——HTML 不統一、標題寫法多元、舊格式是純文字、Part III 常「incorporated by reference」指向 Proxy、部分 item 為 Not Applicable 或 Reserved。

做一個 pipeline：輸入一份 10-K（CIK + accession 或檔案 URL），輸出結構化 JSON，每個 item 包含 `part`、`item_number`、`item_title`、`content_text`、`char_range`、`status`（`extracted` / `incorporated_by_reference` / `not_applicable` / `reserved`）。在 Zeabur 部署為 API，面試官會用自己挑選的 filings 呼叫它。

**資料來源（SEC 官方 API，免費）**：

- API 總覽：[https://www.sec.gov/search-filings/edgar-application-programming-interfaces](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- Submissions API：`https://data.sec.gov/submissions/CIK{10位補零}.json`
- Full-text Search：`https://efts.sec.gov/LATEST/search-index?q={query}&forms=10-K`
- 檔案下載：`https://www.sec.gov/Archives/edgar/data/{CIK}/{accession-去破折號}/{filename}`
- XBRL Company Facts（可用於交叉驗證）：`https://data.sec.gov/api/xbrl/companyfacts/CIK{10位補零}.json`
- 規範：需帶 `User-Agent` header、10 req/sec、無需 API key

請自建 evaluation set（涵蓋不同產業、年份、公司規模，包含一些舊格式），並報告準確度、失敗模式、以及成本/延遲。

**開發重點**：eval set 是否有刻意挑 edge case、解析策略的權衡（規則 vs LLM vs 混合）、在沒有公開 ground truth 下如何驗證自己、incorporated by reference 有沒有正確處理、成本紀律。

10-Ks have an SEC-specified structure (Items 1–16 across Parts I–IV), but actual file formats vary enormously — inconsistent HTML, diverse heading styles, older plain-text filings, "incorporated by reference" sections, "Not Applicable" / "Reserved" items.

Build a pipeline that takes a 10-K (by CIK + accession number or file URL) and outputs structured JSON, with each item containing `part`, `item_number`, `item_title`, `content_text`, `char_range`, and `status` (`extracted` / `incorporated_by_reference` / `not_applicable` / `reserved`). Deploy on Zeabur as an API — we will call it with our own selected filings.

**Data sources (SEC official APIs, free)**:

- API overview: [https://www.sec.gov/search-filings/edgar-application-programming-interfaces](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- Submissions API: `https://data.sec.gov/submissions/CIK{10-digit-padded}.json`
- Full-text Search: `https://efts.sec.gov/LATEST/search-index?q={query}&forms=10-K`
- Raw file downloads: `https://www.sec.gov/Archives/edgar/data/{CIK}/{accession-no-dashes}/{filename}`
- XBRL Company Facts (useful for cross-validation): `https://data.sec.gov/api/xbrl/companyfacts/CIK{10-digit-padded}.json`
- Rules: requires `User-Agent` header, 10 req/sec, no API key

Build your own evaluation set (diverse industries, years, company sizes, including older formats), and report accuracy, failure modes, and cost/latency.

**Important**: whether your eval set intentionally stresses edge cases, your parsing strategy tradeoffs (rules vs LLM vs hybrid), how you verify yourself without public ground truth, handling of "incorporated by reference" cases, cost discipline.

---

## How Evaluate 怎麼評分

Interviewers會用你 eval set 之外的資料跑 held-out 測試、閱讀你的 code、文件與 prompt 紀錄，並在面試中與你深入討論設計決策。

評分重點：eval 設計要有深度、系統能展現分層與權衡、失敗模式誠實、prompt 與commit紀錄需要可以看得出高品質的人與 AI 協作

Interviewers run held-out tests against your deployed system using data outside your eval set, read your code, documentation and prompt records, and discuss design decisions with you in the interview.

Interviewers will eval: design has depth, system shows layered/weighted tradeoffs, failure modes honestly surfaced, prompt records show high-quality AI collaboration


### Notes
1. 這個題目設計一大部分是在測驗你是否具有很強的系統架構與實作思維能力，能做出來只是基本分。面試官更多的是想看你在這三個tasks中你的思路與做法，是否能提出一些連公司主管都沒有想到的東西或優化方向? 優化方向不一定要真的做出來，但至少要有個方向，並且寫到repo中做補充。
2. AI 開發迭代得非常快，你需要上網搜尋以後盡可能運用一些比較前沿的想法，例如駕馭工程harness engineering等，這對你的實作會有蠻大幫助，並且要於repo中進行highlight與補充說明。
3. 如果你時做上有遇到任何問題歡迎隨時跟我說，讓我去跟面試官做溝通詢問! 如果有需要確認的地方，請你帶著答案或思路再讓我去問問題，我才能夠比較好拿到具體回覆喔，感謝。
4. 面試官設計這些題目的其中一個標準是「如果把這些東西直接讓 OpenClaw/HermesAgent 去做會怎麼樣」，希望你可以表現得比這些一般的LLM/Agents更加出色。請盡可能提供一些好的創新思路來實作。


## Submission 繳交

給出：公開 Git repo URL、各題 Zeabur URL、必要補充。祝好運。
Provide: public Git repo URL, Zeabur URL(s), and any supplementary notes. Good luck.

