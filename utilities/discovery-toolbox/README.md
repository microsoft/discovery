# Discovery Toolbox

> Your command center for [Microsoft Discovery](https://learn.microsoft.com/en-us/azure/microsoft-discovery/) — an IT DevOps–focused VS Code extension for the setup, management, and operation of the Azure infrastructure required to run the platform.

Microsoft Discovery is the AI for Science platform that enables agentic-driven scientific research and development. Discovery Toolbox provides an end-to-end deployment and management experience — including instantiation of agents, tools, models, and (soon) knowledge bases, plus declarative validation plans and live agent chat — empowering teams to start doing agentic-driven, scientific R&D from day one.

**Current version:** `v1.1.7`

---

## Install

**Requirements:** Visual Studio Code **1.95+** on Windows, macOS, or Linux.

1. Open the **[`vsix/` folder](https://github.com/microsoft/discovery/tree/main/utilities/discovery-toolbox/vsix)** and download the file with the highest version number — `DiscoveryToolbox-v<version>.vsix`.
2. In VS Code, open the Command Palette (**`Ctrl+Shift+P`** / **`Cmd+Shift+P`**) and run **`Extensions: Install from VSIX…`**, then pick the file you downloaded.
3. Reload VS Code when prompted, then click the **Discovery Toolbox** icon in the Activity Bar to open the **Welcome** page. From there, jump into the **Onboarding Journey** for a guided walk-through.

> **Updating.** The toolbox checks for new releases on activation and shows a banner on the Welcome page. Click **Install Now** to upgrade in place, or repeat the steps above with a newer `.vsix`.

---

## What Discovery Toolbox does

- 🔧 **End-to-end deployment** — Provision the full Microsoft Discovery platform from scratch (VNets, supercomputers, workspaces, projects, chat models, storage, managed identities) using a bundled, hardened Bicep template, deployed directly from inside VS Code with live terminal output.
- 🤖 **Agent & tool publishing** — Publish AI agents and containerized tools directly to your Discovery environment. Create from scratch or from the catalog, then build tool images **remotely via ACR Tasks** — no local Docker required — and push them straight to your Azure Container Registry.
- 🛡️ **Prerequisite validation** — Automatically verify 100+ Azure prerequisites — RBAC roles, resource providers, quotas, policies, **network security perimeter**, and configuration — before deployment, with one-click remediation actions for every issue found.
- 📊 **Architecture visualization** — See your entire Discovery deployment topology as an interactive diagram (workspaces, projects, agents, supercomputers, storage, networking) with real-time health status. Export as PNG (2×) or SVG, or browse a built-in example dataset.
- 💰 **Cost analysis** — Track per-resource costs across your Discovery resource groups (daily, weekly, monthly breakdowns). Sortable table with RG and service filters, plus direct links to the Azure Portal cost blade.
- 📋 **Operational monitoring** — 5-signal diagnostics dashboard (Resource Health, Active Alerts, Advisor Recommendations, Service Health, Diagnostic Settings) across main and managed resource groups, with KPI tiles.

## Key capabilities

- **Onboarding Journey** — Guided 6-step path (Discover → Evaluate → Engage → Triage → Onboard → Deploy & Build) with curated links to the Azure announcement, MS Learn docs, and solutions page.
- **Dashboard** — At-a-glance health of every section with colored status tiles, KPI/hybrid metric tiles, and completion tracking.
- **Prerequisites** — Azure CLI, Bicep, login, tenant, subscription, region — including approved-region validation against the Azure locations API.
- **Deployment Settings** — Region + resource group selectors that act as both the deployment target for new infrastructure and the management scope used to discover existing deployments.
- **Permission Auditing** — Enumerate 15 RBAC roles with member resolution (users, groups, service principals, managed identities) across subscription, RG, and child-resource scopes.
- **Role Summary** — 3-persona capability matrix (Platform Admin · Scientist · Reader) showing what each persona can and can't do based on current role assignments.
- **Quota Management** — vCPU and AI Foundry TPM quotas per region with one-click quota-form data generation; NetApp Files reported informationally.
- **Network Security** — Four checks for the AIFSPInfrastructure service principal (existence, NSP Perimeter Joiner role, role assignment, Reader at subscription scope) with one-click create/assign actions.
- **Bicep Deployment** — Validate, configure, and deploy the bundled template with real-time terminal output and a live Infra Status bar.
- **Agents Page** — Combined catalog browser + agent inventory across workspaces and projects with model, tools, KBs, and Studio/Foundry links.
- **Tool Publishing** — End-to-end ACR build & push pipeline via ACR Tasks (no local Docker required), with image verification and ARM deploy.
- **Agent Publishing** — Create agents from scratch or catalog with 8-phase deploy progress events and retry on failure.
- **Architecture Export** — Export your deployment topology as PNG (2×) or SVG; Show Example mode with realistic sample data.
- **Tracking Log** — Azure Activity Log viewer with date range presets, search, sort, and expandable detail rows.
- **Diagnostics** — 5 signals with 6 KPI tiles and 5 collapsible data tables across main + managed resource groups.
- **Documentation** — Embedded MS Learn docs browser (no git clone required).
- **Activity Log** — Every Azure API call routed through a logged fetch wrapper for full traceability and troubleshooting.
- **Update Checker** — Automatic version check on startup with a welcome-page banner and VS Code notification when a new version is available.

## What's new & coming soon

Experimental features are off by default. To opt in, set `mdToolbox.showExperimental` to `true` in VS Code Settings.

| Status | Feature | What it does |
| --- | --- | --- |
| Experimental | **Plan-Driven Validation** | Author a declarative 7-stage build plan (workspace · chat model · storage · project · agents · interactions), execute it, and review per-step pass/fail with JSONL audit footers. |
| Experimental | **Live Agent Chat** | Talk to deployed Discovery agents from a 3-pane chat UX (investigations · conversations · messages) over REST or MCP, with a four-mode transport selector and per-message override. |
| Experimental | **@discovery Chat Participant** | Slash commands (`/create-agent`, `/explain`) plus `#discovery_*` language model tools for natural-language agent creation, catalog Q&A, and doc search. Requires GitHub Copilot Chat. |
| Experimental | **MCP Catalog & Invoke** | Browse MCP servers exposed by your Discovery environment and invoke their tools directly from the toolbox. |
| Planned | **Bookshelves & Knowledge Bases** | Bookshelf enumeration, KB management, and data-ingestion tracking — wired into the Agent Deploy form's Knowledge Bases multi-select and the architecture diagram. |
| Planned | **Post-Deploy Health Smoke** | Dashboard-level passive health verification, endpoint connectivity tests, and Service Health correlation — complements the active Validation feature. |
| Planned | **Resource Deletion** | Delete actions for agents, tools, storage containers, and projects with confirmation and optional cascade. |
| Planned | **Sidebar Status Indicators** | Activity Bar badge with failed-check count plus per-section status icons in the tree. |
| Planned | **Centralized Input Validation** | Shared validation rules driving inline validation across every editable field. |
| Planned | **Standalone Resource Provisioning** | Install workspaces, projects, and other components via the Discovery REST API for granular, per-resource control. |
| Planned | **@discovery Chat — Write Tools & Bundled Skills** | Phase 5+ follow-on to the chat participant. Adds write tools (deploy / configure) callable from chat, and bundled skill files for common workflows. |

## Resources

- [Microsoft Learn — Microsoft Discovery docs](https://learn.microsoft.com/en-us/azure/microsoft-discovery/)
- [Azure Blog — Microsoft Discovery: advancing agentic R&D at scale](https://azure.microsoft.com/en-us/blog/microsoft-discovery-advancing-agentic-rd-at-scale/)
- [Azure Solutions page](https://azure.microsoft.com/en-us/solutions/discovery)
- [Privacy & data handling](./PRIVACY.md)
- [All available Discovery Toolbox versions](https://github.com/microsoft/discovery/tree/main/utilities/discovery-toolbox/vsix)

## Feedback

Found a bug, want a feature, or have general feedback? Open an issue on the [microsoft/discovery](https://github.com/microsoft/discovery/issues/new) repo and include the page you were on plus your toolbox version (Help → About inside the extension).

---

<sub>Published version **v1.1.7** &middot; built from `c3ae654` on 2026-05-29T18:32:13.198Z.</sub>
