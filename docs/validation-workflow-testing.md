# Testing validation workflows

Use the manually dispatched **Validate Everything** workflow to test pipeline
changes without modifying an open pull request. The workflow has two modes.

The repository helper is the preferred interface. It uses the current branch by
default and requires an authenticated GitHub CLI session (`gh auth login`).

For read-only source validation, trusted reporting, staged production bootstrap,
and retirement of any previously deployed event exception, see the
[workflow trust boundary and rollout guide](actions-execution-policy.md). Passing local
tests does not prove GitHub event delivery or change live settings.

## Test the PR Review reporting split

PR Review runs read-only on `pull_request`; PR Review Report publishes feedback
on `workflow_run`. The required **Post Results** check stays in the read-only
workflow as the attempt-scoped artifact handoff. The separate **Publish PR
Feedback** job is not a PR required check.

Run the workflow contracts and the reporter's behavioral tests:

```powershell
python -m pytest .github\tests\test_pr_review_workflow_security.py `
  .github\tests\test_report_pr_review.py `
  .github\tests\test_actions_execution_policy.py `
  .github\tests\test_security_automation.py -q
```

These cover fork runs with empty PR associations, source identity, current-head
and rerun freshness, hostile/missing artifacts, labels, and comment-only
feedback. Live reporting starts only after its workflow and trusted script are
merged to `main`. Then test valid/invalid same-repository and fork PRs, a new push,
and partial reruns; inspect **PR Review Report** logs if feedback is absent.
See the [reporting trust boundary](actions-execution-policy.md#pr-review-validation-and-reporting).

## Troubleshoot missing or stale feedback

Inspect the source workflow first, then **PR Review Report**. The reporter is
non-required; comments and labels may be delayed, stale, or absent without
changing the source checks. A successful dispatch or a diagnostic label is not
evidence that every required check passed.

| Symptom | Interpretation and next step |
| --- | --- |
| No source run for a fork or conflicted PR | Check GitHub's fork approval policy and resolve merge conflicts. PR Review targets `main`; removal validation covers all base branches. Both use opened/synchronize/reopened activities, not label events. |
| No reporter run | Confirm its workflow and trusted scripts exist on the default branch. It subscribes only to the two literal source workflow names, and skips cancelled or non-`pull_request` sources. Manual shadow validation does not invoke it. |
| PR Review's **Post Results** fails | Inspect the `validation-results` download and `pr-review-report-<run_attempt>` upload. This is a required handoff, unlike removal's optional transport. |
| Removal upload warns or its report artifact is missing | The existing gate decision remains authoritative. Inspect source logs and the reporter's missing-artifact error; do not make reporting required or restore a write-enabled validator. |
| `--report-json` is unrecognized, or the trusted protocol script is absent | The target base is unprepared. Follow the [staged rollout](actions-execution-policy.md#production-bootstrap-and-rollout); never execute the PR copy as a fallback. |
| Reporter says the source is superseded, closed, cancelled, or has a changed head | Inspect the newest source run and its attempt-scoped artifact. Skipping obsolete feedback is intentional. A rerun cannot reuse an older attempt's reporting artifact. |
| Reporter cannot identify a unique open PR | Multiple PRs may share a head branch/SHA across base branches. Do not guess a target or put a preferred PR number in the artifact; investigate the API associations. |
| Passing PR Review label but a red removal/unit/schema check | Expected separation: the label covers only PR Review and may lag the head. Required checks and human review, not labels, govern merge eligibility. |
| No removal comment on success/no-op | Expected. Only blocked/error removal results produce diagnostic comments; they do not change PR Review labels. |
| Maintainer override does not apply | Non-fork PRs only: verify label presence, its latest applier's current write/maintain/admin permission, then rerun the removal check. API errors fail closed. Applying a label alone does not trigger a run. |

Reporter API/protocol errors are visible in its logs, not a reason to weaken
branch protection. Use local fixtures below to investigate computation and
artifact handling without producing real PR feedback.

## Test agent-removal migration locally

The removal check now runs read-only on `pull_request`. Its required job name
is unchanged and all base branches remain covered. **PR Review Report** also
publishes removal diagnostics, using an isolated source profile; it does not
change removal gate decisions or PR Review labels.

Run from the repository root, using the existing environment first:

```powershell
$env:PYTHONUTF8 = "1"
python -m pytest .github\tests\test_check_agent_removal_impact.py `
  .github\tests\test_report_agent_removal_impact.py `
  .github\tests\test_agent_removal_migration_integration.py `
  .github\tests\test_report_pr_review.py `
  .github\tests\test_pr_review_workflow_security.py `
  .github\tests\test_actions_execution_policy.py `
  .github\tests\test_security_automation.py -q
python -m pytest .github\tests\ -q -ra -n 2 --dist worksteal
git --no-pager diff --check
```

Restore dependencies from `.github/requirements-ci.txt` only after a missing
dependency failure. On Windows, put Git's `usr\bin` directory on PATH for
content-sniffing tests that require `file.exe`. Node.js is needed for tests of
the actual inline workflow JavaScript. Linux CI remains authoritative for Bash
and native Actions scheduling.

The offline tests execute the real gate against temporary trusted-base/PR
fixtures, pass its exact output bytes through the workflow finalizer and a real
ZIP, and invoke the real reporter with a recording fake API. They cover kit
resolutions, authorized/denied/fork overrides, GET-only validation, missing or
contradictory local results, no-op without checkout/Python, unprepared bases,
fork association gaps, provenance, stale heads/attempts, partial reruns,
hostile/oversized artifacts, and reporter isolation. Fixture-case manifests
record gate exits, outcomes, source conclusions, and captured mutations in
pytest temporary directories; these are not real GitHub writes.

No push, PR, production merge, label write, or settings change is required.
Capture JUnit and fixtures with `--junitxml=<evidence>\focused.xml`,
`-o junit_family=xunit1`, and `--basetemp=<new-evidence-directory>\fixtures`
if persistent local evidence is wanted. Always use a new basetemp directory.

For optional Linux verification, deliberately commit/push a non-default
candidate branch and use the existing registered workflow, without a PR number:

```powershell
python .github\scripts\run_validation_workflow.py `
  --ref test/agent-removal-migration --checks=unit-tests `
  --reason "Fixture-only removal migration verification"
```

Verify the resulting run's SHA and final unfiltered test result, not just
dispatch success. This proves candidate tests on Linux, not the removal
workflow's PR trigger, real source-artifact transport, `workflow_run` delivery,
token grants, or required-check attribution. Those need the
[staged production rollout](actions-execution-policy.md#production-bootstrap-and-rollout)
and post-deployment acceptance. Never bypass a missing trusted-base protocol by
executing the PR copy.

## Test a candidate branch

Leave `pr_number` blank. Both full-catalog jobs run from the selected branch and
fail normally when the branch's validators, schemas, or tests find a problem.

```console
python .github/scripts/run_validation_workflow.py --reason="Candidate branch smoke test"
```

### Run only a subset of the checks

By default every full-catalog check runs. Pass `--checks` (or set the **checks**
input in the UI) to run just one: `unit-tests`, `catalog-validation`,
`starter-kits`, or `schemas`. Unselected checks report as skipped and never fail
the run. This is ignored in shadow-PR mode.

```console
python .github/scripts/run_validation_workflow.py --checks=schemas --reason="Schema regression only"
```

## Shadow-test an open pull request

Set `pr_number` to any open pull request in `microsoft/discovery`. Internal
branches and external forks use the same command because the workflow resolves
the PR head repository through the GitHub API.

```console
python .github/scripts/run_validation_workflow.py --pr-number=123 --reason="Queued PR canary"
```

Pass `--ref <branch-or-sha>` to test a pushed ref other than the current branch.

The shadow job executes validator code only from the selected repository branch.
It checks out the PR head separately as untrusted data, disables persisted Git
credentials, and uses a read-only token. It then creates an ephemeral integration
tree by merging the PR commit into the selected branch on the runner. A merge
conflict is reported as evidence rather than changing either branch. Clean trees
are scanned without executing PR-supplied scripts or tests.

The workflow does not comment, label, approve, merge, or publish a check to the
target PR. Validation findings are collected in the workflow summary and the
`shadow-pr-<number>` artifact; the job remains report only so it cannot alter
merge eligibility.

The shadow removal check intentionally receives no override token, so it does
not verify maintainer-label overrides. It runs the selected branch's validator
against the ephemeral integration tree, not the native PR workflow's exact
trusted-base/head pair. Its findings can therefore differ from the required
removal check and do not replace it.

To launch the same modes in the GitHub UI, open **Actions**, select **Validate
Everything**, choose **Run workflow**, select the candidate branch, and either
leave **pr_number** empty or enter an open PR number.

## Run an individual schema validator on demand

The **Validate Agent Schemas**, **Validate Starter Kits**, and **Validate
Starter Kit Schema** workflows normally run only on pull requests. Each now also
accepts a manual trigger: open **Actions**, select the workflow, choose **Run
workflow**, and pick a branch. On manual dispatch they skip the changed-file
detection and run their full regression guard against the selected ref, so you
can confirm the whole catalog still validates without opening a PR.

## Inspect a run

```console
gh run list --repo microsoft/discovery --workflow validate-everything.yml --limit 10
gh run watch <run-id> --repo microsoft/discovery
gh run view <run-id> --repo microsoft/discovery --log-failed
gh run download <run-id> --repo microsoft/discovery --pattern "shadow-pr-*"
```

Shadow mode intentionally does not execute Python, shell scripts, or tests from
the PR checkout. Use branch mode to test trusted pipeline code. The normal
`pull_request` workflows remain the final test of event wiring and required
check behavior.