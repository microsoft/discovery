# Testing validation workflows

Use the manually dispatched **Validate Everything** workflow to test pipeline
changes without modifying an open pull request. The workflow has two modes.

The repository helper is the preferred interface. It uses the current branch by
default and requires an authenticated GitHub CLI session (`gh auth login`).

## Test a candidate branch

Leave `pr_number` blank. Both full-catalog jobs run from the selected branch and
fail normally when the branch's validators, schemas, or tests find a problem.

```console
python .github/scripts/run_validation_workflow.py --reason="Candidate branch smoke test"
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

To launch the same modes in the GitHub UI, open **Actions**, select **Validate
Everything**, choose **Run workflow**, select the candidate branch, and either
leave **pr_number** empty or enter an open PR number.

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