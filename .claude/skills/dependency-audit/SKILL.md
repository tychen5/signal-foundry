---
name: dependency-audit
description: >
  Audits project dependencies for known vulnerabilities, outdated packages,
  and license compliance. Use when user says "audit deps", "check vulnerabilities",
  "update packages", "security audit", "CVE check", or "dependency scan".
  Read-only operation — reports findings without making changes.
---

# Dependency Audit Skill

## Purpose
Scan project dependencies for security vulnerabilities, outdated versions,
and license compliance issues.

## Inputs
- `repo_url` (required): GitHub repository URL
- `severity_threshold` (default: "medium"): Minimum severity to report (low/medium/high/critical)
- `include_dev` (default: true): Include dev dependencies in audit

## Outputs
```json
{
  "execution_id": "ghi789",
  "status": "clean | warnings | vulnerabilities_found",
  "total_dependencies": 45,
  "vulnerabilities": [
    {
      "package": "requests",
      "current_version": "2.28.0",
      "fixed_version": "2.31.0",
      "severity": "high",
      "cve": "CVE-2023-32681",
      "description": "Unintended leak of Proxy-Authorization header"
    }
  ],
  "outdated": [
    {
      "package": "numpy",
      "current": "1.24.0",
      "latest": "1.26.4"
    }
  ],
  "license_issues": []
}
```

## Security Boundary
- **Read-only**: Does not modify any dependency files
- **No execution**: Does not install packages — analyzes lock files only
- **Offline-capable**: Uses vulnerability databases, not live package installs

## Idempotency
Same repo + same lock file hash = same results.

## Workflow
1. Detect package manager (pip/poetry/npm/yarn)
2. Parse dependency lock file
3. Cross-reference against vulnerability databases (OSV, NVD)
4. Check for outdated versions
5. Scan licenses for compatibility
6. Generate prioritized report (critical → low)
