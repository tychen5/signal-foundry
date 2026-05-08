# Browser Agent Prompts — Version Ledger

## Active: v3 (2026-05-08, vision-aware) → v2 → v1 fallback

The agent loads the latest version present on disk via `_load_prompt_versioned()` in `src/task2_browser/planner.py`. Currently shipping:

| Stage | Active version | Notes |
|---|---|---|
| planner | v3_planner.txt | STRICT JSON-only output (no markdown fences); domain-hint handling for "前往鉅亨網" style tasks; visual-content prompt anticipation |
| actor | v3_actor.txt | Multi-screenshot timeline reasoning; visual-only element interpretation |
| verifier | v3_verifier.txt | Strict numeric grounding + multi-field completion |
| healer | v2_healer.txt | 13-class root-cause taxonomy (`should_retry` strictness) |

### v3 (2026-05-08) — what changed vs v2
- v3_planner.txt: added STRICT JSON-only output rule (matches the new `extract_json_object` parser in `src/shared/llm_utils.py`); added "domain hint without URL" example for live-data tasks where the user names a site (鉅亨網, cnyes) but no URL — e.g. previously the cnyes demo button hard-coded `https://www.cnyes.com/twstock/twse/TWSE.htm` which is dead, now the planner is asked to find a working URL via Google search.
- v3_actor.txt: existing — multi-screenshot timeline reasoning with explicit instructions for change detection across consecutive viewports.
- v3_verifier.txt: existing — stricter completion gate.

The frontend now ALSO uses `extract_json_object` to parse responses, so even if the model accidentally includes a ```json fence (despite the v3 instructions), the parser recovers gracefully.

### v2_planner.txt — what changed vs v1
- Added explicit anti-hallucination rules (numeric answers must be quotable from page text)
- Added planning-time popup/cookie-banner anticipation (saves a healer round trip on EU + news sites)
- Added SPA wait guidance (`wait 2000` after async-triggering clicks)
- Cap at 12 steps (loop / runaway prevention)
- Added explicit "predict failure points" section for live-data finance tasks (TWSE, cnyes, Yahoo)

### v2_actor.txt — what changed vs v1
- "Anti-hallucination rules (CRITICAL)" section: extracted answers MUST be quotable from `visible_text` or accessibility_tree
- For numeric answers, the EXACT number must appear on the observed page (no approximations)
- Explicit not-found handling: `done` with `value="not_found: <reason>"` rather than guessing
- Login-wall / paywall / 404 → `done` with `value="not_accessible: <category>"` rather than retrying

### v2_verifier.txt — what changed vs v1
- Re-cast as a STRICT verifier (the bar for `complete=true` is high)
- Numeric grounding requirement: exact number must appear in visible_text
- Negative-result honesty: `complete=true, answer="not_found"` is correct, not failure
- Multi-field tasks require ALL requested fields before complete=true
- Examples for each anti-hallucination case

### v2_healer.txt — what changed vs v1
Added 4 new root cause categories on top of v1's 9-class taxonomy:
- `rate_limit_429` — 429 from upstream LLM API → wait + retry, or mark degraded
- `login_wall` — sign-in required → set should_retry=false, mark not_accessible
- `paywall` — pay-to-read overlay → set should_retry=false, mark not_accessible
- `frame_detached` — "Target page closed" / "Frame detached" mid-action → re-observe (navigation may have completed)

The structured output schema is now stricter (`should_retry` boolean tells the agent whether to stop completely).

### Why v2 was needed
v1 was too lenient about the `done` action. The Task 2 live eval surfaced:
- 5/17 cases where the LLM was happy to mark a task complete when it had no real answer
- Numeric tasks (TWSE 實收資本額, cnyes 加權指數) where the model would output a plausible-looking number not actually on the page
- Login-wall pages getting infinite retry instead of being correctly marked unreachable

v2 hardens these boundaries with explicit rules and few-shot examples for the failure modes.

## v1 Archive (2026-05-04)

Kept on disk for auditability:
- v1_planner.txt — Original plan decomposition prompt
- v1_actor.txt — Original reactive next-action prompt
- v1_verifier.txt — Original task-completion verifier
- v1_healer.txt — Original 9-class root cause diagnoser

## Design Rationale (cross-cutting)

- **AOM-first**: All prompts instruct LLM to use accessibility-tree roles/names, never CSS selectors
- **Semantic descriptions**: "the search button" not "#btn-search" — survives UI redesigns
- **Confidence scoring**: Enables the agent to decide when to heal vs. proceed
- **Structured JSON output**: With deterministic fallback parsing if JSON fails
- **Anti-hallucination > completion-rate**: The cost of a fabricated answer is much higher than the cost of an extra step or honest "not_found"
