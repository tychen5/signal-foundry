"""
GitHub Client for CI/CD Skills.

Provides authenticated GitHub API access and shallow git clone operations.
Uses PyGithub for API calls and subprocess for git clone (PyGithub doesn't
support shallow clones natively).

Security: GitHub token is embedded in clone URL and immediately replaced
with *** in all log messages — never appears in logs.
"""

from __future__ import annotations

import re
from typing import Optional

from src.shared.logger import get_logger
from src.task1_cicd.sandbox import SandboxConfig, run_command

logger = get_logger("github_client")

# Matches https://github.com/owner/repo or https://github.com/owner/repo.git
_GITHUB_URL_RE = re.compile(
    r"https?://(?:[^@/]+@)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$"
)


class FastFailError(Exception):
    """Non-retryable error — bad input or missing resource."""

    def __init__(self, message: str, error_code: str = "unknown") -> None:
        super().__init__(message)
        self.error_code = error_code


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    """
    Parse a GitHub URL into (owner, repo) tuple.

    Raises FastFailError if URL is not a valid GitHub repo URL.
    """
    m = _GITHUB_URL_RE.match(repo_url.strip())
    if not m:
        raise FastFailError(
            f"Not a valid GitHub repo URL: {repo_url}",
            error_code="invalid_repo_url",
        )
    owner, repo = m.group(1), m.group(2)
    return owner, repo


def _make_authenticated_url(owner: str, repo: str, token: Optional[str]) -> str:
    """Build a GitHub HTTPS clone URL with optional token auth."""
    if token:
        return f"https://{token}@github.com/{owner}/{repo}.git"
    return f"https://github.com/{owner}/{repo}.git"


def _redact_token(url: str) -> str:
    """Replace any embedded token in a URL with *** for logging."""
    return re.sub(r"https://[^@]+@github\.com", "https://***@github.com", url)


async def validate_repo(
    repo_url: str,
    token: Optional[str] = None,
) -> dict:
    """
    Validate that a GitHub repo exists and is accessible.

    Returns: {"owner": str, "repo": str, "default_branch": str, "private": bool}
    Raises FastFailError(REPO_NOT_FOUND) on 404 or auth failure.
    """
    import httpx

    owner, repo = parse_repo_url(repo_url)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    logger.info("validate_repo", owner=owner, repo=repo)

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(api_url, headers=headers)
        except httpx.RequestError as e:
            raise FastFailError(f"Network error reaching GitHub API: {e}", error_code="network_error") from e

    if resp.status_code == 404:
        raise FastFailError(
            f"Repository not found: {owner}/{repo}",
            error_code="repo_not_found",
        )
    if resp.status_code == 403:
        raise FastFailError(
            f"Access denied to {owner}/{repo}. Check your GitHub token.",
            error_code="auth_error",
        )
    if resp.status_code != 200:
        raise FastFailError(
            f"GitHub API error {resp.status_code} for {owner}/{repo}",
            error_code="api_error",
        )

    data = resp.json()
    return {
        "owner": owner,
        "repo": repo,
        "default_branch": data.get("default_branch", "main"),
        "private": data.get("private", False),
    }


async def get_repo_head_sha(
    owner: str,
    repo: str,
    branch: str,
    token: Optional[str] = None,
) -> str:
    """
    Get the HEAD commit SHA for a branch via GitHub API (no clone needed).

    This is called before cloning so we can check the idempotency cache first.
    """
    import httpx

    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    api_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
    logger.info("get_head_sha", owner=owner, repo=repo, branch=branch)

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(api_url, headers=headers)
        except httpx.RequestError as e:
            raise FastFailError(f"Network error: {e}", error_code="network_error") from e

    if resp.status_code == 404:
        raise FastFailError(
            f"Branch '{branch}' not found in {owner}/{repo}",
            error_code="branch_not_found",
        )
    if resp.status_code != 200:
        raise FastFailError(
            f"GitHub API error {resp.status_code}",
            error_code="api_error",
        )

    sha = resp.json().get("sha", "")
    if not sha:
        raise FastFailError("Could not get commit SHA from GitHub API", error_code="api_error")

    logger.info("got_head_sha", sha=sha[:12])
    return sha


async def clone_repo(
    repo_url: str,
    branch: str,
    dest_dir: str,
    token: Optional[str] = None,
    timeout_seconds: int = 120,
) -> str:
    """
    Shallow-clone a GitHub repo into dest_dir.

    Primary path: `git clone --depth 1 --branch {branch}` (faster, gives real
    .git so subprocess tools that depend on it still work).
    Fallback: GitHub tarball API → tar -xz (used when the runtime image lacks
    a `git` binary, e.g. some Zeabur Python builders). The fallback is slower
    but works without any system git installation.
    Returns the HEAD commit SHA. Token is embedded in URL but never logged.
    """
    owner, repo = parse_repo_url(repo_url)
    auth_url = _make_authenticated_url(owner, repo, token)
    safe_url = _redact_token(auth_url)

    logger.info("clone_start", url=safe_url, branch=branch, dest=dest_dir)

    cfg = SandboxConfig(timeout_seconds=timeout_seconds, working_dir=None)

    clone_result = await run_command(
        ["git", "clone", "--depth", "1", "--branch", branch, auth_url, dest_dir],
        cfg,
    )

    # Detect "git binary not installed in runtime" — fall back to API tarball.
    git_missing = clone_result.returncode == 127 or (
        "command not found" in (clone_result.stderr or "").lower()
        or "no such file or directory" in (clone_result.stderr or "").lower()
        and "git" in (clone_result.stderr or "").lower()
    )
    if git_missing:
        logger.warning("git_binary_missing_fallback_to_api", stderr=clone_result.stderr[:200])
        return await _clone_via_api_tarball(owner, repo, branch, dest_dir, token, timeout_seconds)

    if clone_result.timed_out:
        raise FastFailError(
            f"git clone timed out after {timeout_seconds}s",
            error_code="timeout",
        )
    if clone_result.returncode != 0:
        err = clone_result.stderr[:500]
        raise FastFailError(
            f"git clone failed (exit {clone_result.returncode}): {err}",
            error_code="clone_failed",
        )

    # Get HEAD SHA
    sha_result = await run_command(
        ["git", "rev-parse", "HEAD"],
        SandboxConfig(timeout_seconds=10, working_dir=dest_dir),
    )
    commit_sha = sha_result.stdout.strip() or "unknown"
    logger.info("clone_done", sha=commit_sha[:12], duration_ms=round(clone_result.duration_ms))
    return commit_sha


async def _clone_via_api_tarball(
    owner: str,
    repo: str,
    branch: str,
    dest_dir: str,
    token: Optional[str],
    timeout_seconds: int,
) -> str:
    """Download repo as tarball via GitHub API. Used when `git` is unavailable."""
    import os
    import tarfile
    import time as _time

    import httpx

    url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{branch}"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    started = _time.time()
    os.makedirs(dest_dir, exist_ok=True)

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout_seconds) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise FastFailError(
                f"GitHub tarball download failed: {resp.status_code}",
                error_code="api_tarball_failed",
            )
        tar_path = os.path.join(dest_dir, ".tarball.tgz")
        with open(tar_path, "wb") as f:
            f.write(resp.content)

    # GitHub tarball wraps content in a top-level <user>-<repo>-<sha7>/ directory.
    with tarfile.open(tar_path, "r:gz") as tar:
        members = tar.getmembers()
        if not members:
            raise FastFailError("Empty tarball", error_code="api_tarball_failed")
        top_prefix = members[0].name.split("/")[0]
        # Strip the top-level directory while extracting
        for m in members:
            if m.name.startswith(top_prefix + "/"):
                m.name = m.name[len(top_prefix) + 1 :]
            elif m.name == top_prefix:
                continue
            if m.name:
                tar.extract(m, path=dest_dir)
    os.remove(tar_path)

    # Get HEAD SHA via API since we don't have .git
    head_sha = await get_repo_head_sha(owner, repo, branch, token)
    logger.info(
        "clone_done_via_api",
        sha=head_sha[:12],
        duration_ms=round((_time.time() - started) * 1000),
    )
    return head_sha


async def get_latest_tag(
    owner: str,
    repo: str,
    token: Optional[str] = None,
) -> Optional[str]:
    """
    Return the most recent semver tag for a repo, or None if no tags exist.
    """
    import httpx

    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    api_url = f"https://api.github.com/repos/{owner}/{repo}/tags?per_page=10"

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(api_url, headers=headers)
        except httpx.RequestError:
            return None

    if resp.status_code != 200:
        return None

    tags = resp.json()
    # Return the first tag that looks like a semver (vX.Y.Z or X.Y.Z)
    for tag in tags:
        name = tag.get("name", "")
        if re.match(r"^v?\d+\.\d+\.\d+", name):
            return name
    return None


async def get_commits_since_tag(
    owner: str,
    repo: str,
    since_tag: Optional[str],
    token: Optional[str] = None,
    max_commits: int = 50,
) -> list[dict]:
    """
    Return commits since the given tag (or last 50 commits if no tag).

    Each commit: {"sha": str, "message": str, "author": str, "date": str}
    """
    import httpx

    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params: dict = {"per_page": max_commits}
    if since_tag:
        params["sha"] = "HEAD"  # will compare against tag below

    api_url = f"https://api.github.com/repos/{owner}/{repo}/commits"

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(api_url, headers=headers, params=params)
        except httpx.RequestError:
            return []

    if resp.status_code != 200:
        return []

    commits = []
    for c in resp.json():
        commit_data = c.get("commit", {})
        commits.append({
            "sha": c.get("sha", ""),
            "message": commit_data.get("message", "").split("\n")[0],  # first line only
            "author": commit_data.get("author", {}).get("name", "unknown"),
            "date": commit_data.get("author", {}).get("date", ""),
        })

    # If we have a since_tag, find where the tag commit is and slice
    if since_tag:
        tag_sha = await _get_tag_sha(owner, repo, since_tag, token)
        if tag_sha:
            for i, c in enumerate(commits):
                if c["sha"].startswith(tag_sha[:12]) or tag_sha.startswith(c["sha"][:12]):
                    commits = commits[:i]
                    break

    return commits


async def _get_tag_sha(
    owner: str,
    repo: str,
    tag: str,
    token: Optional[str] = None,
) -> Optional[str]:
    """Get the commit SHA that a tag points to."""
    import httpx

    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/ref/tags/{tag}"

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(api_url, headers=headers)
        except httpx.RequestError:
            return None

    if resp.status_code != 200:
        return None

    obj = resp.json().get("object", {})
    return obj.get("sha")


async def create_github_release(
    owner: str,
    repo: str,
    tag_name: str,
    name: str,
    body: str,
    commit_sha: str,
    token: str,
) -> str:
    """
    Create an annotated tag and GitHub release via API.

    Only called when dry_run=False. Returns the release URL.
    Idempotency: checks if tag already exists before creating.
    """
    import httpx

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # Check if tag already exists
        tag_check = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/ref/tags/{tag_name}",
            headers=headers,
        )
        if tag_check.status_code == 200:
            # Tag exists — find existing release
            rel_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag_name}",
                headers=headers,
            )
            if rel_resp.status_code == 200:
                return rel_resp.json().get("html_url", "")

        # Create tag object
        tag_resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/git/tags",
            headers=headers,
            json={
                "tag": tag_name,
                "message": f"Release {tag_name}",
                "object": commit_sha,
                "type": "commit",
            },
        )
        if tag_resp.status_code not in (200, 201):
            raise FastFailError(
                f"Failed to create tag {tag_name}: {tag_resp.status_code}",
                error_code="api_error",
            )
        tag_sha = tag_resp.json().get("sha", commit_sha)

        # Create ref pointing to tag
        await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/tags/{tag_name}", "sha": tag_sha},
        )

        # Create release
        rel_resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/releases",
            headers=headers,
            json={
                "tag_name": tag_name,
                "name": name,
                "body": body,
                "draft": False,
                "prerelease": False,
            },
        )
        if rel_resp.status_code not in (200, 201):
            raise FastFailError(
                f"Failed to create release: {rel_resp.status_code}",
                error_code="api_error",
            )
        return rel_resp.json().get("html_url", "")
