---
name: security-scan
description: >
  Scans repository for security issues: hardcoded secrets, SAST findings,
  and common vulnerability patterns. Use when user says "scan for secrets",
  "SAST", "check CVEs", "security scan", "find leaked keys", or
  "check for hardcoded credentials". Read-only static analysis.
---

# Security Scan Skill

## Purpose
Perform static security analysis on repository code to find hardcoded
secrets, common vulnerability patterns, and security anti-patterns.

## Inputs
- `repo_url` (required): GitHub repository URL
- `scan_type` (default: "full"): "secrets" | "sast" | "full"
- `exclude_patterns` (optional): File patterns to skip (e.g., ["*.test.*", "docs/*"])

## Outputs
```json
{
  "execution_id": "jkl012",
  "status": "clean | findings",
  "scan_type": "full",
  "findings": [
    {
      "type": "hardcoded_secret",
      "severity": "critical",
      "file": "config.py",
      "line": 42,
      "description": "Possible API key detected",
      "recommendation": "Move to environment variable"
    },
    {
      "type": "sql_injection",
      "severity": "high",
      "file": "db/queries.py",
      "line": 15,
      "description": "String formatting in SQL query",
      "recommendation": "Use parameterized queries"
    }
  ],
  "summary": {
    "critical": 1,
    "high": 1,
    "medium": 0,
    "low": 2,
    "info": 3
  }
}
```

## Security Boundary
- **Read-only**: Static analysis only — no code execution
- **Pattern-based**: Uses regex and AST analysis, not runtime testing
- **No exfiltration**: Findings stay local, never sent to external services
- **Configurable scope**: Can exclude test files, docs, and vendor code

## Idempotency
Same repo + same commit = same findings.

## Workflow
1. Clone repository (shallow)
2. Secret detection: scan for API keys, tokens, passwords using pattern matching
3. SAST: analyze code for common vulnerabilities (SQL injection, XSS, path traversal)
4. Configuration review: check for insecure defaults
5. Dependency cross-reference with known CVEs
6. Generate prioritized findings report
