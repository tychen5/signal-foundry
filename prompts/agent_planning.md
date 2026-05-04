# Agent Planning Prompts

## v1: Naive Task Decomposition

**Goal**: Have LLM break down a natural language browser task into executable steps.

**Prompt**:
```
Given a browser task description, break it into a sequence of steps.
Each step should be one atomic action: click, type, navigate, scroll, or wait.

Task: {task_description}
Current URL: {current_url}

Output as JSON array of steps.
```

**Problem**: LLM would generate steps assuming specific CSS selectors exist.
When selectors didn't match, the agent would fail silently.

## v2: AOM-first with Fallback Strategy

**Change**: Instructed LLM to describe elements semantically (by role + text)
instead of by selector. Added mandatory success verification per step.

**Prompt**:
```
You are planning browser actions. For each step:
1. Describe the target element by its ROLE and VISIBLE TEXT (not by CSS selector)
2. Specify what SUCCESS looks like after this action
3. Specify what to do if the element is NOT FOUND

Example:
{
  "action": "click",
  "target": {"role": "button", "text": "Sign In"},
  "success_signal": "URL changes to /dashboard",
  "fallback": "Look for link with text 'Log In' or 'Login'"
}
```

**Impact**: Self-correction rate improved from 20% to 65% on eval set.
