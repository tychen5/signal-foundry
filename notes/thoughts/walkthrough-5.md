主要改動：


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