# Discovery Supercomputer CLI

The Discovery CLI provides access to the **Discovery Supercomputer API** for submitting jobs, managing storage, and building container images.

>  **Note:**  
> This is *not* an official Discovery client and is provided *as-is* without support.  
> An SDK is **not available** during the private preview phase.

---

## Prerequisites

Before you begin, make sure the following requirements are met:

1. **Discovery Environment Setup**
   - You have a Discovery instance configured with:
     - Workspace  
     - Project  
     - Supercomputer  
     - Storage  
     - Nodepools  
   - [Follow setup instructions here](https://github.com/microsoft/discovery/blob/main/2-getting-started/quickstart.md)

2. **Required Tools**
   - Operating System: **Linux**, **macOS**, or **Windows Subsystem for Linux (WSL)**
   - **Python 3.9+** – [Download](https://www.python.org/downloads/)
   - **Azure CLI** – [Download](https://learn.microsoft.com/en-us/cli/azure/?view=azure-cli-latest)
   - **azcopy** – [Download](https://learn.microsoft.com/en-us/azure/storage/common/storage-use-azcopy-v10) (required for blob storage commands)
   - Azure subscription with **Contributor** permissions

---

## Getting Started

### 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install the Discovery CLI

Install the `discovery` command globally using uv:

```bash
uv tool install discovery --from git+https://github.com/microsoft/discovery.git#subdirectory=utilities/supercomputer-cli/discovery
```

This installs the CLI in an isolated environment and makes it available system-wide.

### 3. Upgrade the Discovery CLI

The CLI checks for new releases once per day in the background and prints a
one-line reminder when a newer version of the `utilities/supercomputer-cli/`
subdirectory has landed on `main`. Apply an update in one of two ways:

```bash
discovery update            # interactive: check + prompt + install via uv
discovery update --check    # check only
discovery update -y         # install without confirmation
```

You can also upgrade directly:

```bash
uv tool upgrade discovery
```

The automatic background check can be disabled either per-invocation
(`DISCOVERY_NO_UPDATE_CHECK=1`) or persistently:

```bash
discovery update --disable   # turn off background checks
discovery update --enable    # turn them back on
```

> **Authentication is optional.** The update check works fully
> unauthenticated against a public repo, but GitHub limits anonymous
> traffic to 60 requests/hour per IP. To raise the limit to 5000/hour
> the checker opportunistically uses `DISCOVERY_GITHUB_TOKEN`,
> `GITHUB_TOKEN`, `GH_TOKEN`, or `gh auth token` (when the `gh` CLI is
> installed and authenticated) — no setup required for most developers.

> **Following a non-default branch.** Set `DISCOVERY_UPDATE_REF=<ref>` to
> compare against a branch, tag, or commit other than `main`. Pair with
> `DISCOVERY_UPDATE_REPO=owner/name` for fork-based or RC-channel
> testing.

### 4. Verify your installation

```bash
discovery --version   # Show version and build commit
discovery doctor      # Check installation health, dependencies, and auth status
```

### 5. Configure Discovery Resources

```bash
discovery configure
```

This walks you through the project, ACR registry, tool, nodepool, and two
storage concepts:

- **Archive** (mandatory) — blob-backed container for tool-run input/output
  data persistence. Single global value per workspace. The Azure resource
  type differs by API version (`Microsoft.Discovery/datacontainers` on V1,
  `storagecontainers` on V2) but the picker dispatches automatically and
  only surfaces blob-kind candidates.
- **Scratch** (optional, per supercomputer) — ANF-backed wrapper providing
  ephemeral working storage at `/scratch` when you submit a job with
  `discovery job start --scratch`. Same dispatch story (datacontainer of
  `kind=DiscoveryStorage` on V1, storagecontainer of `kind=AzureNetAppFiles`
  on V2). Skip this step if your jobs don't need scratch ANF.

Set or change the API version (persisted to your config) with
`--api-version`:

```bash
discovery configure --api-version 2026-02-01-preview
```

If you don't pass `--api-version`, the full `configure` flow prompts you to
pick interactively. Launch only that picker with `discovery configure
--api-version-select`.

You can also run individual steps:

```bash
discovery configure --acr                # only ACR registry
discovery configure --tool               # only tool
discovery configure --archive-select     # only Archive (blob) container
discovery configure --nodepool           # only nodepool
discovery configure --scratch-select     # only Scratch (ANF) wrappers per SC
discovery configure --api-version-select # only API version picker
```

Both Archive and Scratch pickers offer a `+ Create new...` option at the top
that lets you author the wrapper inline (no portal/Bicep round-trip):

- **Archive Create** lists `Microsoft.Storage/storageAccounts` in the
  workspace's subscription and region, prompts for a name, and deploys the
  blob-kind dataContainer (V1) or storageContainer (V2). On V1 it uses the
  workspace's `workspaceIdentity` UAMI for the required credentials block.
- **Scratch Create** lists candidate ANF resources visible on the
  supercomputer's VNet — V1: `Microsoft.Discovery/storages`, V2:
  `Microsoft.NetApp/.../volumes` — then deploys the ANF-kind wrapper.

### Scratch (ANF) wrapper — per supercomputer

`discovery configure --scratch-select` prompts once per supercomputer in
the workspace. The picker hard-filters to wrappers whose underlying ANF
lives on the **same VNet** as the supercomputer (ANF is mounted over a
private endpoint on that VNet, so cross-VNet selection is never offered —
even within the same region). The picker also offers:

- `+ Create new Scratch ...` — deploy a wrapper inline against an existing
  ANF on the SC's VNet.
- `Skip <sc>` — leave this SC unmapped. `--scratch` job submissions on
  that SC will fail fast with a hint to re-run `--scratch-select`.

After selection, `configure` automatically creates a `scratch` asset under
each chosen wrapper (dataAsset on V1, storageAsset on V2) so the
`/scratch` URI built at submit time resolves immediately.

The picker derives the supercomputer's VNet from `properties.subnetId` on
the supercomputer ARM resource. The underlying ANF resource itself
(`Microsoft.Discovery/storages` for V1, `Microsoft.NetApp/.../volumes` for
V2) must already exist on that VNet — the CLI doesn't provision the ANF
itself.

### Mounting `/scratch` on a job

Pass `--scratch` to `start`, `batch`, or `vscode` to mount the
per-supercomputer Scratch ANF at `/scratch` for that job:

```bash
discovery job start --scratch "python train.py --workdir /scratch/run"
discovery job vscode --scratch
discovery job batch 4 --scratch "python /scratch/jobs/{job_index}.sh"
```

The CLI dispatches to the correct URI scheme automatically — V1
`discovery://dataassets/...`, V2 `discovery://storageassets/...` — using a
fresh UUID-suffixed subpath per run so concurrent jobs don't collide. If
`--scratch` is requested but no Scratch wrapper is configured for the
chosen nodepool's supercomputer, the CLI fails fast (exit 2) with a hint to
run `discovery configure --scratch-select`.

When `--scratch` is omitted, no `/scratch` mount is added — your job runs
without one. The Scratch flow is opt-in per submission.

---

## CLI Command Reference

> **Tip:** Run `discovery --help` or `discovery <command> --help` for the most up-to-date usage information. The built-in help is always more accurate than this README.

The CLI is organized into command groups:

### Global Options

```bash
discovery --version  # Show version and git commit
discovery --verbose  # Enable debug logging for any command
discovery -v         # Short form for --verbose
```

### Top-level Commands

| Command | Description |
|---------|-------------|
| `discovery configure` | Interactively select Discovery resources and persist configuration |
| `discovery doctor` | Check installation health — modules, templates, tools, and auth status |

### Job Commands (`discovery job`)

Manage and monitor Discovery jobs:

| Command | Description |
|---------|-------------|
| `discovery job start <command>` | Start a tool run and poll until completion |
| `discovery job batch <command>` | Submit multiple independent tool runs (no polling) |
| `discovery job vscode [--tunnel-name <name>]` | Start a job that hosts a VS Code tunnel (default name: `discovery-<username>`) |
| `discovery job cancel <operation-id>` | Cancel a running operation |
| `discovery job cancel --since 10m` | Bulk-cancel every locally-recorded job submitted in the last 10 minutes |
| `discovery job running` | List your running operations (this machine); `--all` to see everyone's |
| `discovery job pending` | List your queued operations (this machine); `--all` to see everyone's |
| `discovery job done` | List your completed operations (this machine); `--all` to see everyone's |
| `discovery job list` | List your recent operations (this machine); `--all` or `--user X` to widen |
| `discovery job status [operation-id]` | Get compute usage, or status of a specific operation |
| `discovery job pools` | List available nodepools from configuration |
| `discovery job cleanup-anf` | List stale operations whose ANF scratch folders can be cleaned up |
| `discovery job history` | List, locate, or wipe the local job-submit history |

> **Local job history.** Every `discovery job start` / `batch` / `vscode`
> records the operation ID + command + tool + nodepool + project + workspace
> to `~/.discovery/job-history.jsonl` (one JSON-Lines record per submit).
> `discovery job list / running / pending / done` filter to this machine's
> history by default — pass `--all` (or `--user X` on `list`) to widen the
> view to other people / other machines. Use `discovery job history` to
> browse the local store directly without hitting the service. Set
> `DISCOVERY_NO_JOB_HISTORY=1` to disable recording for an invocation.

**Examples:**

```bash
# Start a simple job
discovery job start "python train.py"

# Start with VS Code tunnel for debugging (defaults tunnel name to discovery-<username>)
discovery job vscode
# ...or override the tunnel name
discovery job vscode --tunnel-name my-box

# Start with resource requirements
discovery job start --cpus 4 --gpus 2 --memory 32Gi "python train.py"

# Start with the per-SC Scratch ANF mounted at /scratch
discovery job start --scratch "python train.py --workdir /scratch/run"

# Pick a specific nodepool for this run; --pool can target any pool in
# the workspace (including pools on a different supercomputer than the
# default). The Scratch lookup auto-routes to whichever SC the chosen
# pool lives on.
discovery job start --pool ibtest2/hbv4 --scratch "echo hi"

# Browse jobs you've submitted from this machine (offline, no API call)
discovery job history
discovery job history --limit 10
discovery job history --since 7d
discovery job history --all-workspaces --this-host

# Add live status + computed runtime (one parallel API call per entry)
discovery job history --status
discovery job history --status --since 24h

# Server-side listings default to jobs from this machine — pass --all
# to widen the view (or --user X on `list` for a specific submitter)
discovery job list                  # mine
discovery job list --all            # everyone's
discovery job list --user alice     # alice's (implies --all)
discovery job running                # mine, running now
discovery job running --all          # everyone's running

# Bulk-cancel everything you submitted from this machine in the last 10
# minutes (current workspace only; --yes skips the interactive confirm).
discovery job cancel --since 10m
discovery job cancel --since 1h --yes

# Submit several independent runs in one shot
discovery job batch 4 "python -c 'print(\"hello\")'"

# List operations
discovery job list --user you@example.com   # filter by submitter (email/UPN)
discovery job running                       # currently running ops

# Inspect a single op
discovery job status <operation-id>

# Cancel
discovery job cancel <operation-id>
```

### Blob Storage Commands (`discovery blob`)

Upload, download, and manage files in Discovery storage:

| Command | Alias | Description |
|---------|-------|-------------|
| `discovery blob upload <src> <dest>` | `up` | Upload files to storage |
| `discovery blob download <src> <dest>` | `down` | Download files from storage |
| `discovery blob ls [path]` | | List storage contents |
| `discovery blob remove <path>` | `rm` | Remove files from storage |
| `discovery blob url` | | Print Azure portal URL for the storage account |
| `discovery blob create-user-storage` | | Create a data asset and blob container for a user |

Storage paths support prefixes:
- `user:path/to/file` — User's personal storage (default)
- `shared:path/to/file` — Shared team storage

**Examples:**

```bash
# Upload a file to user storage
discovery blob up ./model.pt user:models/model.pt

# Download from shared storage
discovery blob down shared:datasets/data.csv ./local/

# List contents of user storage
discovery blob ls user:

# List shared storage root
discovery blob ls shared:
```

### Build Commands (`discovery build`)

Build and manage container images via ACR Tasks:

| Command | Description |
|---------|-------------|
| `discovery build image <context>` | Build a Docker image via ACR Task |
| `discovery build rebuild` | Layer VS Code CLI onto an existing ACR image |

**Examples:**

```bash
# Build an image with VS Code tunnel support
discovery build image --vscode .

# Build with custom image name and tag
discovery build image --image my-tool --tag v2 .
```

### Smoke Test Commands (`discovery smoke`)

Load testing and API validation:

| Command | Description |
|---------|-------------|
| `discovery smoke load` | Run load tests against the supercomputer API |

---

## Development Setup

If you want to contribute or modify the code:

```bash
# Clone the repository
git clone https://github.com/microsoft/discovery.git
cd discovery/utils/supercomputer-cli/discovery

# Sync dependencies (creates .venv and installs package in editable mode)
uv sync

# Activate the environment
source .venv/bin/activate

# Run tests
uv run pytest

# Run linter
uv run ruff check src tests
```

---

## VS Code Tunnel Integration

VS Code tunnel support lets you debug Discovery jobs interactively from your local VS Code.

When you build with `--vscode`:

```bash
discovery build image --vscode .
```

The command automatically:

* Adds the **VS Code CLI** (`/usr/local/bin/code`) into your image.
* Includes a helper script that starts the VS Code tunnel in the background with automatic restart.

**Running a tunnel-enabled job:**

```bash
discovery job vscode                                           # GitHub device-flow (default), tunnel name: discovery-<username>
discovery job vscode --tunnel-name my-box                      # Override tunnel name
discovery job vscode --tunnel-name my-box --provider microsoft # Microsoft-account device-flow
```

This starts a VS Code tunnel in the job container, letting you connect to it from your local editor. The `vscode` command does not take a user command — it hosts a tunnel session. To run a tunnel **alongside** your own workload, build your image with `--vscode` (see above) and launch via `discovery job start`.

**Configuration via environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `VS_CODE_TUNNEL_LOG` | `/tmp/vscode-tunnel.log` | Log file location |
| `VS_CODE_TUNNEL_MAX_RETRIES` | `0` (unlimited) | Max restart attempts (0 = unlimited) |
| `VS_CODE_TUNNEL_RETRY_DELAY` | `5` | Seconds between restart attempts |

---

## Quick Reference

```bash
# Check version and installation health
discovery --version
discovery doctor

# Configure your Discovery environment
discovery configure

# Upload data and start a job
discovery blob up ./data.csv user:datasets/data.csv
discovery job start "python train.py --gpus 4"

# Monitor jobs
discovery job running
discovery job status <operation-id>

# Download results
discovery blob down user:results/ ./local/results/
```

---

## Support

This toolkit is provided for **experimental and educational** purposes only.
Support is **not available** during the private preview.

For reference, visit:

* [Discovery Documentation](https://github.com/microsoft/discovery)
* [Azure CLI Reference](https://learn.microsoft.com/en-us/cli/azure/)
