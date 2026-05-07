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