# Prompt Engineering Records

This directory contains versioned prompts used across all three tasks.
Interviewers will read these to understand our AI collaboration process.

## Structure

```
prompts/
├── v1_initial/          # First-draft prompts — naive approaches
├── v2_refined/          # After discovering failure modes
├── v3_production/       # Production-grade with constraints & few-shot
├── skill_design.md      # Prompts used for Claude Skill creation
├── agent_planning.md    # Prompts for browser agent task decomposition
├── failure_analysis.md  # Prompts for diagnosing failures
└── eval_design.md       # Prompts for evaluation set creation
```

## Iteration Log

Each prompt version documents:
1. What the prompt was trying to achieve
2. What failure mode prompted the revision
3. What was changed and why
4. Eval results before and after

This transparency shows genuine human-AI collaboration, not one-shot generation.
