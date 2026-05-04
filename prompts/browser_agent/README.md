# Browser Agent Prompts — Version Ledger

## Current: v1 (2026-05-04)

### v1_planner.txt
- **Purpose**: Decompose natural language task into JSON action sequence
- **Key design**: Uses semantic element descriptions (not CSS selectors)
- **Output**: JSON array of step objects with action, target, value, reasoning, success_criteria

### v1_actor.txt
- **Purpose**: Decide next action reactively from current page state
- **Key design**: Reads accessibility tree to find interactive elements
- **Output**: Single JSON action object

### v1_verifier.txt
- **Purpose**: Check if the task has been completed
- **Key design**: Strict verification with confidence scoring (0-1)
- **Output**: JSON with complete, answer, confidence

### v1_healer.txt
- **Purpose**: Diagnose failure root cause and suggest recovery
- **Key design**: 9-class root cause taxonomy (not just "retry")
- **Output**: Root cause classification + specific recovery strategy

## Design Rationale
- **AOM-first**: Prompts instruct LLM to use accessibility tree roles/names, not CSS selectors
- **Semantic descriptions**: "the search button" instead of "#btn-search" — survives UI redesigns
- **Confidence scoring**: Enables automated decision-making about when to heal vs. proceed
- **Structured output**: JSON format for reliable parsing (with fallback text parsing)
