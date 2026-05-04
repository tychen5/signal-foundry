# Skill Design Prompts

## v1: Initial Claude Skill Description

**Goal**: Write trigger-accurate SKILL.md descriptions for 4 CI/CD skills.

**Prompt used**:
```
You are designing Claude Skills (SKILL.md) for GitHub CI/CD automation.
For each skill below, write a YAML frontmatter description that:
1. Clearly states what the skill does
2. Lists specific trigger phrases users might say
3. Specifies security scope (read-only vs write)

Skills: lint-and-test, build-and-release, dependency-audit, security-scan
```

**Result**: Initial descriptions were too vague — Claude would trigger lint-and-test
when user asked about "code" in general. Needed more specific trigger conditions.

## v2: Refined with Exclusion Criteria

**Change**: Added negative examples ("do NOT trigger when...") and scope limits.
**Impact**: Mis-trigger rate dropped from ~30% to <5% in manual testing.
