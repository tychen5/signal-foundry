# PLANS.md — Execution Plan Template

## Purpose

This template guides agents through multi-step work. When a task involves more than 3 files or requires careful sequencing, create an ExecPlan before writing code.

## ExecPlan Template

```markdown
# ExecPlan: [Title]

## Goal
One-sentence description of what this plan achieves.

## Pre-conditions
- [ ] Dependencies available
- [ ] Required API keys configured
- [ ] Related tests passing

## Steps

### Step 1: [Description]
- **Files**: list files to modify/create
- **Action**: what to do
- **Verify**: how to confirm step succeeded

### Step 2: [Description]
...

## Post-conditions
- [ ] All new tests pass
- [ ] Existing tests still pass
- [ ] Lint passes
- [ ] Cost tracker updated
- [ ] Documentation updated

## Rollback
How to undo if something goes wrong.
```

## When to Use

- Adding a new feature that spans multiple modules
- Refactoring shared infrastructure
- Adding a new skill or evaluation set
- Any change that could break existing functionality

## When NOT to Use

- Single-file bug fixes
- Documentation-only changes
- Adding a single test
- Formatting or lint fixes
