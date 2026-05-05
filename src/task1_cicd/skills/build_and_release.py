"""
Build and Release Skill.

Analyzes git commit history to determine the next semantic version,
generates a changelog, and optionally creates a GitHub release.

dry_run=True (default): returns a preview with identical schema but no side effects.
dry_run=False: creates an annotated tag and GitHub release via API.

Idempotency: checks if the computed tag already exists before creating it.
"""

from __future__ import annotations

import re
from typing import Optional

from src.shared.logger import get_logger
from src.task1_cicd import github_client
from src.task1_cicd.schemas import BuildAndReleaseResult, RepoContext

logger = get_logger("build_and_release")

# Conventional commits spec: https://www.conventionalcommits.org/
_BREAKING_RE = re.compile(r"BREAKING CHANGE|!:", re.IGNORECASE)
_FEAT_RE = re.compile(r"^feat(\([^)]+\))?(!)?:", re.IGNORECASE)
_FIX_RE = re.compile(r"^fix(\([^)]+\))?(!)?:", re.IGNORECASE)
_CHORE_RE = re.compile(r"^(chore|docs|style|refactor|perf|test|build|ci)(\([^)]+\))?(!)?:", re.IGNORECASE)


async def run(
    ctx: RepoContext,
    dry_run: bool,
    token: str,
) -> BuildAndReleaseResult:
    """
    Analyze commits → determine next version → changelog.
    If dry_run=True: return preview (no GitHub API write calls).
    If dry_run=False: create tag + release (idempotent).
    """
    owner, repo = ctx.owner, ctx.repo
    mode = "dry_run" if dry_run else "execute"

    logger.info("build_and_release_start", owner=owner, repo=repo, dry_run=dry_run)

    # Step 1: Get current latest tag
    current_tag = await github_client.get_latest_tag(owner, repo, token)
    logger.info("current_tag", tag=current_tag)

    # Step 2: Get commits since last tag
    commits = await github_client.get_commits_since_tag(owner, repo, current_tag, token)
    logger.info("commits_since_tag", count=len(commits))

    if not commits and current_tag:
        return BuildAndReleaseResult(
            mode=mode,
            status="skipped",
            current_version=current_tag,
            next_version=current_tag,
            version_bump="none",
            changelog="No new commits since last release.",
            commits_since_tag=0,
            notes="Nothing to release — HEAD is already tagged.",
        )

    # Step 3: Determine version bump
    bump_type, bump_reason = _determine_version_bump(commits)

    # Step 4: Compute next version
    next_version = _bump_semver(current_tag, bump_type)

    # Step 5: Build changelog
    changelog = _build_changelog(commits, current_tag, next_version)

    if dry_run:
        return BuildAndReleaseResult(
            mode="dry_run",
            status="success",
            current_version=current_tag,
            next_version=next_version,
            version_bump=bump_type,
            changelog=changelog,
            commits_since_tag=len(commits),
            release_url=None,
            tag_created=False,
            notes=f"Dry run. {bump_reason}. Run with dry_run=false to create the release.",
        )

    # Step 6: Create tag + release (dry_run=False only)
    if not token:
        return BuildAndReleaseResult(
            mode="execute",
            status="failed",
            current_version=current_tag,
            next_version=next_version,
            version_bump=bump_type,
            changelog=changelog,
            commits_since_tag=len(commits),
            notes="No GitHub token provided — cannot create release.",
        )

    try:
        release_url = await github_client.create_github_release(
            owner=owner,
            repo=repo,
            tag_name=next_version,
            name=f"Release {next_version}",
            body=changelog,
            commit_sha=ctx.commit_sha,
            token=token,
        )
    except github_client.FastFailError as e:
        return BuildAndReleaseResult(
            mode="execute",
            status="failed",
            current_version=current_tag,
            next_version=next_version,
            version_bump=bump_type,
            changelog=changelog,
            commits_since_tag=len(commits),
            notes=f"Release creation failed: {e}",
        )

    logger.info("release_created", tag=next_version, url=release_url)
    return BuildAndReleaseResult(
        mode="execute",
        status="success",
        current_version=current_tag,
        next_version=next_version,
        version_bump=bump_type,
        changelog=changelog,
        commits_since_tag=len(commits),
        release_url=release_url,
        tag_created=True,
    )


def _determine_version_bump(commits: list[dict]) -> tuple[str, str]:
    """
    Apply Conventional Commits rules to determine the version bump type.

    Rules (in priority order):
    1. Any commit with 'BREAKING CHANGE' in body or '!' in type → major
    2. Any commit with 'feat:' prefix → minor
    3. Otherwise → patch
    """
    has_breaking = False
    has_feat = False

    for c in commits:
        msg = c.get("message", "")
        if _BREAKING_RE.search(msg):
            has_breaking = True
            break
        if _FEAT_RE.match(msg):
            has_feat = True

    if has_breaking:
        return "major", "Breaking change detected in commit history"
    if has_feat:
        return "minor", "New feature commit(s) detected (feat:)"
    return "patch", "Only bug fixes and maintenance commits detected"


def _bump_semver(current: Optional[str], bump: str) -> str:
    """
    Parse current semver tag and increment by bump type.
    If no current tag, start at v0.1.0 for minor/major, v0.0.1 for patch.
    """
    if not current:
        if bump == "major":
            return "v1.0.0"
        elif bump == "minor":
            return "v0.1.0"
        return "v0.0.1"

    # Strip leading 'v'
    raw = current.lstrip("v")
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", raw)
    if not m:
        # Can't parse — start fresh
        return "v0.1.0"

    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))

    if bump == "major":
        return f"v{major + 1}.0.0"
    elif bump == "minor":
        return f"v{major}.{minor + 1}.0"
    else:
        return f"v{major}.{minor}.{patch + 1}"


def _build_changelog(
    commits: list[dict],
    current_tag: Optional[str],
    next_version: str,
) -> str:
    """
    Generate a Markdown changelog from commit list.
    Groups by: Features / Bug Fixes / Other
    """
    features: list[str] = []
    fixes: list[str] = []
    other: list[str] = []

    for c in commits:
        msg = c.get("message", "").strip()
        author = c.get("author", "")
        sha = c.get("sha", "")[:7]
        entry = f"- {msg} ({sha}) @{author}"

        if _FEAT_RE.match(msg):
            features.append(entry)
        elif _FIX_RE.match(msg):
            fixes.append(entry)
        else:
            other.append(entry)

    since_label = f"since {current_tag}" if current_tag else "initial release"
    lines = [f"## {next_version} — What's Changed ({since_label})\n"]

    if features:
        lines.append("### ✨ Features")
        lines.extend(features)
        lines.append("")

    if fixes:
        lines.append("### 🐛 Bug Fixes")
        lines.extend(fixes)
        lines.append("")

    if other:
        lines.append("### 🔧 Other Changes")
        lines.extend(other)
        lines.append("")

    if not commits:
        lines.append("_No changes detected._")

    return "\n".join(lines)
