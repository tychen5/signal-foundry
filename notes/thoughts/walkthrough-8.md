# Phase 10 Finalization — Walkthrough

## Summary

Audited all Phase 10 TODO items in `progress_notes.md`, verified the backend implementations (items 10.1 and 10.2 were already fully implemented), fixed remaining gaps (items 10.3 and 10.4), and marked everything as complete.

## Changes Made

### 1. Task 2 Vision Auto-Toggle + cnyes Replacement
**File**: `templates/task2.html`
- Added `syncVisionDefault()` — auto-checks the "Use vision" checkbox when the selected model is an OpenRouter model (vision-capable) AND the user has an OpenRouter API key entered. Only auto-checks, never auto-unchecks.
- Replaced the cnyes (鉅亨網) example button with TWSE Yahoo Finance (`tw.stock.yahoo.com/t/idx.php`) — CAPTCHA-free and reliable for fetching the TAIEX weighted index.

### 2. Index Page Quick Launchpad Redesign
**Files**: `templates/index.html`, `static/style.css`
- Redesigned the quick-launchpad from flat link buttons → rich mini-cards with icon, title, and description (`.quick-grid` / `.quick-card` CSS).
- 6 cards: Skill Registry, Apple 10-K Filings, Company Info, Live Metrics, Model Registry, API Docs.
- Footer deduplicated: removed Metrics/Models links (now in launchpad), keeping only Health + API Docs.
- Hero stat updated: `289` → `351` unit tests.

### 3. NVIDIA Key Persistence
**Files**: `templates/task1.html`, `templates/task3.html`
- Added `sf_nvidia_key` sessionStorage persistence in `hydrateSharedControls()` on both task pages (task2 already had it).

### 4. Progress Notes
**File**: `notes/progress/progress_notes.md`
- All Phase 10 items marked `[x]` with detailed verification notes.
- Final audit stats updated: 351 tests, 89 eval cases, Phases 0–10 complete.

### 5. CSS Lint Fix
**File**: `static/style.css`
- Added standard `background-clip: text` property alongside `-webkit-background-clip: text`.

## Verification

| Check | Result |
|-------|--------|
| `pytest tests/ -q` | **351 passed**, 7 skipped |
| `ruff check src/ tests/` | All checks passed |
| CSS lint | Fixed (background-clip) |


---

完成 Phase 10 的 5/6/7 強化。

主要變更：

Task1/Task2/Task3 子頁都補上「preset dropdown + free-text model id」雙控件，支援 OpenRouter/NVIDIA 預設模型與任意 publisher/model 輸入。
Task3 UI 現在偵測 OpenRouter model/key 後會自動開 force_llm + use_vision、關閉 skip_llm，並顯示 latency/cost 提醒。
Task2 TAIEX demo 已改成空 Start URL + 指定中文 query，planner fallback 不再允許 0-step plan。
Task2 TAIEX 路徑改為目前可用的 Yahoo %5ETWII quote route，避開 legacy tw.stock.yahoo.com/t/idx.php 的 Edge Too Many Requests。
Browser Agent prompts 已加強：planner 不可輸出 []；actor 遇到 finance rate limit / Google CAPTCHA 時會嘗試替代公開路徑。
README API Reference 已補上 no-start-URL Task2 範例與 Task3 OpenRouter high-accuracy mode 範例。
notes/progress/progress_notes.md Phase 10 的 5/6/7 已更新為完成並記錄 live 驗證結果。
實測：

openai/gpt-5.5 跑 TAIEX 任務：success，5 steps。
google/gemini-3.1-pro-preview 跑 TAIEX 任務：success，4 steps。
ruff check src tests：passed。
python -m pytest tests/ -q：354 passed, 7 skipped。

---

### 完成 Phase 10 的 6(sub) / 8 最後收尾

- **Task3 pipeline tradeoff advisory**: 在 Pipeline Options 區塊下方新增靜態提示文字，告知使用者「Force LLM refine + Use vision 增加準確度但增加 latency (~30–120 s) 與 cost (~$0.01–0.05)，如果更在意 latency/cost 建議取消勾選，rule-only 模式 $0 / <5 s」。
- **NVIDIA key expiration messaging**: 在全部 4 個頁面 (index, task1, task2, task3) 強化 NVIDIA key 提醒文字，明確指出「server-bundled key may be expired or rate-limited」，建議使用者自行至 build.nvidia.com 申請免費 key。
- **Hero stat**: 354 unit tests (from 351)。
- **progress_notes.md**: Phase 10 所有 items (1–8) 全部 `[x]`。

本次調整


把全域預設模型改為 openai/gpt-5.5

檔案: config.py



首頁在沒有既有 session 設定時，會強制預設選到 openai/gpt-5.5，並寫入 sf_model_id

檔案: index.html



Task1/Task2/Task3 的 model preset 與輸入框預設都改為 openai/gpt-5.5，NVIDIA 模型改成 fallback（NVIDIA free — Kimi K2.6）

檔案: task1.html

檔案: task2.html

檔案: task3.html



行為驗證（實測）

用本機啟動服務後，以 Playwright 做端到端驗證，結果如下：

首頁預設模型: openai/gpt-5.5
首頁未填 key 時提示: 會顯示 OpenRouter key 必填，並提示可改用 NVIDIA 模型
填入 OpenRouter key 後進 Task2:

model-select = openai/gpt-5.5，Use vision (multi-modal) = checked
填入 OpenRouter key 後進 Task3:

model-select = openai/gpt-5.5，Force LLM refine = checked，Use vision for uncertain boundaries = checked

檢查


ruff check src/config.py 通過