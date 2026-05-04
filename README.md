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
* demo URL
* Zeabur URL

## Deployment
* 每個 service 的公開 URL
* 多個 endpoint用途

## Limitations / Next Steps
* 哪些地方還不完美
* 還想加什麼
* 工程判斷



