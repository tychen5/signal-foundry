# Failure Analysis Prompts

## Purpose
Used by the Healer component (Task 2) and Reflexive Validator (Task 3)
to diagnose why an operation failed and suggest recovery strategies.

## v1: Browser Failure Diagnosis

```
Given a failed browser action, analyze the failure:

Action attempted: {action}
Error message: {error}
DOM snapshot (simplified): {dom_snippet}
Screenshot available: {has_screenshot}

Determine the failure category:
1. selector_mismatch — element exists but locator strategy failed
2. page_load — page didn't fully load or timed out
3. logic_error — wrong page or unexpected state
4. network — connection or resource loading issue
5. auth_required — login wall or permission denied
6. captcha — CAPTCHA or bot detection

Return JSON:
{
  "failure_category": "...",
  "root_cause": "...",
  "recovery_strategy": "...",
  "confidence": 0.0-1.0
}
```

## v2: SEC Extraction Validation

```
You are validating a 10-K item extraction. Check:
1. Does the item_title match standard SEC nomenclature?
2. Is the content_text consistent with what this item typically contains?
3. Does the status correctly identify incorporated_by_reference patterns?

Item: {item_json}
Source context (±200 chars around boundaries): {context}

Return JSON with validation result and any corrections needed.
```
