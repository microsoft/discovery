# Microsoft Discovery Extension

## Disclaimer

> **IMPORTANT NOTE:**
> The Microsoft Discovery Extension (the "Extension") and associated resources are provided as part of the Microsoft Discovery Preview. The Extension is provided "as is" to support your use of Microsoft Discovery, including your development and testing of agents for specific scenarios.  
> Features may change or be discontinued without notice.  
> You are responsible for carefully testing agent behavior in the context of your Microsoft Discovery use case(s).
> See [LICENSE](LICENSE) for detailed terms of use.

## Getting Started

### 1. Install

Install the extension from a `.vsix` file: open the Extensions view, click the `...` menu, and choose **Install from VSIX**.

### 2. Run the Setup Wizard

On first launch the Setup Wizard opens automatically. You can also run it anytime from the Command Palette (`Ctrl+Shift+P`) → **Discovery: Setup Wizard**.

The wizard connects to your Azure account and auto-discovers your Discovery workspace, compute, and storage resources — no need to copy GUIDs manually. It adapts based on the mode you choose:

| Mode | What it configures |
|---|---|
| **Cloud** | Full Azure-backed Discovery workspace with remote compute and storage |
| **Local** | Local-only environment using Docker — no Azure account required |

#### Information to have ready (Cloud)

Before starting the wizard, make sure you have access to the following:

- **Azure account** — you will be prompted to sign in
- **Tenant ID** — the Azure AD tenant that contains your Discovery resources
- **Subscription ID** — the Azure subscription hosting the Discovery workspace
- **Discovery workspace name** — the wizard lists workspaces it finds, or you can enter one manually
- **Project name** — the project within the workspace you want to work with
- **LLM deployment** _(optional)_ — if you plan to use Azure OpenAI (BYOK), have your endpoint URL and deployment name available

> **Tip:** The wizard auto-detects most resources (resource group, region, storage accounts, and containers) once you select a subscription and workspace. If auto-detection fails due to permissions, the wizard shows the `az role assignment` command you need so an admin can grant access.

### 3. Start chatting

Open the chat panel in the secondary sidebar (`Ctrl+Alt+B`) and start asking questions. The assistant has access to all the computational tools deployed in your Discovery workspace.

## Features

### Conversational Scientific Computing

Chat with an AI assistant that has access to all the computational tools deployed in your Discovery workspace. Describe your task in natural language and the assistant will select the right tools, write and submit scripts to the supercomputer, chain multi-step workflows, and retrieve results — all autonomously.

### LLM Engine Support

Choose between multiple LLM backends from the model picker:

- **GitHub Copilot SDK** — uses the Copilot CLI for model access (requires `npm install -g @github/copilot`)
- **VS Code Language Model API** — uses models provided by installed VS Code extensions (e.g., GitHub Copilot Chat)
- **Azure OpenAI (BYOK)** — bring your own Azure OpenAI deployment

To use Azure OpenAI, add an `azure_openai` block to your profile in `discovery_config.json`. You can open this file directly from the Command Palette (`Ctrl+Shift+P`) → **Discovery: Edit Discovery Config**, and edit it manually. Two authentication methods are supported:

#### Azure AD authentication (recommended)

```json
{
  "active_profile": "my-workspace",
  "profiles": {
    "my-workspace": {
      "mode": "cloud",
      "tenant_id": "YOUR-TENANT-ID",
      "subscription_id": "YOUR-SUBSCRIPTION-ID",
      "resource_group": "my-discovery-rg",
      "location": "eastus",
      "api_version": "2026-02-01-preview",
      "workspace": "my-discovery-workspace",
      "project": "MyProject",
      "azure_openai": {
        "endpoint_url": "https://my-openai-resource.openai.azure.com/",
        "deployment_name": "gpt-4o",
        "auth_type": "azure_ad",
        "api_version": "2024-12-01-preview",
        "azure_ad": {
          "subscription_id": "YOUR-SUBSCRIPTION-ID",
          "resource_group": "my-discovery-rg",
          "tenant_id": "YOUR-TENANT-ID",
          "scope": "https://cognitiveservices.azure.com/.default"
        }
      }
    }
  }
}
```

#### API key authentication

```json
{
  "active_profile": "my-workspace",
  "profiles": {
    "my-workspace": {
      "mode": "cloud",
      "tenant_id": "YOUR-TENANT-ID",
      "subscription_id": "YOUR-SUBSCRIPTION-ID",
      "resource_group": "my-discovery-rg",
      "location": "eastus",
      "api_version": "2026-02-01-preview",
      "workspace": "my-discovery-workspace",
      "project": "MyProject",
      "azure_openai": {
        "endpoint_url": "https://my-openai-resource.openai.azure.com/",
        "deployment_name": "gpt-4o",
        "auth_type": "api_key",
        "api_key": "YOUR-API-KEY",
        "api_version": "2024-12-01-preview"
      }
    }
  }
}
```

#### Azure OpenAI fields

| Field | Type | Required | Description |
|---|---|---|---|
| `endpoint_url` | `string` | **Yes** | Azure OpenAI resource URL |
| `deployment_name` | `string` | **Yes** | Model deployment name (e.g. `gpt-4o`) |
| `auth_type` | `"api_key"` or `"azure_ad"` | **Yes** | Authentication method |
| `api_version` | `string` | **Yes** | API version (e.g. `2024-12-01-preview`) |
| `api_key` | `string` | Only if `auth_type` = `"api_key"` | Azure OpenAI API key |
| `azure_ad.scope` | `string` | No | OAuth scope (defaults to `https://cognitiveservices.azure.com/.default`) |
| `azure_ad.tenant_id` | `string` | No | Azure AD tenant ID |

> **Tip:** The Setup Wizard can generate this configuration interactively — it always uses Azure AD authentication.

Sessions automatically recover when they expire after long idle periods, restoring conversation history seamlessly.

### Tool Activity Panel

See every tool call the assistant makes in real time — what it called, what it returned, and how long it took. Tool calls display human-readable labels (e.g., "Running autodock on deadpool2" instead of "job_submit_code"). Expand any call to inspect the full input/output, or click through to the detail panel for job analysis and live log streaming.

### Job Monitoring and Analysis

Long-running supercomputer jobs are automatically monitored with periodic AI-powered analysis that reports progress, estimated time remaining, cost tracking, and stall detection. The job detail panel shows Job Analysis and Job Output at the top for fast access, with live log streaming via virtual scroll.

### Control Autonomy and Costs

Two toolbar controls in the chat input box let you tune how the assistant works.

**Workflow Mode** — controls how much human oversight the assistant requires. Three modes are available:

| Mode | Behavior |
|---|---|
| **Plan** | Discover agents and design a workflow, then ask for confirmation at each step — nothing runs without your go-ahead |
| **Balanced** _(default)_ | Present the plan first, execute with checkpoints, and pause before long-running jobs |
| **Autonomous** | Plan first, then execute the entire workflow non-stop without pausing |

**Cost Mode** — controls resource usage and retry behavior:

| Tier | Behavior |
|---|---|
| **Economy** | Minimize cost — smallest nodepools, sequential execution, test first, max 1 retry |
| **Standard** _(default)_ | Balance cost vs. quality — appropriate nodepools, test-then-scale, up to 2 retries |
| **Performance** | Maximize speed and quality — largest nodepools, parallel execution, 3+ retries, specialized agents preferred |

Both controls are accessible from the input toolbar and persisted per session.

### Plans

When the assistant works on a multi-step task it creates a **plan** — an ordered list of steps (with optional substeps) that tracks progress through the investigation.

- **Creation** — plans are created automatically by the assistant at the start of a workflow. In Plan and Balanced modes the assistant presents the plan for approval before executing; in Autonomous mode it proceeds immediately.
- **Live updates** — as each step runs, the plan card in the chat updates in real time showing step status (pending ⬜, active ▶, completed ✅, failed ❌, skipped ⏭) and a progress bar.
- **Revision** — if the workflow changes mid-execution the assistant can revise the plan, incrementing the revision counter.
- **Access anytime** — click the plan card's **Open in panel** button, or use the plans button in the chat header to open a detail panel with tabbed navigation across all plans in the session, step timing, and progress metrics.
- **History** — completed and failed plans are archived in the session. When a new plan is created the previous one is automatically closed. All past plans are visible in the detail panel.
- **Plan critique** — enabled by default (`discovery.planCritique`), the assistant self-critiques the plan before presenting it (skipped in Economy cost mode).

### Scientific and Engineering Files Visualization

The extension includes built-in viewers that open scientific and engineering file formats directly in VS Code.

Each viewer runs inside a VS Code webview and is powered by well-known open source libraries.

| Viewer | Formats | Open source packages |
|---|---|---|
| **Molecule Viewer** | `.pdb`, `.pdbqt`, `.cif`, `.mol`, `.sdf`, `.mol2`, `.xyz` | [3Dmol.js](https://3dmol.csb.pitt.edu/) |
| **Molecule Viewer** (large structures / density maps) | `.gro`, `.mmcif`, `.mmtf`, `.mrc` | [NGL Viewer](https://nglviewer.org/) |
| **MD Trajectory Viewer** | `.dcd`, `.xtc`, `.trr`, `.nc`, `.lammpstrj`, `.lammps` (auto-paired with a topology file: `.pdb`, `.gro`, `.prmtop`) | [Mol\*](https://molstar.org/) (bundled) |
| **STEP/STP Viewer** | `.step`, `.stp` | [occt-import-js](https://github.com/kovacsv/occt-import-js) (WASM-compiled [OpenCASCADE](https://dev.opencascade.org/)) + [three.js](https://threejs.org/) |
| **GLTF/GLB Viewer** | `.gltf`, `.glb` | [three.js](https://threejs.org/) (`GLTFLoader`, `OrbitControls`) |
| **VTK Viewer** | `.vtk`, `.vtu` | [three.js](https://threejs.org/) (in-house VTK Legacy / VTK XML UnstructuredGrid parser) |
| **HTML Viewer** | `.html`, `.htm` | Sandboxed iframe (no third-party renderer) |

#### Molecular and Trajectory Visualization

- **Molecule Viewer** — renders PDB, CIF, SDF, MOL, MOL2, XYZ, and PDBQT files with 3Dmol.js (cartoon, ball-and-stick, spacefill, and surface representations), and GRO, MMCIF, MMTF, and MRC files with NGL Viewer
- **MD Trajectory Viewer** — plays DCD, XTC, TRR, NetCDF (`.nc`), LAMMPSTRJ, and LAMMPS trajectory files via a bundled Mol\* build (`media/molstar/`) with automatic topology pairing (`.pdb`, `.gro`, `.prmtop`), playback controls (play/pause, frame stepping, speed control), representation switching, and solvent toggling
- **Molecule Editor** — 2D structure editor for drawing and editing chemical structures inline in the chat

#### CAD and 3D Model Visualization

- **STEP/STP Viewer** — renders STEP (`.step`, `.stp`) 3D CAD models using occt-import-js (WASM-compiled OpenCASCADE) for B-Rep tessellation and three.js for display, with assembly tree navigation, section planes, and measurement tools
- **GLTF/GLB Viewer** — renders GLTF and GLB 3D models using three.js (`GLTFLoader` + `OrbitControls`) with animation timeline, camera presets, material inspection, and wireframe toggle

#### Scientific Data Visualization

- **VTK Viewer** — parses VTK Legacy (`.vtk`) and VTK XML UnstructuredGrid (`.vtu`) files with an in-house parser and renders the meshes with three.js, providing scalar field visualization, clip planes, iso-contours, vector glyphs, and configurable color maps

#### HTML Reports

- **HTML Viewer** — renders HTML and HTM files in a sandboxed iframe (no third-party rendering library), used for AI-generated Discovery reports with embedded styling and interactive content

### Session Explorer

Browse and manage investigation files, job outputs, and Azure blob storage directly in VS Code. Features include inline file preview, drag-and-drop upload, rename, download, and delete. Remote files open via the virtual file system, so sibling files are always discoverable.

### Agent Catalog

Browse published agents and tools in the sidebar. Favorite frequently used agents, filter by active status, and open agent definitions in the Azure portal. Publish new agents, tools, and Docker images directly from the chat.

### Command Execution

The assistant can run local shell commands (Docker, Python, pip, git, az CLI, etc.) with an inline approval workflow. Choose to approve once, always allow a specific program, or auto-approve all commands globally via the `discovery.commandApproval` setting.

### Multi-Profile Support

Switch between Discovery environments (dev, production, different subscriptions) without leaving VS Code. Each profile stores its own Azure, OpenAI, and compute settings.

### Session History

Conversations are automatically saved and restored after VS Code restarts. Browse and restore past sessions from the session dropdown. The dropdown updates to show investigation titles as the assistant names them.

### Collections

Collections let you organize related work across sessions into a single curated canvas. Each top-level folder in the Collections panel is a collection that opens as a rich two-column webview:

- **Left column** — browse files in the collection (with in-place folder navigation), manage linked session references, and drop files from your OS
- **Right column** — create and edit Jupyter-style Markdown notes with view, edit, and collapsed modes

Four card types can be added to a collection:

| Card | Purpose |
|---|---|
| **Files** | Local files and linked file references from sessions |
| **Linked Sessions** | References to chat sessions (click to switch) |
| **Notes** | Markdown notes with live preview, editing, and collapse |
| **Viewer** | Inline preview of images, molecules (3Dmol.js), HTML reports, and text files |

Cards can be dragged between columns to rearrange the layout. Viewer cards support four size presets (half/full width, short/tall height). All layout changes are saved automatically to a `.collection.json` manifest.

To add files from the Session Explorer to a collection, right-click a file and choose **Copy to Collection...** (copies the file) or **Link to Collection...** (creates a reference without copying).

### Sessions

Work is organized into sessions — each with its own scripts, inputs, outputs, and metadata. The assistant creates sessions automatically and chains multi-step workflows using job dependencies.

### Projects

The Projects panel shows the active project with a quick-switch picker. Create new projects or switch between existing ones from the title bar.

### External MCP Servers

Connect additional MCP servers (stdio or SSE transport) via the `discovery.mcpServers` setting for custom tool integrations.

## Commands

Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) and type "Discovery" to see all available commands:

| Command                                 | Description                                           |
| --------------------------------------- | ----------------------------------------------------- |
| **Discovery: Setup Wizard**             | Configure Azure, OpenAI, and compute settings         |
| **Discovery: New Chat Session**         | Start a fresh conversation                            |
| **Discovery: Session History**          | Browse and restore past sessions                      |
| **Discovery: Clear Chat**               | Clear the current conversation                        |
| **Discovery: Select Model**             | Choose the LLM engine and model                       |
| **Discovery: Switch Discovery Profile** | Switch between Azure environments                     |
| **Discovery: Switch Project**           | Switch the active project                             |
| **Discovery: Reconnect MCP Servers**    | Re-establish tool connections                         |
| **Discovery: Show Connection Status**   | View connected servers and tool counts                |
| **Discovery: Export Trace**             | Export LLM interaction traces for debugging           |
| **Discovery: Generate Notebook**        | Export an investigation as a Jupyter notebook         |
| **Discovery: Show Build Info**          | Display current extension version and build timestamp |

## Settings

All settings are under the `discovery.*` namespace in VS Code Settings (`Ctrl+,`):

| Setting                         | Default         | Description                                       |
| ------------------------------- | --------------- | ------------------------------------------------- |
| `discovery.configPath`          | _(auto-detect)_ | Path to `discovery_config.json`                   |
| `discovery.systemPrompt`        | _(built-in)_    | System prompt for the assistant                   |
| `discovery.autoConnectServers`  | `true`          | Connect to MCP servers on activation              |
| `discovery.commandApproval`     | `prompt`        | Command approval mode: `prompt` or `auto-approve` |
| `discovery.maxToolRounds`       | `50`            | Max tool call rounds per conversation turn        |
| `discovery.tracing`             | `false`         | Enable JSONL tracing of LLM interactions          |
| `discovery.hiddenAgentPatterns` | `[]`            | Substrings to hide agents from the sidebar        |
| `discovery.hiddenModelPatterns` | `["codex"]`     | Substrings to hide models from the picker         |
| `discovery.mcpServers`          | `{}`            | External MCP servers to connect to                |
| `discovery.planCritique`        | `true`          | Auto-critique plans before presenting to the user |

## Requirements

- VS Code 1.97 or later
- An Azure account with access to a Microsoft Discovery workspace
- For Copilot SDK models: GitHub Copilot CLI (`npm install -g @github/copilot`)
