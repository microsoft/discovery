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

### Workflow responsibilities

PR validation and diagnostic publishing run in separate trust contexts:

| Workflow | Trigger and scope | Responsibility |
| --- | --- | --- |
| [PR Review](pr-review.yml) | `pull_request` to `main`: opened, synchronize, reopened | Read-only classification, catalog validation, secret scanning, and required report handoff. |
| [Check Agent Removal Impact](check-agent-removal-impact.yml) | `pull_request` to any base branch: opened, synchronize, reopened | Read-only removal gate; skips validation only after successfully classifying the PR as unrelated to agent paths. |
| [PR Review Report](pr-review-report.yml) | Completed `workflow_run` for either source above | Verifies the source run, current PR head, jobs, and bounded artifact before publishing diagnostic feedback. Executes only trusted default-branch code. |
| [Update Registry](update-registry.yml) | Relevant catalog pushes to `main`, or manual dispatch | Rebuilds generated registries and proposes changes in a separate PR using the registry App. Human review and maintainer-controlled merging still apply. |

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
The [agent](../../docs/authoring-guides/agent-authoring-guide.md) and
[starter-kit](../../docs/authoring-guides/starter-kit-authoring-guide.md)
authoring guides describe required files and content constraints. The
[validation rule reference](../../docs/validation-rules.md) explains rule IDs
and remediation.

Changed agent and starter-kit prose is also spellchecked. `SPELL-001`
annotations are advisory warnings: they never block merge. Code, identifiers,
URLs, and fenced Markdown examples are excluded.

Repository-owned validator tests live under [`.github/tests/`](../tests/) and
run in the **Unit Tests** workflow. They cover agents and starter kits through
trusted schema, policy, registry, and validator code. A local test command is:

```powershell
python -m pytest .github\tests\ -v
```

Agent tool authors may place focused `test_*.py` or `*_test.py` files beside a
tool. The registry records their presence as `auto:has-tests`, but catalog PR
validation does not execute submitted tool tests. Those tests may invoke
subprocesses, download models, or require GPUs; run them in your own isolated
environment or CI before submission.

Starter-kit folders cannot contain test files. They may contain `kit.json`,
Markdown documentation, and compliant Markdown images. Trusted schema-security
and starter-kit validator suites cover their behavior instead.

See [validation workflow testing](../../docs/validation-workflow-testing.md)
for focused test commands and optional candidate-branch Linux runs.

### After merge

The weekly catalog audit reruns the modular rules across the full catalog and
runs Microsoft Security DevOps over `agents/` and `starter-kits/`.
URLhaus/PhishTank reputation lookups and Docker Scout base-image CVE scans are
staged but currently disabled until their credentials, provider access, and
representative runs are validated. See the
[security process](../../SECURITY.md#repository-security-process) for ownership
and promotion criteria.

Catalog changes can also trigger **Update Registry**. Generated updates reach
`main` through a separate reviewed registry PR, not automatic merging.

## Release refresh automation

Three workflows work together to keep the mutable `current` tag, the
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
| [`probe-aka-ms.yml`](probe-aka-ms.yml) | Every hour, follows the aka.ms redirects, compares the resolved version to the version recorded in README, and calls `refresh-current.yml` when they drift. Runs only for `microsoft/discovery` on `main`; scheduled runs in forks exit as successful skips. | `schedule` (`0 * * * *`) + `workflow_dispatch` |
| ADO release pipeline task (future) | Same effect as the probe but event-driven — internal build POSTs `repository_dispatch` to GitHub the moment a new app ships. Draft PowerShell snippet lives in the chat history for this branch; ADO owners can adopt it when they're ready. Requires a GitHub App (recommended) or workload identity federation, per the [1ES PAT removal case study](https://eng.ms/docs/coreai/devdiv/one-engineering-system-1es/1es-docs/1es-security-configuration/configuration-guides/case-studies/azureauth-removing-pats). | `repository_dispatch` |

Both trigger paths funnel into the same worker (`refresh-current.yml`), so
adding the ADO event trigger later is additive — no changes to the poll
workflow are required.

### Release asset policy

The release refresh must not upload installer files or any other custom
assets to the GitHub Release. Download links remain the stable `aka.ms`
redirects in the root README; release automation must not call `gh release
upload` or use an upload-asset action.

GitHub automatically displays `Source code (zip)` and `Source code (tar.gz)`
for every release backed by a git tag. Those two generated links cannot be
removed independently while `current` remains a tag-backed release. They are
not uploaded assets and do not contain the Windows installer binaries.

### How the probe knows a new version shipped

`aka.ms/discovery/download/current` 301-redirects to a versioned filename on
Azure Front Door:

```text
$ curl -sI https://aka.ms/discovery/download/current
HTTP/1.1 301 Moved Permanently
Location: https://.../discoveryexpress/Discovery-app-0.15.12-preview-win-x64.exe
```

The probe:

1. Reads `Current release: <strong>vX.Y.Z</strong>` from `README.md`.
2. Extracts `X.Y.Z` from the `Location` header on both the `current` and
   `previous` aka.ms redirects.
3. HEADs the `previous` target blob and reads its `Last-Modified` header to
   derive the `previous_date` column.
4. If the aka.ms `current` version differs from the README `current`
   version — **and** no `release/refresh-current-vX.Y.Z` branch already
   exists on the remote (debounce) — it calls `gh workflow run
   refresh-current.yml` with the three parsed inputs.

### Repository and branch guard

GitHub evaluates `schedule` workflows from each repository's default branch,
including forks where Actions and scheduled workflows are enabled. The probe
therefore guards both jobs with `github.repository == 'microsoft/discovery'`
and `github.ref == 'refs/heads/main'`. A scheduled run may still appear in a
fork's Actions history, but it performs no steps and completes successfully.
Manual dispatches from non-`main` refs are skipped in the same way.

### Manual trigger

You can always run either workflow by hand from the
[Actions tab](https://github.com/microsoft/discovery/actions):

- **Refresh current release** — fill in `version`, `previous_version`,
  `previous_date` when you want to force the retag + rerelease + README PR
  regardless of what aka.ms says.
- **Probe aka.ms Discovery download** — runs the poll immediately without
   waiting for the next hourly schedule tick.

### Local test helpers

Two PowerShell scripts mirror the workflow's runtime logic so you can validate
regex/parsing changes from your workstation before pushing:

- [`scripts/test-probe-aka-ms.ps1`](../../scripts/test-probe-aka-ms.ps1) — hits
  the live `aka.ms/discovery/download/{current,previous}` endpoints and
  replays the probe's decision matrix against your local `README.md`.
- [`scripts/test-refresh-current-readme.ps1`](../../scripts/test-refresh-current-readme.ps1) —
  runs the exact regex substitutions from the worker's "Patch README.md"
  step against a copy of `README.md` and prints the resulting `git diff` so
  you can preview the PR contents.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/test-probe-aka-ms.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/test-refresh-current-readme.ps1 `
    -NewVersion v0.15.13 -PreviousVersion v0.15.12 -PreviousDate 2026-08-28
```

Sample probe output:

```text
aka.ms current  -> v0.15.12
aka.ms previous -> v0.15.11
README current  -> v0.15.12
previous Last-Modified header -> Tue, 18 Aug 2026 13:24:38 GMT
previous_date -> 2026-08-18

DECISION: no-op (README already at v0.15.12)
```

### Dry-run mode for CI smoke tests

Both workflows accept a `dry_run` boolean input on `workflow_dispatch`. When
`true`, they perform every read-only step (probe, notes generation, README
patch in the workspace) but skip everything that mutates external state:

| Step (worker) | dry-run behaviour |
| --- | --- |
| Move `current` tag | Skipped; prints what the retag would do. |
| Delete + recreate `current` release | Skipped; prints the notes preview. |
| Patch `README.md` in workspace | Runs (nothing pushed). |
| Push branch + open PR | Skipped; prints the branch name and PR title. |

The probe skips the final `gh workflow run refresh-current.yml` call and
prints the exact command it would have issued.

Recommended first-run smoke test after this branch merges to `main`:

1. Actions → **Refresh current release** → *Run workflow*.
2. Fill in the same `version` / `previous_version` / `previous_date` the
   README already has, tick `dry_run: true`, and run. Verify the logs show
   the retag + rerelease + PR-open steps as `[dry-run] would run: ...`.
3. Actions → **Probe aka.ms Discovery download** → *Run workflow* with
   `dry_run: true`. Verify the decision line matches
   `DECISION: no-op` (or `[dry-run] would run: gh workflow run …` if a new
   release has just shipped).
4. Once both dry-runs look clean, the scheduled probe will start firing on
   its hourly cron and the worker will act on real inputs.

### Permissions

- `refresh-current.yml` needs `contents: write` (retag, edit release, push
  branch), `pull-requests: write` (open the README PR), and `issues: write`
  (for the failure tracking issue). Uses `secrets.GITHUB_TOKEN`.
- `probe-aka-ms.yml` needs `actions: write` (call `gh workflow run`),
  `contents: read` (read `README.md`), and `issues: write` (for the failure
  tracking issue). No cross-boundary credentials.

### Failure reporting

Both workflows have a `report-failure` job that runs only `if: failure()`.
When any earlier job fails it records the failure — a link to the failing run,
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

Fires for **any** failure — parser drift (aka.ms URL format changed),
README regex miss, broken aka.ms link (the worker HEADs every download
URL after patching), retag/rerelease failure, PR-open failure, or the
`gh workflow run` dispatch call failing.

### Link verification

Before the worker opens the README PR, it enumerates every
`https://aka.ms/discovery/download/...` URL in `README.md` and HEADs each
one. The job fails (which triggers `report-failure`) if any URL returns
anything other than a 3xx with a non-empty `Location` header. This catches
upstream aka.ms breakage before a stale/broken README lands on `main`.
