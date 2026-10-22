# Actions execution policy: read-only validation and trusted reporting

## Decision and acceptance criteria

Discovery no longer uses `pull_request_target` in any workflow. The final
agent-removal exception payload has been retired rather than broadened or left
empty. No new event exception, actor allowlist, or change to branch protection
is required by this implementation.

GitHub's announced November 2, 2026 default execution protection for affected
public repositories is the reason for retiring the target-event workflows.
SHA-pinning actions, token permissions, and `allow-unsafe-pr-checkout` are not
event-policy exceptions. Neither PR validation workflow uses that checkout input.

Acceptance requires:

- Read-only PR validation, including same-repository and fork PRs.
- Existing required-check names and removal decisions preserved.
- Trusted base code and dependencies; the exact PR head checked out only as data,
  with no persisted credentials, PR executable caches, or App credentials.
- Separate, non-required reporting that cannot approve, dismiss reviews, or merge.
- Explicit errors for invalid/missing results and stale-source protection before
  any diagnostic write.
- Pre-merge fixture evidence distinguished from live GitHub acceptance.

## Workflow boundaries

| Workflow | Event and scope | Authority |
| --- | --- | --- |
| [PR Review](../.github/workflows/pr-review.yml) | `pull_request`, `main`, opened/synchronize/reopened | Read-only validation and secret scanning. Required checks: **Classify Changed Paths**, **Validate PR**, **Secret Scan**, **Post Results**. |
| [Check Agent Removal Impact](../.github/workflows/check-agent-removal-impact.yml) | `pull_request`, all base branches, default opened/synchronize/reopened activities | Read-only gate. Required check name remains **Check if agent removal breaks starter kits**. |
| [PR Review Report](../.github/workflows/pr-review-report.yml) | Completed `workflow_run` for either literal source name | Actions read and PR/issue write; default-branch reporting code only. **Publish PR Feedback** must not become a required PR check. |

Normal fork-run approval policies apply; first-time contributors may need a
maintainer to authorize a run. Conflicted PRs must resolve their merge conflicts
before `pull_request` workflows can run. Workflow-level path filters are absent
so irrelevant PRs do not strand required checks.

Source dependency installers use the trusted base's constraints when available.
Their existing compatibility fallback installs the named validator packages
unpinned if that base lacks the constraints file; it never reads PR-supplied
requirements. This fallback does not provide new CLI/protocol support. Prepare
trusted code and constraints before cutover rather than relying on it as a
single-merge bootstrap.

## PR Review validation and reporting

PR Review executes validators and dependency constraints from the trusted base
SHA. Its exact head checkout is isolated as data. **Post Results** stays in the
read-only workflow and republishes `validation-results.json` as
`pr-review-report-<run_attempt>`. Missing downloads or failed uploads still fail
that required handoff; this migration does not change PR Review's behavior.

The [reporter](../.github/scripts/report_pr_review.py) has two fixed source
profiles, not artifact-selected handlers. Each fixes the workflow path, API
workflow ID check, expected jobs, base-branch scope, artifact prefix, and schema.
PR Review remains main-only. Removal reporting retains all-base-branches scope.
Concurrency includes source workflow identity so the two flows do not displace
each other's pending reports.

The reporter refetches source metadata from GitHub and verifies repository,
workflow path/ID, `pull_request` event, completed status, and latest attempt.
It resolves the current open PR using source head repository, owner/branch and
exact SHA; it does not trust artifact PR numbers or populated PR association
arrays (which can be empty for fork runs). Ambiguous matches fail without
writes. Closed/stale/deleted-fork/cancelled/superseded runs are skipped with a
notice. Freshness is checked again after reading the artifact, before writes.
Partial reruns select the latest completed result per required job.

Only the exact run's attempt-scoped artifact is accepted. Origin metadata,
duplicate/expired artifacts, ZIP members, compressed/uncompressed sizes (5 MiB),
JSON types and outcome consistency are checked. Artifacts are read in memory,
never extracted or executed. Guidance links must stay within repository docs.
Untrusted text is escaped and comments are bounded.

Only the reporter's PR Review profile manages the allowlisted diagnostic labels
and inline `COMMENT` reviews. The `pr-validation-passed` label covers PR Review's
four jobs, not every required repository check; it can lag behind the current
head if reporting is delayed or fails. GitHub's CODEOWNERS requests are
independent of these labels. Labels are not merge gates. Reporting never
approves, requests changes,
dismisses a blocking review, or enables merging. A failed required check cannot
become a passing label from artifact content alone.

## Agent-removal validation and reporting

The [gate](../.github/scripts/check_agent_removal_impact.py) compares the trusted
base registry with valid head metadata and checks active kits' required refs.
Renames/removals still block unless the PR fixes the kit or a valid non-fork
maintainer override is verified. Optional refs, archived/deleted kits, and
replacement refs to valid agents retain their existing behavior.

Option B remains restricted to non-fork PRs as repository policy, not because
fork label metadata is inherently unreadable. Override checks use only GETs:
paginated labels/events and the latest applier's current write/maintain/admin
permission. Missing or unavailable authorization does not grant an override.
Apply `starter-kit-impact-approved` and rerun the removal check; labeling alone
is not a configured trigger. Fork PRs must resolve their kit references.

The [versioned protocol](../.github/scripts/agent_removal_report.py) records
`success`, `blocked`, `not_applicable`, or `error`, with the gate exit code,
removed paths, affected kits, issues, override decision/reason, and guidance.
The validator never posts comments, even when supplied a token. Existing CLI
callers, including the report-only shadow check, retain their gate exit codes.
Unreadable/corrupt input is an error, not an empty successful registry.

`--report-json` optionally writes schema version 1 alongside the CLI's logged
result. `GITHUB_TOKEN` supplies the read-only override token by default; the
legacy `--github-token` option is also accepted. The gate exits 0 for passing
validation and 1 for blocked/error results. `not_applicable` is produced only by
the workflow's successful changed-path classification, not by the gate CLI.
The protocol checker exits 0 for a valid record matching the expected gate exit,
including a valid blocked record; that does not clear the validator's failure.
Removal reports use the fixed starter-kit authoring guide, not artifact-chosen
guidance URLs.

Only successful classification explicitly finding no relevant paths can produce
`not_applicable`; this needs neither checkout nor Python setup. Classification,
setup, missing/invalid local output, and outcome contradictions fail the required
gate. Relevant results are validated with the trusted protocol implementation.
Finalization and upload are attempted after validator failure unless cancelled.
Runner loss/timeouts can still prevent any artifact.

The diagnostic artifact is `agent-removal-report-<run_attempt>`, containing only
`agent-removal-results.json`. Unlike PR Review's existing required handoff,
removal artifact upload is optional transport: failure emits a warning and
summary, but cannot rewrite the gate decision or swallow a validator failure.
Missing artifacts fail the non-required reporter explicitly.

Removal reporting posts only diagnostic issue comments for blocked/error
results, with run links and resolution guidance. Success/no-op results make no
writes. Source API job/run conclusions must match the report's gate outcome.
The handler cannot alter PR Review labels or reviewer state. Reporting failures
leave the independent required check unchanged.

## Production bootstrap and rollout

Local fixture tests require no merges. Production is different: source
validators run from the PR's **base SHA**, and the reporter must exist on the
default branch for `workflow_run` delivery.

Use two staged changes, not a blind single-merge cutover:

1. Prepare the trusted base with backward-compatible `--report-json` support,
   the protocol module, and both fixed reporter profiles. In that transitional
   change, preserve the old source trigger and legacy invocation behavior;
   structured mode must suppress direct posting. Keep transitional contracts
   consistent with that intermediate state.
2. After preparation reaches every supported target base, land the read-only
   source cutover, remove obsolete direct commenting and the final event
   exception, and enable the final no-target contracts. The read-only workflow
   configuration in this repository represents that final state. For other base branches, prepare
   the protocol there before enabling their cutover checks.

An unprepared base fails explicitly. Never run the PR's validator/protocol copy
as a fallback. Do not add a privileged manual artifact-replay path.

After default-branch deployment, use controlled same-repository/fork canaries:
no-op, valid removal, blocked removal, fix-and-push, maintainer override,
reopen/synchronize, and rerun failed jobs. Check current required-check
attribution and real artifact/reporting delivery. Keep reporting non-required.
Do not approve intentionally broken PRs or weaken branch protection.

## Retiring a previously deployed exception

Deleting the former JSON payload does **not** delete a live GitHub policy.
An administrator must separately inspect **Settings > Actions > Policies** and
**Policy insights**, including inherited organization/enterprise policies:

```powershell
gh api -H "X-GitHub-Api-Version: 2026-03-10" `
  "repos/microsoft/discovery/actions/policies?has_parents=true&per_page=100" `
  --paginate --slurp
gh api repos/microsoft/discovery/branches/main/protection/required_status_checks
```

If the former repository-owned **Reviewed pull request automation** exception
was applied, save its payload, verify its recorded ID and exact scope, then
delete only that policy after cutover acceptance:

```powershell
gh api --method DELETE -H "X-GitHub-Api-Version: 2026-03-10" `
  repos/microsoft/discovery/actions/policies/POLICY_ID
```

Do not delete inherited or unrelated policies. An empty policy listing is not
proof that GitHub's default protections are absent. No settings are changed by
these source edits. Record administrator actions and canary run URLs separately.
If reporting breaks, keep the read-only gate and its logs; do not restore the
target event, relax branch protection, or make reporting required.

## PR approval and merging

Automatic auto-merge enrollment and its release-manifest approval exception
remain removed. All PRs, including manifest-only and generated registry updates,
follow human/CODEOWNER review. Maintainers merge or enable native auto-merge.
The retired job was not required in the October 21, 2026 settings snapshot;
confirm current protection settings during deployment rather than treating
historical observations as current enforcement evidence.

[Update Registry](../.github/workflows/update-registry.yml) independently creates
PRs and still needs `REGISTRY_APP_ID` and `REGISTRY_APP_PRIVATE_KEY`. Do not remove
those credentials as part of this retirement.

## Verification and ongoing ownership

See [Testing validation workflows](validation-workflow-testing.md) for local and
optional branch-only commands. Configuration contracts and offline API fixtures
do not prove hosted token scopes, event delivery, or live settings.
Review future source profiles, permissions, action pins, and dependency changes
together. Keep target-event regression contracts and preserve required-check
names and CODEOWNERS protections.

## References

- [GitHub announcement and November 2 deadline](https://github.blog/changelog/2026-09-17-workflow-execution-protections-in-github-actions-generally-available/)
- [Governing workflow execution and policy insights](https://docs.github.com/en/actions/how-tos/administer/control-workflow-execution)
- [Securely using pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
- [Actions policies REST API](https://docs.github.com/en/rest/actions/policies)
