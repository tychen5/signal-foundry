# CI/CD Skills Prompt Ledger

Versioned prompt records for Task 1 (GitHub CI/CD as Claude Skills).

## Prompt Files

| File | Version | Usage | Template Variables |
|------|---------|-------|--------------------|
| `v1_skill_match.txt` | v1 | Skill name disambiguation (LLM fallback after exact+fuzzy match fails) | `{user_input}` |
| `v1_result_summary.txt` | v1 | Convert structured JSON result to 2-3 sentence prose summary | `{skill_name}`, `{result_json}` |
| `v1_auto_router_plan.txt` | v1 | **Auto-Router PLAN stage**: NL query → ordered skill plan + per-skill rationale + intent paraphrase | `{user_query}`, `{repo_url}`, `{branch}`, `{dry_run}`, `{max_skills}`, `{include_hint}`, `{exclude_hint}` |
| `v1_auto_router_decide.txt` | v1 | **Auto-Router POSTMORTEM stage**: after each skill, decide continue / add_skill / stop | `{user_query}`, `{overall_intent}`, `{repo_url}`, `{branch}`, `{original_plan}`, `{executed_skills}`, `{remaining_plan}`, `{iterations_used}`, `{max_iterations}`, `{cost_usd}`, `{budget_cap_usd}`, `{last_skill}`, `{last_status}`, `{last_summary}`, `{last_findings_compact}`, `{exclude_hint}` |
| `v1_auto_router_synthesize.txt` | v1 | **Auto-Router SYNTHESIZE stage**: cross-skill 1-paragraph answer tied to the user's question | `{user_query}`, `{repo_url}`, `{branch}`, `{executed_skills}`, `{per_skill_summaries}`, `{total_lint_issues}`, `{total_test_failures}`, `{total_cves}`, `{total_outdated}`, `{total_secrets}`, `{total_sast}` |

## Touch Points (Where LLM is Called)

LLM is used at these points in the Task 1 pipeline:

### Single-skill mode (`/api/v1/skills/run`) — at most 2 LLM calls

1. **Skill matching** (`skill_registry._llm_match`)
   - Only called when exact match AND fuzzy token overlap BOTH fail
   - Input: raw user request string (e.g., "check my code for leaked API tokens")
   - Output: `{"skill": "security-scan", "confidence": 0.92, "reasoning": "..."}`
   - Temperature: 0.0 (deterministic)
   - Estimated cost: ~200 tokens in, ~50 tokens out ≈ $0.0005

2. **Result summarization** (`skill_engine._llm_summarize`)
   - Called after every successful skill execution
   - Input: skill name + structured result JSON (trimmed to ≤2000 chars)
   - Output: 2-3 sentence human-readable summary
   - Temperature: 0.3
   - Estimated cost: ~800 tokens in, ~100 tokens out ≈ $0.003

**Total LLM cost per single-skill request**: $0.001–$0.004 (rule matching hits avoid the first call entirely).

### Auto-Router mode (`/api/v1/skills/auto/run`) — variable (typically 3–6 LLM calls)

The auto-router runs 1× **plan** (only when an NL query is provided), *N*× **postmortem** (one per executed skill before the last one), 1× **synthesize**, plus the existing per-skill **summary** the engine writes for each underlying execution.

| Stage | Prompt | Calls per request | Why |
|---|---|---|---|
| Plan | `v1_auto_router_plan.txt` | **1 if NL query present, 0 if chip-only mode** | Pick the ordered skill set from the NL query. Skipped entirely when the user supplies only chips — the include hints ARE the plan in that case |
| Skill execution + per-skill summary | `v1_result_summary.txt` (re-used) | N (= `len(executed_skills)`) | Same path as single-skill mode |
| Postmortem | `v1_auto_router_decide.txt` | N − 1 typically (last iteration may skip if iteration cap or budget cap hits) | Decide continue / pivot / stop |
| Synthesize | `v1_auto_router_synthesize.txt` | 1 | Tie all skill outputs back to the user's question |

For a typical 2-skill auto-router run: 1 plan + 2 summaries + 1 postmortem + 1 synthesize = **5 LLM calls** ≈ $0.005–$0.015 depending on the model.

**Chip-only (empty NL query) mode** saves the plan call: 0 plan + 2 summaries + 1 postmortem + 1 synthesize = **4 LLM calls**. The chips themselves are the deterministic plan, so the planner LLM has nothing useful to add — this is a strict cost win, not a fidelity trade-off. The decide- and synthesize-stage prompts receive a synthesized `{user_query}` substitute string (e.g. *"User did not provide a free-form query; running the user-selected skill set: security-scan."*) so they still have something coherent to read.

The default per-request budget cap (`cost_tracker.DEFAULT_BUDGET_CAP_USD["task1_cicd"]`) is **$0.30**, well above any of these modes.

## Version History

### v1_skill_match.txt (current)
- **Created**: Initial implementation
- **Strategy**: Present all 4 skills with trigger phrases, ask for JSON output
- **Eval result**: 100% accuracy on 5 known cases; tested on 10 adversarial inputs (8/10 correct)
- **Known failure**: "scan my code" routes to lint-and-test (ambiguous) — v2 will add disambiguation question

### v1_result_summary.txt (current)
- **Created**: Initial implementation
- **Strategy**: Structured result JSON → 2-3 sentence prose with action item
- **Known failure**: When result is very sparse (no issues found), LLM may produce generic "all clear" message; acceptable for demo

### v1_auto_router_plan.txt (current)
- **Created**: Phase 10 — Auto-Router roll-out
- **Strategy**:
  - Present all four skills with one-line descriptions and "use for" trigger guidance.
  - Hard-list the canonical skill names so the model can't hallucinate skill identifiers.
  - Encode the cost-discipline rule directly: "Don't pad. Smallest set that covers intent."
  - Encode the safety rule directly: "build-and-release LAST when scheduled."
  - Encode the hint contract: include = soft suggestion, exclude = hard block.
  - Force a strict JSON schema (`plan`, `rationale_per_skill`, `overall_intent`, `confidence`).
  - Provide a degenerate fallback (`["dependency-audit", "security-scan"]`) so the model has a safe default for ultra-vague queries — but the Python `_sanitise_plan` reproduces the same fallback as defence in depth.
- **Why each clause is in the prompt**:
  - "smallest" rule was added because GPT-style routers love to do every action; on the eval set this cut average plan length from 3.1 to 2.0 skills without losing coverage.
  - "build-and-release LAST" was added because thinking-mode models (DeepSeek-V4-Pro) sometimes put it first and the loop's defensive write-skill gate would then waste a postmortem call to discover this.

### v1_auto_router_decide.txt (current)
- **Created**: Phase 10 — Auto-Router roll-out
- **Strategy**:
  - Three-action vocabulary: `continue` / `add_skill` / `stop`. Anything else gets coerced to `stop` server-side.
  - "Be aggressive about stopping" line — without this the router routinely picked `continue` even when remaining_plan was empty (then we'd hit `plan_exhausted` anyway).
  - Hard-codes the budget heuristic: "if iterations_used ≥ max_iterations − 1 OR cost_usd ≥ 0.8 × budget_cap, you MUST pick stop." Saves a final-iteration LLM call when we're already near the cap.
  - Repeats the canonical skill list and exclude-hint rule so the model can't smuggle in an excluded skill via `add_skill`.
- **Defence-in-depth**: the Python `_llm_decide` post-filters `next_skill` against `VALID_SKILLS`, `executed_skills`, `exclude_hint`, and the write-capable + release-intent gate. Even if the prompt fails, the loop is safe.

### v1_auto_router_synthesize.txt (current)
- **Created**: Phase 10 — Auto-Router roll-out
- **Strategy**:
  - Open with a one-sentence direct answer. No hedging — measured this against an "open with a summary" variant on the eval set; direct-answer was rated higher by the LLM-as-judge in 9/10 cases.
  - Provides aggregate signals (total CVEs, total secrets, etc.) so the model doesn't have to re-aggregate from per-skill summaries.
  - "Never invent findings" is explicit because thinking-mode models occasionally extrapolate from the summary text alone.
  - "If skills returned conflicting signals, surface the conflict" prevents the router from averaging away a critical signal (e.g. "tests pass" + "critical CVE" should not become "mostly fine").
- **Output is plain prose** so the FE can drop it into the synthesis card without parsing markdown.

## Future Versions

- **v2_skill_match.txt**: Add few-shot examples for ambiguous cases; add explicit disambiguation for "security" vs "dependencies" when user says "scan".
- **v2_result_summary.txt**: Add skill-specific output templates so LLM focuses on the right fields (e.g., for dependency-audit, always mention CVE IDs).
- **v2_auto_router_plan.txt**: Add few-shot examples covering the trickiest queries from the live demo:
  - "is this safe to ship?" → `[dependency-audit, security-scan]` (NOT lint-and-test, NOT build-and-release without explicit ship intent)
  - "do a full health check" → `[dependency-audit, security-scan, lint-and-test]` in that order
  - "scan deps and secrets" → both, but stop early if the first finds nothing
- **v2_auto_router_decide.txt**: Surface a "diminishing-returns" heuristic — if the prior 2 skills both returned `clean`/`success` and `remaining_plan` is non-empty, prefer `stop` over `continue`.
- **v2_auto_router_synthesize.txt**: Switch to a **structured output** (open with a 1-sentence verdict, then a bulleted list of skill→finding pairs) so the FE can render a nicer card. Currently flat prose because that's the most reliable shape across thinking + non-thinking models.
