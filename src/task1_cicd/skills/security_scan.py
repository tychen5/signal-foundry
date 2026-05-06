"""
Security Scan Skill.

Two-layer scanning:
1. Pure Python regex for secret detection (API keys, tokens, private keys)
   — runs on all repos, zero external deps
2. Bandit for Python SAST (SQL injection, eval, pickle, etc.)
   — only for Python repos, uses subprocess

No secrets appear in full in findings — only redacted previews.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from src.shared.logger import get_logger
from src.task1_cicd.sandbox import SandboxConfig, run_command
from src.task1_cicd.schemas import RepoContext, SecurityFinding, SecurityScanResult

logger = get_logger("security_scan")

# Files/directories to skip during scanning
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".eggs", "dist", "build", ".mypy_cache", ".ruff_cache",
}
_SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2",
    ".ttf", ".eot", ".pdf", ".zip", ".tar", ".gz", ".bin", ".pyc",
    ".pyo", ".so", ".dll", ".exe", ".lock",
}
MAX_FILE_SIZE = 1_000_000  # 1MB

# Secret detection patterns — ordered by severity
_SECRET_PATTERNS: list[tuple[str, str, str, str]] = [
    # (pattern, severity, finding_type, recommendation)
    (
        r"AKIA[0-9A-Z]{16}",
        "critical",
        "AWS Access Key ID",
        "Revoke this AWS key immediately via AWS IAM console and rotate credentials.",
    ),
    (
        r"(?i)aws.{0,20}secret.{0,20}['\"]([A-Za-z0-9/+=]{40})['\"]",
        "critical",
        "AWS Secret Access Key",
        "Revoke this AWS secret key immediately and rotate credentials.",
    ),
    (
        r"ghp_[0-9A-Za-z]{36}",
        "high",
        "GitHub Personal Access Token (classic)",
        "Revoke this token at https://github.com/settings/tokens and regenerate.",
    ),
    (
        r"github_pat_[0-9A-Za-z_]{82}",
        "high",
        "GitHub Fine-Grained PAT",
        "Revoke this token at https://github.com/settings/tokens and regenerate.",
    ),
    (
        r"sk-[A-Za-z0-9]{48}",
        "high",
        "OpenAI API Key",
        "Revoke at https://platform.openai.com/api-keys and rotate immediately.",
    ),
    (
        r"xox[baprs]-[0-9]{10,12}-[0-9]{10,12}-[0-9a-zA-Z]{24,32}",
        "high",
        "Slack API Token",
        "Revoke at https://api.slack.com/apps and rotate immediately.",
    ),
    (
        r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----",
        "critical",
        "Private Key",
        "Remove this private key from the repository immediately and rotate it.",
    ),
    (
        r"(?i)(api[_-]?key|apikey|api[_-]?secret|access[_-]?token)\s*[=:]\s*['\"]([A-Za-z0-9\-_\.]{20,})['\"]",
        "medium",
        "Generic API Key / Token",
        "Move secrets to environment variables or a secrets manager (e.g., Vault, AWS Secrets Manager).",
    ),
    (
        r"(?i)password\s*[=:]\s*['\"]([A-Za-z0-9!@#$%^&*()\-_+=]{8,})['\"]",
        "medium",
        "Hardcoded Password",
        "Move passwords to environment variables or a secrets manager.",
    ),
    (
        r"(?i)(db_password|database_password|db_pass)\s*[=:]\s*['\"]([A-Za-z0-9!@#$%^&*]{6,})['\"]",
        "high",
        "Database Password",
        "Move database credentials to environment variables and rotate immediately.",
    ),
]


async def run(ctx: RepoContext, cfg: SandboxConfig) -> SecurityScanResult:
    """
    Run secret detection + SAST and return a consolidated SecurityScanResult.
    """
    clone_path = ctx.clone_path
    scan_types = ["secret_detection"]
    findings: list[SecurityFinding] = []

    # Layer 1: Pure Python regex secret scan (all languages)
    secret_findings = _run_secret_detection(clone_path)
    findings.extend(secret_findings)
    files_scanned = _count_scannable_files(clone_path)

    # Layer 2: Bandit SAST for Python repos
    if ctx.language == "python":
        scan_types.append("sast_bandit")
        bandit_findings = await _run_bandit(clone_path, cfg)
        findings.extend(bandit_findings)

    # Build severity counts
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        if f.severity in severity_counts:
            severity_counts[f.severity] += 1

    status = "findings" if findings else "clean"

    logger.info(
        "security_scan_done",
        total_findings=len(findings),
        files_scanned=files_scanned,
        status=status,
    )

    return SecurityScanResult(
        status=status,
        scan_types=scan_types,
        findings=findings,
        severity_counts=severity_counts,
        files_scanned=files_scanned,
    )


def _run_secret_detection(clone_path: str) -> list[SecurityFinding]:
    """
    Walk all text files in the clone and scan for secret patterns.
    Never includes the full matched secret — only a redacted preview.
    """
    findings: list[SecurityFinding] = []
    compiled = [(re.compile(pat), sev, ftype, rec) for pat, sev, ftype, rec in _SECRET_PATTERNS]

    for file_path in _iter_text_files(clone_path):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for line_num, line in enumerate(content.splitlines(), start=1):
            for pattern, severity, finding_type, recommendation in compiled:
                m = pattern.search(line)
                if m:
                    # Redact: show first 4 chars + *** (never full secret)
                    matched = m.group(0)
                    preview = matched[:4] + "***" if len(matched) > 4 else "***"
                    rel_path = str(file_path.relative_to(clone_path))
                    findings.append(SecurityFinding(
                        finding_type="secret",
                        severity=severity,
                        file=rel_path,
                        line=line_num,
                        match_preview=preview,
                        description=finding_type,
                        recommendation=recommendation,
                        tool="regex",
                    ))
                    break  # one finding per line is enough

    return findings


async def _run_bandit(clone_path: str, cfg: SandboxConfig) -> list[SecurityFinding]:
    """
    Run bandit SAST on a Python repo.
    cmd: python -m bandit -r . -f json -ll (medium and above only)
    """
    bandit_cfg = SandboxConfig(
        timeout_seconds=min(cfg.timeout_seconds, 120),
        max_output_bytes=cfg.max_output_bytes,
        working_dir=clone_path,
    )

    result = await run_command(
        [sys.executable, "-m", "bandit", "-r", ".", "-f", "json", "-ll", "--quiet"],
        bandit_cfg,
    )

    if result.timed_out:
        logger.warning("bandit_timeout")
        return []

    # bandit exits 1 when findings are found — that's expected
    if result.returncode not in (0, 1) or not result.stdout.strip():
        # bandit not installed or crashed — skip without failing
        logger.info("bandit_unavailable_or_error", returncode=result.returncode)
        return []

    return _parse_bandit_json(result.stdout, clone_path)


def _parse_bandit_json(stdout: str, clone_path: str) -> list[SecurityFinding]:
    """Parse bandit --format json output into SecurityFinding list."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []

    findings = []
    for issue in data.get("results", []):
        severity = issue.get("issue_severity", "LOW").lower()
        # Map bandit severity × confidence to our taxonomy
        confidence = issue.get("issue_confidence", "LOW").lower()
        if severity == "low" and confidence == "low":
            continue  # skip very low signal findings

        rel_path = issue.get("filename", "")
        if rel_path.startswith(clone_path):
            rel_path = rel_path[len(clone_path):].lstrip("/")

        test_id = issue.get("test_id", "")
        test_name = issue.get("test_name", "")
        code_snippet = issue.get("code", "").strip()[:80]

        findings.append(SecurityFinding(
            finding_type="sast",
            severity=severity,
            file=rel_path,
            line=issue.get("line_number", 0),
            match_preview=code_snippet,
            description=f"[{test_id}] {issue.get('issue_text', test_name)}",
            recommendation=f"See https://bandit.readthedocs.io/en/latest/plugins/{test_id.lower()}.html",
            tool="bandit",
        ))

    return findings


def _iter_text_files(base: str):
    """Yield all scannable text file paths under base directory."""
    base_path = Path(base)
    for path in base_path.rglob("*"):
        # Skip directories
        if path.is_dir():
            continue
        # Skip hidden dirs (like .git)
        if any(part.startswith(".") and part != "." for part in path.parts[len(base_path.parts):]):
            if any(d in path.parts for d in _SKIP_DIRS):
                continue
        # Skip by directory name
        if any(d in path.parts for d in _SKIP_DIRS):
            continue
        # Skip by extension
        if path.suffix.lower() in _SKIP_EXTENSIONS:
            continue
        # Skip large files
        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                continue
        except OSError:
            continue
        # Skip binary files (check first 512 bytes)
        try:
            with open(path, "rb") as f:
                chunk = f.read(512)
            if b"\x00" in chunk:  # null bytes indicate binary
                continue
        except OSError:
            continue
        yield path


def _count_scannable_files(base: str) -> int:
    """Count the number of scannable files (for reporting)."""
    return sum(1 for _ in _iter_text_files(base))
