"""
Skill Engine: Main CI/CD Skills Orchestrator.

Data flow:
  [1] resolve skill name (registry: exact → fuzzy → LLM)
  [2] validate repo exists (GitHub API)
  [3] get HEAD SHA (GitHub API, no clone)
  [4] check idempotency cache → return cached result if hit
  [5] make temp dir
  [6] clone repo (--depth 1)
  [7] detect language
  [8] build RepoContext
  [9] dispatch to skill module
  [10] LLM summarize result
  [11] cache result
  [12] cleanup temp dir (finally block)
  [13] return ExecutionResult

Cache key: cicd:v1:{owner}/{repo}:{branch}:{skill_name}:{commit_sha[:12]}:{dry_run}
Idempotency guarantee: same repo+commit+skill always returns the same result.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

from src.shared.cost_tracker import get_cost_tracker
from src.shared.logger import get_logger
from src.shared.schemas import ExecutionResult, ExecutionStatus, FailureType, TaskType
from src.shared.tracing import attach_metadata, traced
from src.task1_cicd import github_client, skill_registry
from src.task1_cicd.github_client import FastFailError
from src.task1_cicd.sandbox import SandboxConfig, cleanup_temp_dir, detect_language, make_temp_dir
from src.task1_cicd.schemas import RepoContext, SkillRunRequest

logger = get_logger("skill_engine")

# In-process idempotency cache — keyed by SHA-based cache key
# In production, swap for Redis with TTL.
_result_cache: dict[str, dict] = {}
_cache_lock = asyncio.Lock()
CACHE_KEY_VERSION = "v1"
CACHE_TTL_SECONDS = 3600  # 1 hour


def _make_cache_key(
    owner: str,
    repo: str,
    branch: str,
    skill_name: str,
    commit_sha: str,
    dry_run: bool,
) -> str:
    """
    Deterministic cache key based on repo identity + content SHA + skill.
    dry_run is part of the key for build-and-release (preview vs real differ).
    """
    return f"cicd:{CACHE_KEY_VERSION}:{owner}/{repo}:{branch}:{skill_name}:{commit_sha[:12]}:{dry_run}"


@traced(name="task1_run_skill", tags=["task1", "cicd_skill"])
async def run_skill(
    request: SkillRunRequest,
    trace_id: str,
    progress_callback: Optional[callable] = None,
) -> ExecutionResult:
    """
    Full skill execution pipeline with idempotency, caching, and cost tracking.

    Args:
        progress_callback: Optional async fn(dict) called at each milestone
            (skill_resolved, sha_fetched, cache_hit/miss, clone_start/done,
            skill_run_start/done, summarize_start/done, skill_complete).
            Used by the SSE streaming endpoint.
    """
    async def _emit(event: str, **payload) -> None:
        if not progress_callback:
            return
        try:
            await progress_callback({"event": event, **payload})
        except Exception as e:
            logger.warning("t1_progress_callback_failed", error=str(e)[:120])

    attach_metadata({
        "trace_id": trace_id,
        "skill_name": request.skill_name,
        "repo_url": request.repo_url,
        "branch": request.branch,
        "dry_run": request.dry_run,
        "model_name": request.model.model_id if request.model else "default",
    })
    await _emit(
        "skill_start",
        repo=request.repo_url,
        branch=request.branch,
        requested_skill=request.skill_name,
        dry_run=request.dry_run,
        model=request.model.model_id if request.model else "default",
    )
    start_time = time.monotonic()
    token = _get_github_token()
    temp_dir: Optional[str] = None

    try:
        # [1] Resolve skill name
        try:
            skill_name, match_confidence = await skill_registry.resolve_skill_name(
                raw=request.skill_name,
                model_name=request.model.model_id,
                user_api_key=request.model.user_openrouter_key,
                trace_id=trace_id,
            )
        except skill_registry.SkillMatchError as e:
            return _fail_result(str(e), FailureType.SKILL_MISMATCH, trace_id, start_time)

        logger.info("skill_resolved", skill=skill_name, confidence=match_confidence, trace_id=trace_id)
        await _emit("skill_resolved", skill=skill_name, confidence=match_confidence)

        # [2] Validate repo exists
        try:
            repo_info = await github_client.validate_repo(request.repo_url, token)
        except FastFailError as e:
            return _fail_result(str(e), FailureType.REPO_NOT_FOUND, trace_id, start_time)

        owner = repo_info["owner"]
        repo = repo_info["repo"]
        # If user left branch at the schema default ("main") but repo's actual
        # default is something else (e.g. encode/httpx → "master"), use the
        # actual default. Only override when the user accepted the schema
        # default — explicit non-"main" branches stay as-is so users can still
        # target a specific branch.
        branch = request.branch
        if request.branch == "main" and repo_info.get("default_branch") and repo_info["default_branch"] != "main":
            branch = repo_info["default_branch"]
            logger.info("branch_default_overridden", original="main", actual=branch, owner=owner, repo=repo)
        await _emit("repo_validated", owner=owner, repo=repo, branch=branch)

        # [3] Get HEAD SHA (fast, no clone)
        try:
            commit_sha = await github_client.get_repo_head_sha(owner, repo, branch, token)
        except FastFailError as e:
            return _fail_result(str(e), FailureType.REPO_NOT_FOUND, trace_id, start_time)
        await _emit("sha_fetched", commit_sha=commit_sha[:12])

        # [4] Check idempotency cache
        cache_key = _make_cache_key(owner, repo, branch, skill_name, commit_sha, request.dry_run)
        async with _cache_lock:
            cached = _result_cache.get(cache_key)
            if cached and (time.monotonic() - cached["cached_at"]) < CACHE_TTL_SECONDS:
                logger.info("cache_hit", cache_key=cache_key, trace_id=trace_id)
                await _emit("cache_hit", cache_key=cache_key[:48])
                elapsed = (time.monotonic() - start_time) * 1000
                return ExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    task=TaskType.CICD_SKILLS,
                    trace_id=trace_id,
                    result={**cached["result"], "cache_hit": True},
                    cost_metadata={"cache_hit": True, "cost_usd": 0.0},
                    latency_ms=elapsed,
                )
        await _emit("cache_miss", cache_key=cache_key[:48])

        # [5] Make temp dir
        temp_dir = make_temp_dir()

        # [6] Clone repo
        logger.info("cloning_repo", owner=owner, repo=repo, branch=branch, trace_id=trace_id)
        await _emit("clone_start", owner=owner, repo=repo, branch=branch)
        try:
            actual_sha = await github_client.clone_repo(
                request.repo_url, branch, temp_dir, token, timeout_seconds=120
            )
            # Use actual SHA from clone (may differ from API SHA by milliseconds)
            commit_sha = actual_sha or commit_sha
        except FastFailError as e:
            return _fail_result(str(e), FailureType.SANDBOX_ERROR, trace_id, start_time)
        await _emit("clone_done", commit_sha=commit_sha[:12])

        # [7] Detect language
        language = detect_language(temp_dir)
        await _emit("language_detected", language=language)
        base = Path(temp_dir)

        # [8] Build RepoContext
        ctx = RepoContext(
            owner=owner,
            repo=repo,
            branch=branch,
            commit_sha=commit_sha,
            clone_path=temp_dir,
            language=language,
            has_pyproject=(base / "pyproject.toml").exists(),
            has_requirements_txt=(base / "requirements.txt").exists(),
            has_package_json=(base / "package.json").exists(),
            has_package_lock=(base / "package-lock.json").exists(),
            has_makefile=(base / "Makefile").exists(),
        )

        sandbox_cfg = SandboxConfig(timeout_seconds=300, max_output_bytes=1_000_000)

        # [9] Dispatch to skill module
        logger.info("dispatching_skill", skill=skill_name, language=language, trace_id=trace_id)
        await _emit("skill_run_start", skill=skill_name, language=language)
        raw_result = await _dispatch(skill_name, ctx, request.dry_run, token, sandbox_cfg)
        await _emit(
            "skill_run_done",
            skill=skill_name,
            status=raw_result.get("status", ""),
            preview=str({k: v for k, v in list(raw_result.items())[:3] if not isinstance(v, list) and k != "summary"})[:240],
        )

        # [10] LLM summarize
        await _emit("summarize_start", model=request.model.model_id if request.model else "default")
        summary = await skill_registry.llm_summarize(
            skill_name=skill_name,
            result=raw_result,
            model_name=request.model.model_id,
            user_api_key=request.model.user_openrouter_key,
            trace_id=trace_id,
        )
        await _emit("summarize_done", summary_preview=(summary or "")[:200])

        # Build final result dict. Spread `raw_result` first so engine-level
        # fields (`summary`, `match_confidence`, etc.) always win — this
        # prevents skill-specific fields with conflicting names (e.g. an
        # earlier `SecurityScanResult.summary` severity-counts dict) from
        # silently overwriting the LLM-generated text summary.
        result_data = {
            **raw_result,
            "skill": skill_name,
            "repo_url": request.repo_url,
            "branch": branch,
            "commit_sha": commit_sha[:12],
            "dry_run": request.dry_run,
            "language": language,
            "summary": summary,
            "match_confidence": match_confidence,
        }

        # [11] Cache result
        async with _cache_lock:
            _result_cache[cache_key] = {
                "result": result_data,
                "cached_at": time.monotonic(),
            }

        elapsed = (time.monotonic() - start_time) * 1000
        cost_metadata = get_cost_tracker().get_request_cost(trace_id)

        logger.info(
            "skill_complete",
            skill=skill_name,
            latency_ms=round(elapsed),
            cost_usd=cost_metadata.get("cost_usd", 0),
            trace_id=trace_id,
        )

        await _emit(
            "skill_complete",
            skill=skill_name,
            status="success",
            latency_ms=round(elapsed),
            cost_usd=cost_metadata.get("cost_usd", 0),
        )

        return ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            task=TaskType.CICD_SKILLS,
            trace_id=trace_id,
            result=result_data,
            cost_metadata=cost_metadata,
            latency_ms=elapsed,
        )

    except Exception as e:
        logger.error("skill_engine_error", error=str(e), trace_id=trace_id, exc_info=True)
        return _fail_result(f"Unexpected error: {e}", FailureType.SANDBOX_ERROR, trace_id, start_time)

    finally:
        # [12] Always clean up temp dir
        if temp_dir:
            cleanup_temp_dir(temp_dir)


async def _dispatch(
    skill_name: str,
    ctx: RepoContext,
    dry_run: bool,
    token: str,
    sandbox_cfg: SandboxConfig,
) -> dict[str, Any]:
    """Route to the correct skill module and return a serializable result dict."""
    if skill_name == "lint-and-test":
        from src.task1_cicd.skills import lint_and_test
        result = await lint_and_test.run(ctx, sandbox_cfg)

    elif skill_name == "dependency-audit":
        from src.task1_cicd.skills import dependency_audit
        result = await dependency_audit.run(ctx)

    elif skill_name == "security-scan":
        from src.task1_cicd.skills import security_scan
        result = await security_scan.run(ctx, sandbox_cfg)

    elif skill_name == "build-and-release":
        from src.task1_cicd.skills import build_and_release
        result = await build_and_release.run(ctx, dry_run, token)

    else:
        raise ValueError(f"Unknown skill: {skill_name}")

    return result.model_dump()


def _fail_result(
    error: str,
    failure_type: FailureType,
    trace_id: str,
    start_time: float,
) -> ExecutionResult:
    """Build a failure ExecutionResult."""
    elapsed = (time.monotonic() - start_time) * 1000
    logger.warning("skill_failed", error=error, failure_type=failure_type, trace_id=trace_id)
    return ExecutionResult(
        status=ExecutionStatus.FAILED,
        task=TaskType.CICD_SKILLS,
        trace_id=trace_id,
        error=error,
        failure_type=failure_type,
        latency_ms=elapsed,
    )


def _get_github_token() -> Optional[str]:
    """Get GitHub token from configuration."""
    try:
        from src.config import get_settings
        settings = get_settings()
        return getattr(settings, "github_token", None)
    except Exception:
        import os
        return os.environ.get("GITHUB_TOKEN")
