# AI Infrastructure MCP

This is an MCP server for the AI Infrastructure on Azure project. The initial release focuses on cluster administration and monitoring tools for Slurm clusters.

## Table of Contents

1. [Installation](#1-installation)
2. [Project Layout](#2-project-layout)
3. [Running the Server](#3-running-the-server)
4. [Development Notes](#4-development-notes)
5. [SSH Configuration](#5-ssh-configuration)
6. [Tools](#6-tools)

   6.1 [InfiniBand Tools](#61-infiniband-tools)

   6.2 [Azure VM Tools](#62-azure-vm-tools)

   6.3 [Slurm Tools](#63-slurm-tools)

   6.4 [Systemd Tools](#64-systemd-tools)

   6.5 [File Access Tools](#65-file-access-tools)

7. [Local LLM (Ollama) Setup](#7-local-llm-ollama-setup)

## 1. Installation

It's recommended to use a virtual environment.

Create and activate a venv (Linux/macOS):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

Install base shared dependency (fastmcp) for development:

```bash
pip install -r requirements.txt
```

## 2. Project Layout

This repository exposes a single MCP server.

```
ai_infrastructure_mcp/       # Unified MCP server package with tools & ssh config
```

## 3. Running the Server

From repo root (after venv + install):

```bash
python -m ai_infrastructure_mcp.server
```

Or via a Model Context Protocol client configuration (see example below).

## 4. Development Notes

- Add new tools under `ai_infrastructure_mcp/tools/` and register them in `server.py` if they need custom wrapping.
- Tests live in `ai_infrastructure_mcp/tests/` and are discovered by `pytest`.

## 5. SSH Configuration

The server reads SSH connection details exclusively from environment variables. No YAML config file is used.

Required env vars:

```
CLUSTER_HOST        # login node hostname
CLUSTER_USER        # SSH username
```

Optional env vars:

```
CLUSTER_PRIVATE_KEY # path to private key (if omitted, SSH agent / default keys are tried)
CLUSTER_PORT        # SSH port (default 22)
```

Example `.vscode/mcp.json` snippet:

```jsonc
{
  "servers": {
    "ai-infrastructure-mcp": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "ai_infrastructure_mcp.server"],
      "env": {
        "CLUSTER_HOST": "login.cluster.local",
        "CLUSTER_USER": "alice",
        "CLUSTER_PRIVATE_KEY": "/home/alice/.ssh/id_rsa",
        "CLUSTER_PORT": 50022,
      },
    },
  },
}
```

Security notes:

- Use a non-root user.

## 6. Tools

### 6.1 InfiniBand Tools

#### get_infiniband_pkeys

Returns InfiniBand partition keys in a structured JSON object (via parallel-ssh across provided hosts).

Example response:

```json
{
  "version": 1,
  "timestamp": "2025-09-09T12:00:00Z",
  "hosts": [
    { "host": "node01", "pkeys": ["0x7fff", "0x8001"], "error": null },
    { "host": "node02", "pkeys": [], "error": null }
  ],
  "summary": { "queried": 2, "ok": 2, "failed": 0 }
}
```

Notes:

- pkeys list is de-duplicated, lowercase, sorted.
- error field is null on success; a string message on failure.
- summary counts classify a host with any error as failed.

### 6.2 Azure VM Tools

#### get_physical_hostnames

Retrieve the underlying Azure physical hostnames for VMs.

Reads the Hyper-V KVP pool file (`/var/lib/hyperv/.kvp_pool_3`) on each specified host via `parallel-ssh` and extracts
the embedded physical host identifier.

**Robust Implementation:**

- Checks if the Hyper-V file exists before attempting to read it
- Gracefully handles non-Azure VMs by returning empty strings
- Provides error reporting for permission issues and other failures

The command used is equivalent to:

```bash
test -f /var/lib/hyperv/.kvp_pool_3 && tr -d '\0' < /var/lib/hyperv/.kvp_pool_3 | \
  grep -o "Qualified[^V]*VirtualMachineDynamic" | \
  sed "s/Qualified//;s/VirtualMachineDynamic//" | head -1 || echo ""
```

Signature:

```
get_physical_hostnames(hosts: List[str])
```

Example usage:

```
get_physical_hostnames(['vmA','vmB','vmC'])
```

Response includes error handling:

```json
{
  "version": 1,
  "timestamp": "2024-01-01T12:00:00Z",
  "hosts": [
    { "host": "vmA", "physical_hostname": "PHYS_HOST_A" },
    {
      "host": "vmB",
      "physical_hostname": "",
      "error": "tr: /var/lib/hyperv/.kvp_pool_3: Permission denied"
    },
    { "host": "vmC", "physical_hostname": "PHYS_HOST_C" }
  ],
  "summary": { "queried": 3 }
}
```

Notes:

- `physical_hostname` may be empty if pattern not found.
- Follows the same structural pattern as `get_infiniband_pkeys` for consistency.

#### get_vmss_id

Retrieve the Azure VMSS (Virtual Machine Scale Set) ID for a list of VM hosts.

Queries the Azure Instance Metadata Service on each specified host via `parallel-ssh` to extract the `compute.name` field,
which contains the VMSS instance name. This ID is essential for correlating hostnames with Azure Monitor metrics data.

**Implementation Details:**

- Uses Azure Instance Metadata Service endpoint with API version 2025-04-07
- Handles cases where metadata service is not accessible (non-Azure VMs)
- Provides error reporting for curl failures and jq parsing issues
- Returns empty string when metadata field is null or unavailable

The command used is equivalent to:

```bash
curl -H "Metadata: true" "http://169.254.169.254/metadata/instance?api-version=2025-04-07&format=json" 2>/dev/null | \
  jq -r .compute.name 2>/dev/null || echo ""
```

Signature:

```
get_vmss_id(hosts: List[str])
```

Example usage:

```
get_vmss_id(['compute-node-01', 'compute-node-02', 'login-node'])
```

Example response:

```json
{
  "version": 1,
  "timestamp": "2025-01-17T12:00:00Z",
  "hosts": [
    { "host": "compute-node-01", "vmss_id": "compute-sinvqvly6zhmb_5" },
    { "host": "compute-node-02", "vmss_id": "compute-sinvqvly6zhmb_12" },
    { "host": "login-node", "vmss_id": "login-sinvqvly6zhmb_0" }
  ],
  "summary": { "queried": 3 }
}
```

Notes:

- `vmss_id` may be empty if metadata service is not accessible or returns null
- Essential for matching hostnames to Azure Monitor metrics and resource data
- Follows the same structural pattern as other Azure VM tools for consistency

### 6.3 Slurm Tools

#### sacct

Run Slurm job accounting with raw argument control.

New simplified signature:

```
sacct(args: Optional[List[str]] = None)
```

Provide a list exactly as you would type after `sacct` on the command line. Each element is one argument; quoting is applied safely.

Examples:

```
sacct()                         # default view for current user
sacct(['--user','alice'])       # jobs for user alice
sacct(['--state=FAILED'])       # failed jobs
sacct(['--format','jobid,state,elapsed'])
sacct(['--user','bob','--starttime','2024-01-01','--endtime','2024-01-02'])

# Convenience behavior:
# If you specify a state selector (-s/--state or --state=STATE) without an
# explicit end time (-E/--endtime/--endtime=TIME), the wrapper automatically
# appends `--endtime=now`. Rationale: on many clusters a state filter with no
# end time yields an empty result set (surprising to users). Adding an explicit
# end time returns the expected active/completed jobs in that window. Provide
# --endtime (or -E) yourself to override this default.
```

Response schema (all Slurm tools share this):

```json
{
  "version": 1,
  "success": true,
  "command": "sacct --user alice",
  "raw_output": "...",
  "error": null
}
```

#### squeue

Queue inspection.

```
squeue(args: Optional[List[str]] = None)
```

Examples:

```
squeue()
squeue(['--user','alice'])
squeue(['--states','RUNNING'])
squeue(['--partition','gpu','--format','%i %t %j'])
```

#### sinfo

Cluster node / partition info.

```
sinfo(args: Optional[List[str]] = None)
```

Examples:

```
sinfo()
sinfo(['--partition','gpu'])
sinfo(['--format','%P %a %l %D %C'])
```

#### scontrol

Cluster control & detailed queries.

```
scontrol(args: Optional[List[str]] = None)
```

Examples:

```
scontrol(['ping'])
scontrol(['show','job','123'])
scontrol(['show','node','node001'])
scontrol(['update','JobId=123','Priority=1000'])
```

#### sreport

Accounting reports.

```
sreport(args: Optional[List[str]] = None)
```

Examples:

```
sreport(['cluster','Utilization'])
sreport(['user','TopUsage','Start=now-7days'])
sreport(['job','SizesByAccount'])
sreport(['cluster','Utilization','Start=2024-01-01','End=2024-01-31','Accounts=myacct'])
```

Report Types and Commands:

- **cluster**: AccountUtilizationByUser, UserUtilizationByAccount, UserUtilizationByWckey, Utilization, WCKeyUtilizationByUser
- **job**: SizesByAccount, SizesByAccountAndWckey, SizesByWckey
- **reservation**: Utilization
- **user**: TopUsage

Common Report Options (add to command string):

- All_Clusters: Use all monitored clusters
- Clusters=<list>: List of clusters to include
- End=<time>: Period ending for report
- Format=<fields>: Comma separated list of fields to display
- Start=<time>: Period start for report
- Accounts=<list>: List of accounts to include
- Users=<list>: List of users to include
- Wckeys=<list>: List of wckeys to include
- Tree: Show account hierarchy (for AccountUtilizationByUser)

### 6.4 Systemd Tools

#### systemctl

```
systemctl(hosts: List[str], args: Optional[List[str]] = None)
```

Examples:

```
systemctl(['status','ssh'], hosts=['node1'])
systemctl(['is-active','nginx'], hosts=['node1','node2'])
systemctl(['list-units','--failed'], hosts=['nodeA'])
```

Multi-host response shape:

```json
{
  "version": 1,
  "success": true,
  "command": "parallel-ssh -i -H \"node1 node2\" \"systemctl is-active sshd\"",
  "hosts": [
    { "host": "node1", "lines": ["active"] },
    { "host": "node2", "lines": ["inactive"] }
  ],
  "raw_output": "[1] ...",
  "error": null,
  "summary": { "queried": 2 }
}
```

#### journalctl

```
journalctl(hosts: List[str], args: Optional[List[str]] = None)
```

Examples:

```
journalctl(['-u','ssh','-n','20'], hosts=['node1'])
journalctl(['-u','sshd','-n','5'], hosts=['node1','node2'])
journalctl(['--priority=err','-n','50'], hosts=['nodeA','nodeB','nodeC'])
```

Response schema matches the `systemctl` multi-host example above.

Notes:

- Only simple command argument lists are allowed; no shell pipelines are constructed for systemd tools.
- Hostnames failing validation raise `ValueError`.

### 6.5 File Access Tools

#### head_file

Read lines from the beginning of a file with offset and length support for chunked reading.

Parameters:

- `path` (string): Path to the file on the cluster
- `offset` (int, default: 0): Number of lines to skip from the beginning
- `length` (int, default: 10): Number of lines to read

Example response:

```json
{
  "version": 1,
  "success": true,
  "path": "/path/to/file.log",
  "offset": 0,
  "length": 10,
  "lines": ["line 1", "line 2", "..."],
  "line_count": 10,
  "error": null
}
```

#### tail_file

Read lines from the end of a file with offset and length support for chunked reading.

Parameters:

- `path` (string): Path to the file on the cluster
- `offset` (int, default: 0): Number of lines to skip from the end
- `length` (int, default: 10): Number of lines to read

Example response:

```json
{
  "version": 1,
  "success": true,
  "path": "/path/to/file.log",
  "offset": 0,
  "length": 10,
  "lines": ["line 991", "line 992", "..."],
  "line_count": 10,
  "error": null
}
```

#### count_file

Count lines or bytes in a file.

Parameters:

- `path` (string): Path to the file on the cluster
- `mode` (string, default: "lines"): "lines" to count lines, "bytes" to count bytes

Example response:

```json
{
  "version": 1,
  "success": true,
  "path": "/path/to/file.log",
  "mode": "lines",
  "count": 1000,
  "error": null
}
```

#### search_file

Search for a pattern in a file with context lines (like grep with before/after).

Parameters:

- `path` (string): Path to the file on the cluster
- `pattern` (string): Regular expression pattern to search for
- `before` (int, default: 0): Number of lines to include before each match
- `after` (int, default: 0): Number of lines to include after each match
- `max_matches` (int, default: 100): Maximum number of matches to return

Example response:

```json
{
  "version": 1,
  "success": true,
  "path": "/path/to/file.log",
  "pattern": "ERROR",
  "before": 1,
  "after": 1,
  "max_matches": 100,
  "matches": [
    {
      "line_number": 42,
      "line": "ERROR: Something went wrong",
      "context_before": [
        { "line_number": 41, "line": "Processing request..." }
      ],
      "context_after": [{ "line_number": 43, "line": "Stack trace:" }]
    }
  ],
  "match_count": 1,
  "error": null
}
```

**File Access Security Notes:**

- All file paths are properly escaped to prevent command injection
- File access is limited to what the SSH user can access on the cluster
- Large files can be read in chunks using offset/length parameters to avoid filling context windows
- Search operations are limited by max_matches to prevent excessive output

## 7. Local LLM (Ollama) Setup

Run a local Ollama instance (e.g. on an Azure NDv5 / GPU node) and point VS Code Copilot to it for fully local model inference.

### Use Local NVMe for Docker Data

Move Docker's data-root onto fast local NVMe to avoid filling OS disk and to speed up model layer extraction.

1. Stop Docker:

```bash
sudo systemctl stop docker
```

2. Edit `/etc/docker/daemon.json` (create if missing) and add or merge:

```jsonc
{
  "data-root": "/mnt/nvme/docker-data",
}
```

3. Ensure the directory exists and proper ownership:

```bash
sudo mkdir -p /mnt/nvme/docker-data
sudo chown root:root /mnt/nvme/docker-data
```

4. Start Docker:

```bash
sudo systemctl start docker
```

### Run Ollama Container

Pull and run the latest Ollama container with GPU access:

```bash
IMAGE="ollama/ollama:latest"
CONTAINER_NAME="ollama_llm"
PORT=11434
sudo docker run --gpus=all --shm-size=1g \
  -v $HOME/ollama_data:/root/.ollama \
  -p ${PORT}:11434 \
  --name $CONTAINER_NAME $IMAGE
```

If you need to restart later:

```bash
sudo docker start ollama_llm
```

### Pre-Pull Models

Download the required models before first use in VS Code (examples shown):

```bash
sudo docker exec -it ollama_llm ollama pull llama2:70b
sudo docker exec -it ollama_llm ollama pull gpt-oss:120b
```

Adjust model names/sizes to what your GPU memory can support.

### Using with VS Code Copilot (Ollama Provider)

1. Open the Copilot chat panel.
2. Click the model dropdown and choose "Manage models...".
3. Select the Ollama provider and pick a local model (e.g. `gpt-oss` or `llama2`).
4. The agent will now route requests to your local Ollama endpoint on `http://localhost:11434`.

Notes:

- Ensure the VS Code environment can reach the GPU host (if remote, use SSH remote dev so localhost maps through the tunnel).
- Large model pulls can take significant time; monitor progress with `docker logs -f ollama_llm`.
- To remove the container & data: `docker rm -f ollama_llm && rm -rf $HOME/ollama_data` (irreversible).
