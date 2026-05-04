---
name: build-and-release
description: >
  Builds project artifacts and manages releases on GitHub. Use when user says
  "release this", "ship it", "deploy", "publish", "create release", "tag version",
  or "build artifact". Always runs in dry-run mode first — requires explicit
  human confirmation before creating tags or releases.
---

# Build and Release Skill

## Purpose
Build project artifacts and create GitHub releases with proper tagging,
changelogs, and artifact attachment. **Always dry-run first.**

## Inputs
- `repo_url` (required): GitHub repository URL
- `version` (optional): Version tag (auto-detected from commit history if omitted)
- `dry_run` (default: true): When true, shows what would happen without executing
- `include_changelog` (default: true): Auto-generate changelog from commits

## Outputs
```json
{
  "execution_id": "def456",
  "mode": "dry_run | execute",
  "status": "success | failed",
  "version": "v1.2.3",
  "changelog": "...",
  "artifacts": ["dist/package-1.2.3.tar.gz"],
  "release_url": "https://github.com/owner/repo/releases/tag/v1.2.3"
}
```

## Security Boundary
- **Dry-run first**: Always previews actions before executing
- **Gated write**: Requires explicit human approval for:
  - Creating git tags
  - Publishing releases
  - Uploading artifacts
- **Blocklist**: Refuses to force-push, delete branches, or modify CI/CD config
- **Audit trail**: All actions logged with execution ID

## Idempotency
If a tag already exists for the version, returns existing release info
instead of creating a duplicate.

## Workflow
1. Analyze commit history since last tag
2. Determine version bump (major/minor/patch) based on conventional commits
3. Generate changelog from commit messages
4. Build artifacts (detect build system: pip, npm, make)
5. **DRY RUN**: Display plan and wait for confirmation
6. Create tag, push, create GitHub release with changelog and artifacts
