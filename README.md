# Malakof/.github — Crystal GitHub governance

Single source of truth for Crystal team GitHub conventions:
labels, issue/PR templates, naming, reusable workflows, agent skill.

**Current version**: `v1.4.1` (see `.crystal-governance.yaml`).

## For humans

- **Canonical document**: [`governance/README.md`](./governance/README.md)
- **Label table**: [`governance/labels.yaml`](./governance/labels.yaml)
- **Conventional Commits scopes**: [`governance/scopes.yaml`](./governance/scopes.yaml)

## For AI agents

- **Skill**: [`skills/crystal-github-conventions/SKILL.md`](./skills/crystal-github-conventions/SKILL.md)

Universal `SKILL.md` format (YAML frontmatter `name` + `description`)
recognised by Claude **and** Codex. Automatically propagated by
`crystal-company/builders/sync_repo_surface.py` to both surfaces:

- `.claude/skills/crystal-github-conventions/` — Claude surface
- `.agents/skills/crystal-github-conventions/` — Codex surface (universal skills,
  see [Codex docs](https://developers.openai.com/codex/skills))

> Note: `.codex/agents/` is reserved for Codex **agents** (roles like
> reviewer/CEO/CTO in TOML). Crystal GitHub conventions are a *skill*
> (reference capability), not an agent — so no file in `.codex/agents/`.

## For Crystal repos

Add to the target repo:

1. `.crystal-governance.yaml`:
   ```yaml
   schema: crystal-governance-pin/v1
   governance_version: v1.4.1
   source: Malakof/.github
   ```

2. `.github/workflows/governance-check.yml`:
   ```yaml
   name: governance-check
   on: [push, pull_request]
   jobs:
     check:
       uses: Malakof/.github/.github/workflows/governance-check.yml@v1.4.1
   ```

3. `.github/workflows/enforce-conventions.yml`:
   ```yaml
   name: enforce-conventions
   on: [pull_request]
   jobs:
     enforce:
       uses: Malakof/.github/.github/workflows/enforce-conventions.yml@v1.4.1
   ```

4. Run label sync:
   ```sh
   gh repo clone Malakof/.github /tmp/crystal-governance
   cd /tmp/crystal-governance
   python scripts/sync-labels.py --repo <owner>/<name>
   ```

## Format-check: GitHub Copilot migration

[GitHub Models was retired on July 30, 2026](https://github.blog/changelog/2026-07-30-github-models-is-now-retired/).
The shared [workflow](.github/workflows/format-check.yml) now uses GitHub Copilot
CLI `1.0.112`, Node.js 24 and the temporary Actions `GITHUB_TOKEN`, with
[`copilot-requests: write`](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli-in-actions).
No PAT or additional repository secret is needed for this check. The organization
must allow Copilot CLI requests billed to the organization.

The [checker](scripts/format_check.py) keeps the canonical deterministic precheck,
artifact-specific qualitative prompts and sticky verdict comment. Copilot receives
only the governance rules and artifact metadata, in a temporary working/config
folder, with no tools, custom instructions or built-in MCP servers. It consumes
native JSONL events rather than terminal-rendered text, which can insert line
breaks into JSON strings. The token is never put in the prompt or command arguments.

A valid verdict preserves the `blocking` policy: advisory findings remain advisory.
An unavailable review, invalid verdict, timeout or failed process always fails the
job and is reported as `UNAVAILABLE`, with `pass: null`. This intentionally replaces
the earlier proposal in PR #5 to warn and exit successfully on unavailable advisory
reviews. Raw provider output and credentials are omitted from diagnostics. Each run
makes one bounded CLI invocation (180 seconds), without automatic retries.

The model defaults to `auto`. Existing `openai/gpt-4o` and `openai/gpt-4o-mini`
inputs are mapped explicitly to Copilot `auto`, with a notice. Other model IDs are
passed through and must be supported by Copilot; no silent fallback is attempted.

### Adoption after publication

These changes are not deployed merely by merging the shared PR. Published tags
are immutable. A maintainer must:

1. Approve the fork's test workflow, review and merge the shared PR.
2. Publish a new SemVer tag and GitHub Release containing this commit, and update
   the self-pin for that actual release. Do not move `v1.4.3` or any older tag.
3. Update **both** the consumer's `.crystal-governance.yaml` and its reusable
   workflow reference to that published version. The workflow checks out the
   script at the consumer pin, so changing only the workflow ref is insufficient.
4. On the calling `format-check` job, replace `models: read` with
   `copilot-requests: write`, retain `contents: read`, `issues: write` and
   `pull-requests: write`, and set `with.model: auto` (or omit the model input).
5. Verify a new issue/PR execution: the runtime version, native Copilot verdict
   and all repository checks must succeed before merging the consumer bump.

The release [bump generator](scripts/open-bump-prs.py) now performs steps 3–4 for
existing reusable format-check callers. It preserves unrelated jobs and explicitly
chosen Copilot models. A detected local adapter causes the whole pin bump to return
`manual-migration-required`, before any commit or push: the old dynamic-import
wrapper may be incompatible with imports in a newer pinned checker. Inline/aliased job definitions that
cannot be migrated safely produce an explicit per-repository error for manual
handling. Its tests cover idempotence and inherited/inline/aliased permissions.

Known callers inspected on November 16, 2026: `crystal-capabilities`,
`crystal-assistant-ui-poc` and `crystal-company`. `crystal-specs` already runs a
local adapter delivered in [PR #357](https://github.com/Malakof/crystal-specs/pull/357):
keep it until the new shared release is available, then switch back to the shared
workflow and remove the adapter in a separate validated change. Repositories
without format-check are not enrolled by this migration.

Run all tests with `python3 -m unittest discover -s tests -v` after installing
`PyYAML>=6.0`. The suite makes no live model call and publishes no CI comment.

## Release workflow

On every semver tag `vX.Y.Z` pushed on `main`:

- `.github/workflows/on-release-bump.yml` opens `chore: bump governance
  to vX.Y.Z` PRs on every non-archived `Malakof/crystal-*` repo pinning
  an older version, including format-check permissions/model migration.

## Versioning

- **Major**: label removal, breaking template change.
- **Minor**: label addition, new template/skill/workflow.
- **Patch**: colors, descriptions, doc.

## Structure

```
.
├── README.md                       ← this file
├── .crystal-governance.yaml        ← self-pin
├── governance/
│   ├── README.md                   ← canonical document (4 naming packs)
│   ├── labels.yaml                 ← canonical label table
│   └── scopes.yaml                 ← Conventional Commits scopes
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── epic.yml
│   │   ├── feature.yml
│   │   ├── bug.yml
│   │   ├── mission-intake.yml
│   │   └── config.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/
│       ├── enforce-conventions.yml ← reusable
│       ├── governance-check.yml    ← reusable
│       ├── format-check.yml        ← reusable (Copilot)
│       └── on-release-bump.yml     ← internal (on tag)
├── skills/
│   └── crystal-github-conventions/   ← propagated to .claude/skills + .agents/skills
│       └── SKILL.md
└── scripts/
    ├── sync-labels.py
    ├── setup-autolinks.py
    ├── format_check.py
    ├── validate_title.py
    ├── validate_labels.py
    └── open-bump-prs.py
```
