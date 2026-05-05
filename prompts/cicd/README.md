# CI/CD Skills Prompt Ledger

Versioned prompt records for Task 1 (GitHub CI/CD as Claude Skills).

## Prompt Files

| File | Version | Usage | Template Variables |
|------|---------|-------|--------------------|
| `v1_skill_match.txt` | v1 | Skill name disambiguation (LLM fallback after exact+fuzzy match fails) | `{user_input}` |
| `v1_result_summary.txt` | v1 | Convert structured JSON result to 2-3 sentence prose summary | `{skill_name}`, `{result_json}` |

## Touch Points (Where LLM is Called)

LLM is used at exactly **two** points in the Task 1 pipeline:

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

**Total LLM cost per request**: $0.001–$0.004 (rule matching hits avoid the first call entirely)

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

## Future Versions

- **v2_skill_match.txt**: Add few-shot examples for ambiguous cases; add explicit disambiguation for "security" vs "dependencies" when user says "scan"
- **v2_result_summary.txt**: Add skill-specific output templates so LLM focuses on the right fields (e.g., for dependency-audit, always mention CVE IDs)
