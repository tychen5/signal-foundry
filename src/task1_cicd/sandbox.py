"""
Subprocess Sandbox for CI/CD Skills.

Provides timeout-enforced, isolated subprocess execution for running
linting, testing, and scanning tools against cloned repositories.
No Docker required — subprocess + tempdir isolation is sufficient.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from src.shared.logger import get_logger
from src.task1_cicd.schemas import SandboxConfig, SandboxResult

logger = get_logger("sandbox")

# Maximum output to capture before truncating (protects memory)
MAX_OUTPUT_BYTES = 1_000_000

# Env vars to strip from child processes (security)
_SENSITIVE_ENV_KEYS = {"GITHUB_TOKEN", "OPENROUTER_API_KEY", "NVIDIA_API_KEY", "LANGCHAIN_API_KEY"}


def _build_child_env(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Build a clean environment for child processes, stripping sensitive keys."""
    env = {k: v for k, v in os.environ.items() if k not in _SENSITIVE_ENV_KEYS}
    if extra:
        env.update(extra)
    return env


async def run_command(
    cmd: list[str],
    config: SandboxConfig,
    extra_env: Optional[dict[str, str]] = None,
) -> SandboxResult:
    """
    Run a command in a subprocess with timeout and output size limiting.

    Uses asyncio.create_subprocess_exec (non-blocking). On timeout: sends
    SIGTERM, waits 5 seconds, then SIGKILL. Sensitive env vars are stripped.
    """
    working_dir = config.working_dir
    env = _build_child_env(extra_env)
    start = time.monotonic()

    logger.info("sandbox_run", cmd=" ".join(cmd[:4]), cwd=working_dir)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=env,
        )
    except FileNotFoundError:
        elapsed = (time.monotonic() - start) * 1000
        return SandboxResult(
            command=cmd,
            returncode=127,
            stdout="",
            stderr=f"Command not found: {cmd[0]}",
            timed_out=False,
            duration_ms=elapsed,
        )
    except OSError as e:
        elapsed = (time.monotonic() - start) * 1000
        return SandboxResult(
            command=cmd,
            returncode=1,
            stdout="",
            stderr=f"OS error starting process: {e}",
            timed_out=False,
            duration_ms=elapsed,
        )

    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=config.timeout_seconds,
        )
    except TimeoutError:
        timed_out = True
        # Graceful shutdown: SIGTERM → 5s → SIGKILL
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        stdout_bytes = b""
        stderr_bytes = b"[TIMEOUT] Process exceeded time limit"

    elapsed = (time.monotonic() - start) * 1000

    # Cap output size
    cap = config.max_output_bytes
    stdout = stdout_bytes[:cap].decode("utf-8", errors="replace")
    stderr = stderr_bytes[:cap].decode("utf-8", errors="replace")

    if len(stdout_bytes) > cap:
        stdout += f"\n[TRUNCATED: output exceeded {cap // 1024}KB]"
    if len(stderr_bytes) > cap:
        stderr += f"\n[TRUNCATED: stderr exceeded {cap // 1024}KB]"

    returncode = proc.returncode if not timed_out else -1

    logger.info(
        "sandbox_done",
        returncode=returncode,
        timed_out=timed_out,
        duration_ms=round(elapsed, 1),
        stdout_len=len(stdout),
    )

    return SandboxResult(
        command=cmd,
        returncode=returncode or 0,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_ms=elapsed,
    )


def detect_language(clone_path: str) -> str:
    """
    Detect the primary programming language from project file presence.

    Priority: pyproject.toml/requirements.txt/setup.py → Python
              package.json → JavaScript
              otherwise → unknown
    """
    base = Path(clone_path)
    if (base / "pyproject.toml").exists() or (base / "requirements.txt").exists() or (base / "setup.py").exists():
        return "python"
    if (base / "package.json").exists():
        return "javascript"
    return "unknown"


def make_temp_dir(prefix: str = "sf_cicd_") -> str:
    """Create an isolated temp directory for a skill run."""
    path = tempfile.mkdtemp(prefix=prefix)
    logger.info("temp_dir_created", path=path)
    return path


def cleanup_temp_dir(path: str) -> None:
    """Remove a temp directory, swallowing all errors."""
    try:
        shutil.rmtree(path, ignore_errors=True)
        logger.info("temp_dir_cleaned", path=path)
    except Exception as e:
        logger.warning("temp_dir_cleanup_failed", path=path, error=str(e))


def get_python_executable() -> str:
    """Return the current Python interpreter path."""
    return sys.executable


def has_ruff(clone_path: str) -> bool:
    """Check if ruff is available in the current env (not in cloned repo)."""
    return shutil.which("ruff") is not None


def has_pytest(clone_path: str) -> bool:
    """Check if pytest is importable in the current env."""
    try:
        import importlib.util
        return importlib.util.find_spec("pytest") is not None
    except Exception:
        return False
