# signal-foundry
Evaluation-first AI systems for Claude Skills, browser automation, and SEC 10-K extraction.
This repository is a public showcase of evaluation-first AI systems engineering: reusable Claude Skills, a browser automation agent with self-correction, and a hybrid SEC 10-K extraction pipeline.

## Project Overview
* AI reliability engineering demos: reusable skills, browser automation, and SEC 10-K extraction with eval-first design.
* A public showcase of harness engineering for Claude Skills, browser agents, and structured document extraction.
* Evaluation-first AI systems for skills orchestration, browser automation, and SEC filing extraction.
* harness first, eval first, observability first
* harness / eval / observability / tradeoffs / deployment

## What’s Included
* Task 1: GitHub CI/CD as Claude Skills
* Task 2: Generalized Browser Automation Agent
* Task 3: SEC 10-K Item-level Structured Extraction

## Task 3 API
Task 3 is implemented as a hybrid rule + optional LLM pipeline:

```bash
curl -X POST http://localhost:8080/api/v1/sec/extract \
  -H "Content-Type: application/json" \
  -d '{"cik":"0000320193","accession_number":"0000320193-23-000106","skip_llm":true,"skip_xbrl":true}'
```

The response returns item-level JSON with `part`, `item_number`, `item_title`, `content_text`, `char_range`, `status`, confidence, extraction method, validation metadata, cost, and latency.

Task 3 evals use official SEC identifiers and can be run with:

```bash
python -m evals.task3.run_eval --skip-xbrl
```


## Architecture
* 共用的 orchestrator / harness / evaluator / logging
* 每個 task 的子模組隔離
* Web UI / API / worker / prompts / eval set

## Design Decisions
* 為什麼採用 hybrid rules + LLM
* 為什麼要有 deterministic validation
* 為什麼要做 held-out eval set
* 怎麼處理 silent failure、selector drift、incorporated by reference、idempotency 這些風險

## Evaluation
* 怎麼測
*  metrics 是什麼
*  failure taxonomy 是什麼
*  有哪些 edge cases 被刻意納入 eval set

## AI Collaboration
* Claude Code / Skills / prompts 怎麼加速
* 哪些地方是 AI 協作，哪些地方是手動設計與把關
* 哪些 prompt 失敗過、你怎麼修正

## How to Run
* how to run, key design decisions, where LLM involved
* demo URL
* Zeabur URL

## Deployment
* 每個 service 的公開 URL
* 多個 endpoint用途

## Limitations / Next Steps
* 哪些地方還不完美
* 還想加什麼
* 工程判斷


