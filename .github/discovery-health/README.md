# Discovery Health

Discovery Health runs live, programmatic tests for every agent and tool in
[`agents/`](../../agents) against a dedicated Microsoft Discovery test
environment. It publishes a public scorecard on GitHub Pages.

The same PowerShell 7 entry point runs on a Windows 11 workstation and on
GitHub-hosted Linux runners. Docker isn't required: images build remotely in
Azure Container Registry (ACR). **No AI runs in the harness.** Prompts, tool
inputs and assertions come from deterministic specs or fixed templates. Only the
agent under test uses its own model, inside Discovery.

## What gets tested

| Stage | Proves | Where | Depends on |
| --- | --- | --- | --- |
| `discover` | YAML parses, image reference, tool bindings, spec validity, fingerprints | Runner | — |
| `build` | Dockerfile builds; the image is pushed to `discovery-github-test/<image>:<fingerprint>-<stamp>` with OCI labels | One ACR multi-step run per tool | `discover` |
| `image-smoke` | The image starts, interpreters and action entrypoints exist, plus optional spec checks | Same ACR run (`cmd` steps) | `build` |
| `tool-register` | `Microsoft.Discovery/tools` is accepted and provisioned (tagged `discovery-github-test=true`) | ARM | `build`, or an existing image for the fingerprint |
| `tool-run` | The tool executes on a matching nodepool with deterministic inputs; logs, exit code and receipt are asserted | `POST {workspace}/tools/projects/{project}:run` | `tool-register` (+ `image-smoke`) |
| `agent-register` | The patched `agent.yaml` is accepted by `:upsertAgent` and the deployment operation succeeds | Discovery data plane | `tool-register` for every bound tool |
| `round-trip` | Agent, model and **every expected tool** are called, with tool success, receipt and expected text verified | Investigation → conversation → responses | `agent-register` (+ `tool-run`) |

**How dependencies and timeouts are handled:**
- Tools of one agent are isolated from each other. A failure never stops other tools or agents.
- Dependent stages are recorded as `blocked`, `untested` or `inconclusive`, and are never attempted.
- In-flight ACR builds, tool runs and responses are cancelled at the run deadline or on cancellation.

**Statuses:** `passed`, `cached`, `warning`, `failed`, `blocked`, `skipped`, `untested`, `inconclusive`.

**Failure categories:**
- `contribution`: a problem in the agent's Dockerfile, YAML, commands, assertions or behavior.
- `infrastructure`: quota, capacity, throttling, timeouts, or auth.
- `harness`: a defect in the test framework.

Only `contribution` failures mark an agent `failing`.

**Agent states on the scorecard:**
- `healthy`: every applicable stage passed with full coverage.
- `partial`: everything testable passed, but some stages are `untested`, such as a missing spec, no nodepool capacity, or trusted configuration that isn't available.
- `inconclusive`: infrastructure prevented a verdict.
- `failing`: at least one contribution failure was found.

The score (0–100) weights `build` 20, `image-smoke` 10, `tool-register` 15,
`tool-run` 20, `agent-register` 10 and `round-trip` 25. Untested stages count
as zero; they're never treated as not applicable.

## Requirements

- PowerShell 7.2 or later (`pwsh`). Windows PowerShell 5.1 is not supported.
- Azure CLI (`az`), logged in to the test tenant. CI uses GitHub OIDC.
- Python 3 with PyYAML (`python -m pip install -r .github/requirements-ci.txt`). The harness uses Python only to convert YAML to JSON.
- Git and Git LFS. Build contexts come from git objects (`git archive`), so Windows and Linux build identical bytes.
- `tar` (built into Windows 10+ and Linux).

## Quick start (Windows 11 or Linux)

```powershell
Copy-Item .github/discovery-health/config.template.json .github/discovery-health/config.json   # gitignored; fill in values
az login --tenant <tenant-id>

# Plan only (no Azure calls): shows agents, tools, shards and spec coverage
pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 plan -Agents chembl,aizynthfinder

# Individual tests
pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 run -Agents chembl -Stages build
pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 run -Agents chembl -Stages tool-register,tool-run
pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 run -Agents chembl -Stages all -FailOn contribution

# Test uncommitted edits (warns about untracked files and CRLF normalization)
pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 run -Agents chembl -Source worktree

# Build a local scorecard from one or more result folders
pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 report -ResultsDir .discovery-health/run-20260101-000000 -Site -Bootstrap

# Preview cleanup of stale discovery-github-test resources
pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 cleanup -DryRun
```

Output goes to `.discovery-health/<command>-<timestamp>/` (gitignored):

| Path | Contents |
| --- | --- |
| `results/<agent>/<tool or _agent>/<stage>.json` | One atomic result per stage (public fields only) |
| `operations/*.json` | Registry of submitted remote operations, used for cancellation and reaping |
| `evidence/…` | **Private** raw ACR logs, tool-run logs, payloads and response JSON |
| `report/` | `summary.md`, `junit.xml`, `results.json`, plus `site/` when `-Site` is set |

### Commands

| Command | Purpose |
| --- | --- |
| `plan` | Discover and select agents, then write `plan.json` (expected results) and `matrix.json` (shards). No Azure calls. |
| `run` | Run stages for `-Agents` or for a plan shard (`-PlanPath … -Shard N`). Use `-DryRun` to print the DAG only. |
| `report` | Merge results, synthesize `inconclusive` for lost items, write the summary and JUnit, and build the scorecard (`-Site`). `-FromCheckpoints` and `-ReapOrphans` recover from lost shards. |
| `cleanup` | Delete stale `discovery-github-test` resources in dependency order. `-DryRun` previews; `-All` removes everything the tests created. |
| `evidence` | Download a run's private evidence: `evidence -RunId <id>`. |
| `scaffold-spec` | Write deterministic spec skeletons for `-Agents` that have no spec. |
| `validate-specs` | Validate every spec against the schema and the catalog. |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success, or failures that don't trip `failOn` |
| `1` | Failing agents (`-FailOn contribution`) or any failure (`any`) |
| `2` | Cleanup refused: resources not tagged `discovery-github-test=true` |
| `3` | The scorecard history couldn't be loaded and `-Bootstrap` wasn't set |
| `4` | Harness error |

## Configuration

Precedence (highest first):

1. Command-line parameters
2. `DH_*` environment variables (scalars as text; objects and arrays as JSON; `DH_CONFIG_JSON` for a full overlay)
3. `config.json`
4. Built-in defaults

The file is validated against [`schemas/config.schema.json`](schemas/config.schema.json).

| Key | Purpose |
| --- | --- |
| `subscriptionId`, `tenantId`, `resourceGroup`, `location` | Test subscription and the resource group (tagged) for `Microsoft.Discovery/tools` |
| `acrName`, `acrResourceGroup`, `acrAgentPool`, `acrTimeoutSeconds` | Test registry (tagged). Use a dedicated agent pool and up to 28800 s on Premium for large GPU images. |
| `workspaceEndpoint`, `project`, `apiVersion`, `chatModel` | Dedicated Discovery workspace and project. GA `2026-06-01` by default; preview routes are supported. |
| `projectResourceId` | Optional ARM id of the Discovery project. When set, cleanup refuses data-plane deletions unless the project is tagged `discovery-github-test=true`. |
| `nodePools` | `[{ id, skus[], gpu }]`. Tool runs and round trips need a pool whose SKUs intersect the tool's `recommended_sku`; otherwise the stage is `untested`. |
| `outputStorageContainerId` | Optional `Microsoft.Discovery/storagecontainers` id used to persist tool-run outputs |
| `evidenceStorage` | `{ account, container, resourceGroup }`. Private storage for raw evidence, run checkpoints, the image ledger and a scorecard mirror. Required in CI. |
| `testTag`, `acrRepositoryPrefix`, `namePrefix` | Markers (`discovery-github-test`, `discovery-github-test`, `dgt-`). `namePrefix` must be non-empty. |
| `rebuild` | `{ mode: changed\|always, maxImageAgeDays }`. Unchanged fingerprints reuse their newest image until it's older than the limit. |
| `concurrency`, `budgets` | Limits per class: `acr`, `toolRegister`, `toolRun`, `gpuToolRun`, `agentRegister`, `roundTrip`. Budgets are split exactly across shards; work over budget is `skipped`. Concurrency is split across shards with at least one slot per shard, so the effective maximum is `max(limit, shards)`. `plan` warns when shards exceed a limit. |
| `timeouts`, `deadlineMinutes`, `pollSeconds` | Per-stage limits. Nothing starts after the run deadline, and in-flight work is cancelled. |
| `roundTrip` | `{ enabled, maxAttempts, deleteInvestigationOnPass }` |
| `cleanup` | `{ afterRun: none\|all, retentionDays, retainFailedDays, keepImagesPerRepo, maxRunAgeHours }` |
| `templateVariables` | Values for agent YAML placeholders such as MCP connection names and endpoints. **Never applied in PR runs.** |
| `failOn` | `contribution` (default), `any` or `none` |

## Azure test environment

Use a dedicated environment. Never point the harness at production.

1. **Resource group** for tools, tagged `discovery-github-test=true`. Preflight and cleanup refuse untagged groups.
2. **Azure Container Registry**, tagged `discovery-github-test=true`. Premium is recommended (8-hour task timeout, dedicated agent pools for 10–20 GB GPU images). Grant the Discovery workspace's managed identity **AcrPull** on it.
3. **Discovery workspace, project, supercomputer and nodepools**. Add CPU SKUs (e.g. `Standard_D4s_v6`), and GPU SKUs (`Standard_NC24ads_A100_v4`, `Standard_NC40ads_H100_v5`) if you want GPU tools exercised.
4. **Storage account for evidence**, tagged `discovery-github-test=true`. Keep it private, and add a lifecycle rule that deletes blobs under `discovery-github-test/` after your retention period.
5. **Identity for CI**: an Entra app or user-assigned identity with federated credentials for the subjects `repo:microsoft/discovery:environment:discovery-health-trusted` and `repo:microsoft/discovery:environment:discovery-health-pr`. Roles:
   - **AcrPush** and permission to run ACR tasks on the registry
   - **Contributor** on the test resource group
   - Discovery data-plane access on the test project
   - **Storage Blob Data Contributor** on the evidence container
   - **Reader** on the nodepools

## GitHub setup

1. **Environments**
   - `discovery-health-trusted`: deployment branches limited to `main`, no required reviewers, so the weekly schedule runs unattended.
   - `discovery-health-pr`: **required reviewers**. Used only when a maintainer dispatches a PR test.
2. **Environment variables** (both environments):
   - `DH_AZURE_CLIENT_ID`, `DH_TENANT_ID`, `DH_SUBSCRIPTION_ID`
   - `DH_RESOURCE_GROUP`, `DH_LOCATION`
   - `DH_ACR_NAME`, `DH_ACR_RESOURCE_GROUP`, `DH_ACR_AGENT_POOL`
   - `DH_WORKSPACE_ENDPOINT`, `DH_PROJECT`, `DH_CHAT_MODEL`
   - `DH_NODE_POOLS` (JSON), `DH_EVIDENCE_STORAGE` (JSON), `DH_OUTPUT_STORAGE_CONTAINER_ID`
   - `DH_CONFIG_JSON` (optional overrides such as budgets)
3. **Optional secret** in `discovery-health-trusted` only: `DH_TEMPLATE_VARIABLES` (JSON) for agents that need connection names or endpoints.
4. **Pages**: set the source to **GitHub Actions**, and set the repository variable `DH_PAGES_URL` to the site URL (for example `https://microsoft.github.io/discovery`). Run the workflow once with `bootstrap: true`. After that, every publish reads `state.json` back from the site, so history is preserved.

## Workflows

[`discovery-health.yml`](../workflows/discovery-health.yml) runs on a weekly schedule (Saturday 04:00 UTC, full catalog) and on `workflow_dispatch` with these inputs:
- `agents`, `stages`
- `pr_number` / `pr_head_sha`
- `rebuild`, `shards`, `dry_run`, `publish`, `bootstrap`

The jobs:

1. **plan**: no Azure access. For PR tests it verifies through the API that the PR is open, targets `main`, and has the expected head SHA. It selects the changed agents and checks out the PR as data only.
2. **test** (matrix of shards): OIDC login, then `run`. PR runs use the reviewer-gated environment and the trusted harness and specs from `main`, and never receive secrets. Uploads results, without the private evidence.
3. **report**: merges shards, imports blob checkpoints, reaps orphaned operations, writes the job summary and JUnit, and builds the site.
4. **publish**: deploys to GitHub Pages, only for `main` runs that aren't PR tests.
5. **pr-feedback**: updates one sticky comment on the PR with the summary.

[`discovery-health-cleanup.yml`](../workflows/discovery-health-cleanup.yml) runs weekly, and on dispatch defaults to `dry_run: true`.

Both workflows share the `discovery-health-live` concurrency group, so runs never overwrite each other's deployments.

## Deterministic specs

Specs are optional. Without one, the harness uses fixed templates:

**Image smoke**
- An interpreter check per code environment, such as `python3 -c "print('DH_OK')"`.
- `command -v` and `test -e` checks for each action's executable and script.

**Tool run (code environments)**
- Runs the tool's own command template with an inline script.
- The script computes 6×7, writes a file, and prints the deployer's `DISCOVERY_VALIDATION_RESULT` receipt.

**Round trip**
- Code-environment tools use a fixed prompt that asks the agent to compute 6×7 through the tool and print the receipt.
- Tool-less agents get a short capability prompt.

**Action tools** need a spec to be fully tested. Until one exists, their tool run and round trip are `untested: needs spec` and the agent can be at most `partial`.

Specs live in [`specs/<agent>.yaml`](specs) and are maintainer-owned. PR runs always use the specs from `main`. Schema: [`schemas/spec.schema.json`](schemas/spec.schema.json).

```yaml
agent: alphafold-db
requires:
  skus: auto                 # or an explicit SKU list
  variables: []              # trusted template variables the agent needs
skip:                        # expiring skips; shown on the scorecard
  - stage: round-trip
    reason: model quota exhausted in the test project
    until: '2027-01-31'
toolIdPlaceholders:          # only when automatic binding is ambiguous
  '{{alphafolddbToolId}}': alphafold-db
tools:
  alphafold-db:
    buildContext: tool       # 'agent' when the Dockerfile copies tools/<tool>/... (auto-detected)
    imageSmoke:
      - name: entrypoint-help
        command: python3 /app/entrypoint.py --help
        expect: { exitCode: 0, contains: ['usage'] }
    toolRun:
      - name: fetch-p00520
        action: fetch_structure          # renders the action's own command template
        inputs: { accession: P00520 }
        verify: "test -s {{output_directory}}/P00520.pdb && grep -m1 '^ATOM' {{output_directory}}/P00520.pdb"
        expect: { status: Succeeded, contains: ['ATOM'] }
        timeoutMinutes: 15
roundTrip:
  prompt: 'Use the alphafold-db tool to fetch UniProt P00520 and name the PDB file it produced.'
  expect:
    toolsCalled: [alphafold-db]          # defaults to every bound tool
    matches: ['P00520']
    receipt: false                       # true appends the deployer's receipt contract
```

**Tool-run case fields**

| Field | Purpose |
| --- | --- |
| `action` + `inputs` | Renders the action's own command template (Handlebars `{{var}}` and `{{#if}}…{{else}}…{{/if}}`). |
| `script` | Runs the tool's code-environment command with your script mounted at `/dh/input/`. |
| `command` | A literal shell command. |
| `inlineFiles` | Mounted under `/dh/input/`. |

Paths `{{input_directory}}` and `{{output_directory}}` resolve to `/dh/input` and the run's output directory.

```powershell
pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 scaffold-spec -Agents alphafold-db   # skeleton from tool.yaml input schemas
pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 validate-specs
```

## Tagging, privacy and cleanup

| Resource | Marker | Removed by |
| --- | --- | --- |
| ACR images | `discovery-github-test/` repository namespace, OCI labels `discovery-github-test=true`, `dgt.fingerprint`, `dgt.git-sha`, `dgt.run-id`; unique, never-reused tags | `acr purge` on the namespace (`--ago`, `--keep`) |
| Discovery tools | Azure tags `discovery-github-test=true`, `dgt-run-id`, `dgt-git-sha`, `dgt-agent`, `dgt-def-hash` | Cleanup: clear `linkedAgentIds`, then delete |
| Data-plane agents | `dgt-` name prefix and `[discovery-github-test <runId>]` in the description | Cleanup deletes only agents carrying both markers that are no longer in the catalog (or all with `-All`) |
| Investigations | `dgt-` prefix and `discovery-github-test` display name | Deleted on pass. Failures are kept for `retainFailedDays`; cleanup skips any whose age can't be determined. |
| Tool runs | Run on tagged test tools | Cleanup cancels only stale runs whose `toolId` is a tagged test tool |
| Evidence and checkpoints | `discovery-github-test/runs/<runId>/` in private storage | Storage lifecycle rule |

The repository is public, so Actions logs and artifacts are world-readable:

- **Public output** (console, summary, annotations, artifacts, Pages) is built only from templated messages in [`templates/messages.psd1`](templates/messages.psd1), with sanitized parameters. Configuration values are masked.
- **Public artifacts** contain only result records (no resource URLs or registry names). The remote-operation registry goes to private checkpoints only, which the report job reads with `-FromCheckpoints`.
- **Raw output** (logs, payloads, responses) is written only to private evidence storage. Download it with `evidence -RunId <id>`.

## Cost controls

- **Builds:** unchanged tools reuse images (content fingerprint), and build plus smoke run as one ACR task.
- **Tool registration** is skipped when the definition hash is unchanged.
- **GPU runs** happen only when `nodePools` has a matching GPU SKU. `concurrency.gpuToolRun` and `budgets.maxGpuToolRuns` cap them.
- **Round trips** are skipped when the tool run failed, capped by `budgets.maxRoundTrips`, and can be disabled entirely with `roundTrip.enabled: false`.
- **Time:** the run deadline cancels in-flight work, and cleanup deletes stale resources weekly.

## Pilot checklist

Validate these in the test environment before enabling the schedule:

| # | Check |
| --- | --- |
| P1 | `az acr run --no-wait` returns a run id; multi-step YAML with `--label`; the run log shows `runtime-dependency` digests |
| P2 | Large GPU images build within the default ACR agent's disk and time limits (otherwise set `acrAgentPool`, `acrTimeoutSeconds`) |
| P3 | Whether `pool_type: static` holds compute after registration or a run (otherwise set `cleanup.afterRun: all`) |
| P4 | GA `:run` accepts the payload (`toolId`, `command`, `inlineFiles`, `nodePoolIds`, optional `outputData`), returns logs, and honors `:cancel` |
| P5 | Data-plane agents and investigations keep the `dgt-` name and description markers (and whether native tags are supported) |
| P6 | The workspace managed identity can pull from the test ACR |
| P7 | OIDC re-login keeps a multi-hour shard authenticated |
| P8 | Agents with top-level `tools:` (`kind: mcp` / `web_search`) behave as reported (`DH-AGT-004`) |
| P9 | Responses POST returns promptly, and rate limits hold at the configured `concurrency.roundTrip` |
| P10 | Weekly cost of a full run is acceptable; tune `budgets` and `concurrency` |

## Development

```powershell
pwsh -File .github/discovery-health/tests/Unit.Tests.ps1        # pure functions
pwsh -File .github/discovery-health/tests/Scheduler.Tests.ps1   # end-to-end against an offline fake Azure/Discovery backend
python -m pytest .github/tests/test_discovery_health.py -q      # suites + workflow contracts + parity with the agent deployer
```

[`test_discovery_health.py`](../tests/test_discovery_health.py) runs the deployer skill's embedded Python (`patch_agent_yaml`, `build_payload`, `verify_receipt`) as the reference implementation. Any contract drift between the deployer and this harness fails CI.
