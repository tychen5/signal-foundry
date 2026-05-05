"""
Dependency Audit Skill.

Pure parse + HTTP — no subprocess execution needed.
Parses lock files to discover dependencies, then queries OSV.dev for CVEs
and PyPI for outdated versions. Satisfies the "no install attempts" boundary.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Optional

import httpx

from src.shared.logger import get_logger
from src.task1_cicd.schemas import (
    DependencyAuditResult,
    OutdatedEntry,
    PackagePin,
    RepoContext,
    VulnerabilityEntry,
)

logger = get_logger("dependency_audit")

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
PYPI_URL = "https://pypi.org/pypi/{name}/json"
MAX_BATCH_SIZE = 100  # OSV.dev batch limit


async def run(ctx: RepoContext) -> DependencyAuditResult:
    """Main entry: parse lock files → query OSV.dev → check outdated → return report."""
    clone_path = ctx.clone_path
    base = Path(clone_path)

    python_packages: list[PackagePin] = []
    js_packages: list[PackagePin] = []
    ecosystems: list[str] = []

    # Collect Python dependencies
    req_txt = base / "requirements.txt"
    if req_txt.exists():
        python_packages.extend(_parse_requirements_txt(str(req_txt)))
        ecosystems.append("PyPI")

    pyproject = base / "pyproject.toml"
    if pyproject.exists():
        extra = _parse_pyproject_toml(str(pyproject))
        # Merge, avoiding duplicates
        existing_names = {p.name.lower() for p in python_packages}
        for p in extra:
            if p.name.lower() not in existing_names:
                python_packages.append(p)
                existing_names.add(p.name.lower())
        if extra:
            ecosystems = list(dict.fromkeys(["PyPI"] + ecosystems))

    # Collect JavaScript dependencies
    pkg_lock = base / "package-lock.json"
    if pkg_lock.exists():
        js_packages = _parse_package_lock_v2(str(pkg_lock))
        ecosystems.append("npm")

    all_packages = python_packages + js_packages
    total = len(all_packages)
    logger.info("audit_packages", total=total, ecosystems=ecosystems)

    if total == 0:
        return DependencyAuditResult(
            status="clean",
            total_dependencies=0,
            ecosystems_checked=ecosystems,
            notes="No lockfiles found (requirements.txt, pyproject.toml, package-lock.json)",
        )

    # Query OSV.dev for vulnerabilities
    vulns: list[VulnerabilityEntry] = []
    if python_packages:
        vulns.extend(await _query_osv_batch(python_packages, "PyPI"))
    if js_packages:
        vulns.extend(await _query_osv_batch(js_packages, "npm"))

    # Check for outdated Python packages
    outdated: list[OutdatedEntry] = []
    if python_packages:
        outdated = await _check_outdated_python(python_packages[:50])  # limit to 50 for latency

    # Severity breakdown
    critical = sum(1 for v in vulns if v.severity == "critical")
    high = sum(1 for v in vulns if v.severity == "high")
    medium = sum(1 for v in vulns if v.severity == "medium")

    if critical + high > 0:
        status = "vulnerabilities_found"
    elif medium > 0 or outdated:
        status = "warnings"
    else:
        status = "clean"

    return DependencyAuditResult(
        status=status,
        total_dependencies=total,
        ecosystems_checked=list(dict.fromkeys(ecosystems)),
        vulnerabilities=vulns,
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        outdated=outdated,
    )


def _parse_requirements_txt(path: str) -> list[PackagePin]:
    """Parse a requirements.txt file into a list of PackagePin."""
    packages = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith(("#", "-", "git+")):
                continue
            # Strip inline comments
            line = line.split("#")[0].strip()
            # Handle extras like package[extra]==version
            m = re.match(r"^([A-Za-z0-9_\-\.]+)(?:\[[^\]]*\])?(?:==|>=|<=|~=|!=|>|<)\s*([\S]+)", line)
            if m:
                name = m.group(1)
                version = m.group(2).split(",")[0].strip()  # take first version constraint
                packages.append(PackagePin(name=name, version=version, ecosystem="PyPI"))
            else:
                # Bare package name without version
                bare = re.match(r"^([A-Za-z0-9_\-\.]+)", line)
                if bare:
                    packages.append(PackagePin(name=bare.group(1), version=None, ecosystem="PyPI"))
    return packages


def _parse_pyproject_toml(path: str) -> list[PackagePin]:
    """
    Parse pyproject.toml for dependencies.
    Uses tomllib (stdlib in Python 3.11+).
    Covers both PEP 621 [project.dependencies] and poetry [tool.poetry.dependencies].
    """
    try:
        if sys.version_info >= (3, 11):
            import tomllib
            with open(path, "rb") as f:
                data = tomllib.load(f)
        else:
            try:
                import tomli as tomllib  # type: ignore[no-redef]
                with open(path, "rb") as f:
                    data = tomllib.load(f)
            except ImportError:
                return []
    except Exception:
        return []

    packages = []
    # PEP 621 style: [project] dependencies = ["requests>=2.28"]
    pep621 = data.get("project", {}).get("dependencies", [])
    for dep in pep621:
        m = re.match(r"^([A-Za-z0-9_\-\.]+)(?:\[[^\]]*\])?(?:==|>=|<=|~=|!=|>|<)\s*([\S]+)?", dep)
        if m:
            packages.append(PackagePin(name=m.group(1), version=m.group(2), ecosystem="PyPI"))
        else:
            bare = re.match(r"^([A-Za-z0-9_\-\.]+)", dep)
            if bare:
                packages.append(PackagePin(name=bare.group(1), version=None, ecosystem="PyPI"))

    # Poetry style: [tool.poetry.dependencies] requests = "^2.28"
    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    existing = {p.name.lower() for p in packages}
    for name, spec in poetry_deps.items():
        if name.lower() == "python":
            continue
        if name.lower() not in existing:
            version = None
            if isinstance(spec, str):
                version = re.sub(r"[^0-9\.]", "", spec) or None
            elif isinstance(spec, dict):
                raw = spec.get("version", "")
                version = re.sub(r"[^0-9\.]", "", raw) or None
            packages.append(PackagePin(name=name, version=version, ecosystem="PyPI"))

    return packages


def _parse_package_lock_v2(path: str) -> list[PackagePin]:
    """
    Parse package-lock.json (npm lockfile v2/v3) for resolved package versions.
    Reads from packages["node_modules/X"] section.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception:
        return []

    packages = []
    # v2/v3 format: packages["node_modules/pkg"] = {"version": "1.2.3"}
    pkg_map = data.get("packages", {})
    for key, info in pkg_map.items():
        if not key.startswith("node_modules/"):
            continue
        name = key[len("node_modules/"):]
        # Skip nested packages (e.g., node_modules/a/node_modules/b)
        if "/" in name:
            continue
        version = info.get("version")
        if name and version:
            packages.append(PackagePin(name=name, version=version, ecosystem="npm"))

    # Limit to 200 packages to keep OSV.dev queries manageable
    return packages[:200]


async def _query_osv_batch(
    packages: list[PackagePin],
    ecosystem: str,
) -> list[VulnerabilityEntry]:
    """
    Query OSV.dev batch endpoint for vulnerabilities.
    POST https://api.osv.dev/v1/querybatch
    Free, no auth required.
    """
    # Only query packages with known versions
    pinned = [p for p in packages if p.version]
    if not pinned:
        return []

    vulns: list[VulnerabilityEntry] = []

    # Process in batches of MAX_BATCH_SIZE
    for i in range(0, len(pinned), MAX_BATCH_SIZE):
        batch = pinned[i:i + MAX_BATCH_SIZE]
        queries = [
            {"package": {"name": p.name, "ecosystem": ecosystem}, "version": p.version}
            for p in batch
        ]

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(OSV_BATCH_URL, json={"queries": queries})
        except httpx.RequestError as e:
            logger.warning("osv_request_error", error=str(e))
            continue

        if resp.status_code != 200:
            logger.warning("osv_api_error", status=resp.status_code)
            continue

        results = resp.json().get("results", [])
        for pkg, result in zip(batch, results):
            for vuln in result.get("vulns", []):
                severity = _osv_severity(vuln)
                fixed_version = _osv_fixed_version(vuln, pkg.name)
                aliases = vuln.get("aliases", [])
                cve_id = next((a for a in aliases if a.startswith("CVE-")), "")
                ref_url = ""
                for ref in vuln.get("references", []):
                    if ref.get("type") == "WEB":
                        ref_url = ref.get("url", "")
                        break

                vulns.append(VulnerabilityEntry(
                    package=pkg.name,
                    version=pkg.version or "unknown",
                    cve_id=cve_id,
                    osv_id=vuln.get("id", ""),
                    severity=severity,
                    summary=vuln.get("summary", "")[:200],
                    fixed_version=fixed_version,
                    reference_url=ref_url,
                ))

    return vulns


def _osv_severity(vuln: dict) -> str:
    """Extract severity from an OSV vulnerability record."""
    severity = vuln.get("database_specific", {}).get("severity", "")
    if severity:
        return severity.lower()
    # Try CVSS from affected
    for aff in vuln.get("affected", []):
        for sev in aff.get("severity", []):
            score = sev.get("score", "")
            if score:
                try:
                    val = float(score)
                    if val >= 9.0:
                        return "critical"
                    elif val >= 7.0:
                        return "high"
                    elif val >= 4.0:
                        return "medium"
                    return "low"
                except ValueError:
                    pass
    return "unknown"


def _osv_fixed_version(vuln: dict, package_name: str) -> Optional[str]:
    """Extract the first fixed version from an OSV vulnerability record."""
    for aff in vuln.get("affected", []):
        if aff.get("package", {}).get("name", "").lower() == package_name.lower():
            for rng in aff.get("ranges", []):
                for event in rng.get("events", []):
                    if "fixed" in event:
                        return event["fixed"]
    return None


async def _check_outdated_python(packages: list[PackagePin]) -> list[OutdatedEntry]:
    """
    Check each pinned Python package against PyPI for the latest version.
    Uses concurrent requests (up to 10 at a time).
    """
    pinned = [p for p in packages if p.version]
    if not pinned:
        return []

    outdated: list[OutdatedEntry] = []
    semaphore = asyncio.Semaphore(10)

    async def check_one(pkg: PackagePin) -> Optional[OutdatedEntry]:
        async with semaphore:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(PYPI_URL.format(name=pkg.name))
                if resp.status_code != 200:
                    return None
                latest = resp.json().get("info", {}).get("version", "")
                if latest and latest != pkg.version:
                    is_major = _is_major_bump(pkg.version or "", latest)
                    return OutdatedEntry(
                        package=pkg.name,
                        current_version=pkg.version or "unknown",
                        latest_version=latest,
                        is_major_bump=is_major,
                    )
            except Exception:
                pass
            return None

    results = await asyncio.gather(*[check_one(p) for p in pinned])
    outdated = [r for r in results if r is not None]
    return outdated


def _is_major_bump(current: str, latest: str) -> bool:
    """Check if latest represents a major version bump from current."""
    try:
        cur_major = int(current.split(".")[0].lstrip("v"))
        lat_major = int(latest.split(".")[0].lstrip("v"))
        return lat_major > cur_major
    except (ValueError, IndexError):
        return False
