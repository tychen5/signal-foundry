# Signal-Foundry Task Tracker

## Phase 0: Skeleton + Documentation + Shared Infra
- [x] Create repo skeleton (all directories)
- [x] Write .env.example
- [x] Write pyproject.toml + requirements.txt
- [x] Write CLAUDE.md
- [x] Write AGENTS.md
- [x] Write PLANS.md
- [x] Write code_review.md
- [x] Write architecture_design_spec.md
- [x] Write zbpack.json + Dockerfile
- [x] Implement src/config.py (model registry, env vars)
- [x] Implement src/llm_provider.py (OpenRouter + NVIDIA factory)
- [x] Implement src/shared/ (harness, evaluator, cost_tracker, logger, schemas)
- [x] Implement src/main.py (FastAPI unified entry)
- [x] 4 Claude Skills SKILL.md files created
- [x] 3 task routers with skeleton endpoints
- [x] Eval sets created (5 T1 + 8 T2 + 8 T3)
- [x] Prompt records created (4 versioned prompt files)
- [x] Dashboard template + CSS
- [x] All 18 tests passing

## Phase 1: Task 3 — SEC 10-K Extraction
- [x] Implement src/task3_sec/fetcher.py
- [x] Implement src/task3_sec/normalizer.py
- [x] Implement src/task3_sec/rule_parser.py
- [x] Implement src/task3_sec/llm_refiner.py
- [x] Implement src/task3_sec/validator.py
- [x] Implement src/task3_sec/xbrl_client.py
- [x] Implement src/task3_sec/pipeline.py
- [x] Implement src/task3_sec/router.py
- [x] Create evals/task3/ eval set
- [ ] Create templates/task3.html

## Phase 2: Task 2 — Browser Automation Agent
- [ ] Implement src/task2_browser/browser_tools.py
- [ ] Implement src/task2_browser/locator_strategy.py
- [ ] Implement src/task2_browser/planner.py
- [ ] Implement src/task2_browser/executor.py
- [ ] Implement src/task2_browser/healer.py
- [ ] Implement src/task2_browser/state_tracker.py
- [ ] Implement src/task2_browser/agent.py
- [ ] Implement src/task2_browser/router.py
- [ ] Create evals/task2/ eval set
- [ ] Create templates/task2.html

## Phase 3: Task 1 — CI/CD Skills
- [ ] Write .claude/skills/lint-and-test/SKILL.md
- [ ] Write .claude/skills/build-and-release/SKILL.md
- [ ] Write .claude/skills/dependency-audit/SKILL.md
- [ ] Write .claude/skills/security-scan/SKILL.md
- [ ] Implement src/task1_cicd/skill_engine.py
- [ ] Implement src/task1_cicd/skill_registry.py
- [ ] Implement src/task1_cicd/github_client.py
- [ ] Implement src/task1_cicd/sandbox.py
- [ ] Implement src/task1_cicd/router.py
- [ ] Create evals/task1/ eval set
- [ ] Create templates/task1.html

## Phase 4: Polish + Deploy
- [ ] Write prompts/ versioned prompt records
- [ ] Complete README.md with arch diagram, tradeoffs, AI collab log
- [ ] Run all eval sets and generate reports
- [ ] Deploy to Zeabur
- [ ] Final verification
