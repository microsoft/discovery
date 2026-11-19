# GitHub Actions workflows

## Pull request validation and feedback

### What happens to a pull request

Open a PR from your fork against `main`, complete the
[PR template](../pull_request_template.md), and follow the CLA bot's instructions.
Fork runs may need maintainer authorization; resolve merge conflicts before
`pull_request` checks can run.

Read the required check results and their source run logs. **PR Review Report**
publishes feedback asynchronously: inline rule comments where locations are
available, summaries for other findings, and diagnostic labels. Setup/reporting
failures may leave only run logs. Address findings in follow-up commits.

GitHub requests review according to [CODEOWNERS](../CODEOWNERS), independently
of diagnostic labels. At least one CODEOWNERS approval and all other configured
review requirements must be satisfied. A maintainer then merges the PR or
enables GitHub's native auto-merge.

### Contributor validation and review

PR validation is author-agnostic: author permissions and organization
associations do not determine which paths a contributor may change. Existing
path-specific validation and secret scanning still apply. CODEOWNERS and the
repository's configured review requirements determine who must review changes;
validation does not replace or waive those protections.

Utilities use engineering CODEOWNERS, while root files use the default
maintainer owner; Discovery Toolbox retains its maintainer-owned exception.
Draft PRs do not automatically request CODEOWNER reviews. After a new push,
check the latest commit's required checks and approval requirements rather than
relying on an older approval or diagnostic label.

### Workflow responsibilities

PR validation and diagnostic publishing run in separate trust contexts:

| Workflow | Trigger and scope | Responsibility |
| --- | --- | --- |
| [PR Review](pr-review.yml) | `pull_request` to `main`: opened, synchronize, reopened | Read-only classification, catalog validation, secret scanning, and required report handoff. |
| [Check Agent Removal Impact](check-agent-removal-impact.yml) | `pull_request` to any base branch: opened, synchronize, reopened | Read-only removal gate; skips validation only after successfully classifying the PR as unrelated to agent paths. |
| [PR Review Report](pr-review-report.yml) | Completed `workflow_run` for either source above | Verifies the source run, current PR head, jobs, and bounded artifact before publishing diagnostic feedback. Executes only trusted default-branch code. |
| [Update Registry](update-registry.yml) | Daily at 09:23 UTC, or manual dispatch on `main` | Batches meaningful generated-registry changes into a reviewed PR using the registry App. At most one trusted registry-refresh PR remains open; its snapshot is not rewritten. |

The source workflows use contents/PR read permissions and trusted base-SHA
validators, with the exact PR head checked out separately as data. Fork approval
policies apply, and merge conflicts must be resolved before `pull_request`
checks run. Neither source uses `pull_request_target` or an unsafe-checkout
exception.

Keep the existing required-check names: **Classify Changed Paths**, **Validate
PR**, **Secret Scan**, **Post Results**, and **Check if agent removal breaks
starter kits**. Do not add **Publish PR Feedback** as a required PR check:
`workflow_run` checks are associated with the default branch, not the source
PR head. Actual enforcement is configured in GitHub, not by this README.

### Reporting artifacts and failures

| Source | Attempt-scoped artifact | Single JSON member | Upload failure |
| --- | --- | --- | --- |
| PR Review | `pr-review-report-<run_attempt>` | `validation-results.json` | Fails the required **Post Results** handoff. |
| Agent removal | `agent-removal-report-<run_attempt>` | `agent-removal-results.json` | Warns without rewriting the independently computed gate decision; missing data fails reporting. |

Feedback is asynchronous and may be absent after cancellation, runner loss,
missing artifacts, or a reporting error. Consult source checks and logs rather
than waiting for a comment or label. PR Review's `pr-validation-passed` label
does not summarize removal, unit-test, or schema checks. Only its reporting
profile manages diagnostic labels and inline `COMMENT` reviews. Removal
reporting posts summary comments for blocked/error results and makes no writes
for success/no-op results. Neither profile approves, dismisses reviews, or merges.

The former auto-merge enrollment and release-manifest approval workflow is
retired. Maintainers merge PRs or enable GitHub's native auto-merge after the
required checks and human/CODEOWNER reviews are satisfied. Registry App
credentials are still needed to create registry refresh PRs.

See the [trust boundary and staged rollout](../../docs/actions-execution-policy.md)
before deploying changes to base-SHA validators, and
[workflow testing and troubleshooting](../../docs/validation-workflow-testing.md)
for local fixtures, optional branch-only runs, and missing feedback. The retired
event-exception payload does not remove any policy previously applied in GitHub;
administrator cleanup is separate.

### Validation details and test model

Catalog checks cover structure, schemas, policy, documentation, and security.
Top-level `skills/` contributions run the applicable source-content policies,
secret scan, dependency review, and code/capability scans, with the same
maintainer/contributions-reviewer ownership as agents and starter kits.
Skill scripts are inspected as data, never executed by catalog validation;
agent/starter-kit structural and schema rules do not impose their manifests on skills.
The blocking `POL-022` policy rejects Podman `Containerfile` names and `.in`
preprocessing conventions; use the
[Podman-to-Docker migration guide](../../docs/authoring-guides/podman-to-docker-migration.md)
or its linked migration skill. The check is static and does not build or execute
contributor-controlled container inputs.
The [agent](../../docs/authoring-guides/agent-authoring-guide.md) and
[starter-kit](../../docs/authoring-guides/starter-kit-authoring-guide.md)
authoring guides describe required files and content constraints. The
[validation rule reference](../../docs/validation-rules.md) explains rule IDs
and remediation.

Changed agent, starter-kit, and skill prose is also spellchecked. `SPELL-001`
annotations are advisory warnings: they never block merge. Code, identifiers,
URLs, and fenced Markdown examples are excluded.

Repository-owned validator tests live under [`.github/tests/`](../tests/) and
run in the **Unit Tests** workflow. They cover agents and starter kits through
trusted schema, policy, registry, and validator code. A local test command is:

```powershell
python -m pytest .github\tests\ -v
```

The contribution-security suites have an explicit `catalog` prefix:

- [`test_catalog_security_automation.py`](../tests/test_catalog_security_automation.py)
  checks content-scanner and supporting CI configuration contracts.
- [`test_catalog_schema_security.py`](../tests/test_catalog_schema_security.py)
  checks catalog schema invariants and governed documents.

Here, contributed content means agents and their tools, starter kits, skills,
quickstarts, and reference material, not utilities implementations. The suites
are not audits of `utilities/` code. Their concrete scanner paths and document
groups define current coverage; renaming a suite does not expand that coverage.
Infrastructure trust-boundary tests remain separately named
[`test_pr_review_workflow_security.py`](../tests/test_pr_review_workflow_security.py).

Agent tool authors may place focused `test_*.py` or `*_test.py` files beside a
tool. The registry records their presence as `auto:has-tests`, but catalog PR
validation does not execute submitted tool tests. Those tests may invoke
subprocesses, download models, or require GPUs; run them in your own isolated
environment or CI before submission.

Starter-kit folders may contain `kit.json`, Markdown documentation, compliant
Markdown images, and CommonJS (`.cjs`) source, including supporting tests.
Other source-code types remain disallowed. Submitted CommonJS is inspected
as data, not executed; trusted schema-security and starter-kit validator suites
cover catalog validation behavior.

See [validation workflow testing](../../docs/validation-workflow-testing.md)
for focused test commands and optional candidate-branch Linux runs.

### After merge

The weekly catalog audit reruns the modular rules across the full catalog and
runs Microsoft Security DevOps over `agents/`, `starter-kits/`, and `skills/`.
URLhaus/PhishTank reputation lookups and Docker Scout base-image CVE scans are
staged but currently disabled until their credentials, provider access, and
representative runs are validated. See the
[security process](../../SECURITY.md#repository-security-process) for ownership
and promotion criteria.

**Update Registry** rebuilds from current `main` daily at 09:23 UTC, or when
manually dispatched on `main`. Generated updates reach `main` through a separate
reviewed registry PR, not automatic merging. Maintainers can dispatch it after
an urgent catalog change instead of waiting for the daily batch.

The publication check ignores only generation timestamps and the starter-kit
snapshot's source commit when comparing payloads. Metadata-only regeneration
preserves the published snapshot. Real changes to entries, availability, tags,
versions, or schemas still produce a refresh. If a trusted same-repository
registry-bot refresh PR targeting `main` is open, new changes remain queued
until that PR is resolved and a later batch runs; automation does not rewrite
reviewed content or create another PR. API, generation, and schema errors fail
explicitly rather than being treated as an empty batch.

The registry App installation must grant Contents-write and
Pull-requests-write; the token step explicitly requests both. A 403 still needs
an owner to verify the App installation's approved grants, not a bypass of
human review.

## Routine dependency maintenance

Dependabot checks the five configured ecosystems monthly, on the first day of
the month at their configured UTC times. Minor/patch updates remain grouped,
with a seven-day cooldown and one open routine PR per ecosystem. Non-security
major upgrades require deliberate maintenance review. For pip requirements,
`increase-if-necessary` avoids raising a lower bound that already permits the
new version; exact pins can still be updated.

Pip targets cover the repository root and recursive subdirectories, including
`utilities/`, contributed content, hidden directories, and future top-level
projects. New supported manifests are discovered without editing a per-project
list. CI requirements remain explicitly targeted at `.github/`, and the utility
CLI's separate uv block remains enabled for uv lockfile updates. This
repository-wide dependency protection is separate from the catalog-scoped
content scanners. Dependencies written only in Dockerfile `RUN pip install`
commands are not pip manifests and are not discovered by these globs.

Security-update PRs retain their separate groups and GitHub's separate limit.
Monthly schedules, cooldowns, version-only `allow.update-types`, and routine
PR limits do not delay security updates. Automatic rebasing remains enabled
because disabling it would also affect security PRs. Existing PRs are not
automatically closed. Five routine open slots are not a monthly creation quota.

See the [Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)
for the distinction between version and security updates.

## CodeQL ownership

GitHub default setup publishes Python, JavaScript/TypeScript, and Actions
analyses. The custom catalog Python job currently provides additional security
queries as an artifact, so a successful default scan is not sufficient evidence
to remove it. An owner must configure equivalent default security-query
coverage and verify the published SARIF before that redundant job can be
retired. Do not disable either configuration or remove a required check as an
incidental schedule cleanup. DevSkim, capability reports, and the weekly
catalog/MSDO audit remain unchanged.

## Release refresh automation

The release worker keeps the mutable `current` tag, the
`Discovery-app-preview-release` GitHub Release, and the download table in
[`README.md`](../../README.md) in sync with the app that ships behind the
`aka.ms/discovery/download/*` short links. The homepage "Releases" sidebar
displays `published_at`, so the point of this automation is to keep that
timestamp fresh — the previous rolling release was showing "2 months ago"
even after the tag had been moved forward.

### The pieces

| Workflow | Purpose | Triggers |
| --- | --- | --- |
| [`refresh-current.yml`](refresh-current.yml) | Moves the `current` git tag to `main` HEAD, delete-and-recreates the `current` GitHub Release (fresh `published_at`, auto-generated notes), and opens a PR that bumps the README download table. | `workflow_dispatch` (manual button) + `repository_dispatch` (`event_type: app-released`) |
| ADO release pipeline task (future) | Calls the worker when a new app ships, supplying the three release inputs through `repository_dispatch`. Requires a GitHub App (recommended) or workload identity federation, per the [1ES PAT removal case study](https://eng.ms/docs/coreai/devdiv/one-engineering-system-1es/1es-docs/1es-security-configuration/configuration-guides/case-studies/azureauth-removing-pats). | `repository_dispatch` |

The worker accepts explicit release inputs from manual or event dispatch.
Scheduled download polling and live aka.ms link checks have been removed.

### Release asset policy

The release refresh must not upload installer files or any other custom
assets to the GitHub Release. Download links remain the stable `aka.ms`
redirects in the root README; release automation must not call `gh release
upload` or use an upload-asset action.

GitHub automatically displays `Source code (zip)` and `Source code (tar.gz)`
for every release backed by a git tag. Those two generated links cannot be
removed independently while `current` remains a tag-backed release. They are
not uploaded assets and do not contain the Windows installer binaries.

### Repository and branch guard

The worker is restricted to `github.repository == 'microsoft/discovery'` and
`github.ref == 'refs/heads/main'`. Dispatches in forks or from non-`main` refs
are skipped.

### Manual trigger

Run **Refresh current release** by hand from the
[Actions tab](https://github.com/microsoft/discovery/actions):

Fill in `version`, `previous_version`, and `previous_date` to retag, recreate
the release, and propose the README update.

### Local test helpers

The offline README patcher lets you validate regex/parsing changes from your
workstation before pushing:

- [`scripts/test-refresh-current-readme.ps1`](../../scripts/test-refresh-current-readme.ps1) —
  runs the exact regex substitutions from the worker's "Patch README.md"
  step against a copy of `README.md` and prints the resulting `git diff` so
  you can preview the PR contents.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/test-refresh-current-readme.ps1 `
    -NewVersion v0.15.13 -PreviousVersion v0.15.12 -PreviousDate 2026-08-28
```

### Dry-run mode for CI smoke tests

The worker accepts a `dry_run` boolean input on `workflow_dispatch`. When
`true`, it validates inputs and patches README in the workspace, but skips
everything that mutates external state:

| Step (worker) | dry-run behaviour |
| --- | --- |
| Move `current` tag | Skipped; prints what the retag would do. |
| Delete + recreate `current` release | Skipped; prints the notes preview. |
| Patch `README.md` in workspace | Runs (nothing pushed). |
| Push branch + open PR | Skipped; prints the branch name and PR title. |

Recommended first-run smoke test after this branch merges to `main`:

1. Actions → **Refresh current release** → *Run workflow*.
2. Fill in the same `version` / `previous_version` / `previous_date` the
   README already has, tick `dry_run: true`, and run. Verify the logs show
   the retag + rerelease + PR-open steps as `[dry-run] would run: ...`.
3. After verifying the dry run, dispatch without `dry_run` when ready to
   publish the release update.

### Permissions

- `refresh-current.yml` needs `contents: write` (retag, edit release, push
  branch), `pull-requests: write` (open the README PR), and `issues: write`
  (for the failure tracking issue). Uses `secrets.GITHUB_TOKEN`.

### Failure reporting

The worker's `report-failure` job records a failed refresh with a link to the run,
the triggering event, and a triage checklist.

**Issues are intentionally disabled on this public repo**, so the primary
output is written to the **Actions run's job summary** together with a
`::warning::` annotation on the run. The reporter probes `hasIssuesEnabled`
first and degrades to this summary path rather than failing; a broken run must
never be masked by a second "the reporter itself failed" error. Read the
failure detail on the run page under **Summary** (and in the maintainer
notification for the run).

If Issues are ever re-enabled (or the reporter is pointed at a private
tracking repo), the same job additionally opens or comments on a GitHub issue
labelled [`release-automation`](https://github.com/microsoft/discovery/labels/release-automation):

- The label is created idempotently on first failure with color `#d73a4a`.
- Deduplication: if an open issue with title `[release-automation] <workflow>
  failed` already exists, the job comments on it rather than opening a new
  one. Close the issue once you've reconciled state to reset the cycle.
- Any `gh issue` failure also falls back to the job-summary path.

Fires for invalid release inputs, README regex misses, retag/rerelease
failures, or PR-open failures.
