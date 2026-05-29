
<div align="center">

# Discovery Toolbox

### Your Command Center for the Microsoft Discovery Platform

*Discovery Toolbox provides an end‑to‑end deployment and management experience for the Microsoft Discovery platform — including instantiation of agents, tools, models, and (soon) knowledge bases, plus declarative validation plans and live agent chat — empowering teams to start doing agentic‑driven, scientific R&D from day one.*

<sub>About for **v1.1.2** · [Send feedback](https://github.com/microsoft/discovery/issues/new?title=%5BFeedback%5D%20&labels=feedback)</sub>

---

</div>

💡 **First‑time user?** Open the **Onboarding Journey** for a guided 6‑step path from initial Discovery to full deployment — or work through each sidebar section in order, from Prerequisites through Deployment to Operations, to understand what Microsoft Discovery needs and why.

---

## Requirements

**Required**
- **VS Code 1.95+**
- **Azure subscription** with Microsoft Discovery enabled (provisioned by your Microsoft account team)
- **Azure CLI** signed in (`az login`) — or VS Code Microsoft authentication

**Optional**
- **GitHub Copilot Chat** — enables the `@discovery` chat participant and `#discovery_*` language model tools for natural-language agent creation, catalog Q&A, and doc search. *Free tier works; Pro/Business removes monthly limits.*
- **GitHub account with access to the `discovery-catalog` repo** — required only if you want to browse / deploy from the shared Discovery agent catalog.

> Toolbox's deployment, inventory, cost, and operations features all work **without** GitHub Copilot. Only the chat surface depends on it.

---

## Discovery Toolbox Features

<table>
<tr>
<td width="50%">

### 🔧 End‑to‑End Deployment
Provision the full Microsoft Discovery platform from scratch — VNets, supercomputers, workspaces, projects, chat models, storage, and managed identities — using a **bundled, hardened Bicep template** with network isolation tags, deployed directly from inside VS Code with live terminal output.

</td>
<td width="50%">

### 🤖 Agent & Tool Publishing
Publish AI agents and containerized tools directly to your Discovery environment. Create agents from scratch or from the catalog — configure model, instructions, tool bindings, and knowledge bases. Build tool images **remotely via ACR Tasks** and push them straight to your Azure Container Registry.

</td>
</tr>
<tr>
<td>

### 🛡️ Prerequisite Validation
Automatically verify 100+ Azure prerequisites — RBAC roles, resource providers, quotas, policies, **network security perimeter**, and configuration — before deployment, with one‑click remediation actions for every issue found.

</td>
<td>

### 📊 Architecture Visualization
See your entire Discovery deployment topology as an interactive diagram — workspaces, projects, agents, supercomputers, storage, networking — with real‑time health status. Export as PNG (2×) or SVG, or browse a built‑in example dataset.

</td>
</tr>
<tr>
<td>

### 💰 Cost Analysis
Track per‑resource costs across your Discovery resource groups — daily, weekly, and monthly breakdowns. Sortable table with RG and service filters, plus direct links to the Azure Portal cost blade.

</td>
<td>

### 📋 Operational Monitoring
5‑signal diagnostics dashboard — Resource Health, Active Alerts, Advisor Recommendations, Service Health, and Diagnostic Settings — across main and managed resource groups with KPI tiles.

</td>
</tr>
<tr>
<td>

### ✅ Plan‑Driven Validation
Author a declarative 7‑stage build plan (workspace → chat model → storage → project → agents → interactions), execute it, and review per‑step pass/fail with a JSONL audit footer. Stage 6 supports a multi‑substep composer — `createInvestigation`, `addTask`, `addConversation`, `addMessage` — so a single plan can stand up a project, deploy agents, and assert on chat responses end‑to‑end.

</td>
<td>

### 💬 Live Agent Chat
Talk to deployed Discovery agents from the **Validation Interactions** page — a 3‑pane chat UX (investigations rail · conversation switcher · message timeline) over the Discovery data plane. Four‑mode transport selector (`rest-only` / `mcp-only` / `rest-then-mcp` / `mcp-then-rest`) routes each message through REST `POST /conversations/{conv}/openai/responses` or MCP `notifications/message`, with conversation JSONL persistence under `~/.md-toolbox/conversations/`.

</td>
</tr>
</table>

---

## Key Capabilities

| Capability | Description |
|---|---|
| **Onboarding Journey** | Guided 6‑step path (Discover → Evaluate → Engage → Triage → Onboard → Deploy & Build) with curated links to the Azure announcement, MS Learn docs, solutions page, and registration form |
| **Dashboard** | At‑a‑glance health of every section with colored status tiles, KPI/hybrid metric tiles, and completion tracking |
| **Prerequisites** | Azure CLI, Bicep, login, tenant, subscription, region — including **approved‑region validation against the Azure locations API** |
| **Deployment Settings** | Region + resource group selectors that act as both the **deployment target** for new infrastructure and the **management scope** the rest of the toolbox uses to discover existing deployments |
| **Bicep Settings** | Separate sidebar entry for resource names, networking, node pool, chat model, and storage — split from Deployment Settings so deployment scope and template parameters are independently editable |
| **Permission Auditing** | Enumerate **15 RBAC roles** (Owner, User Access Admin, Discovery Platform Admin/Contributor/Reader, Managed Identity Contributor/Operator, Storage Account/Blob Data Contributor, Network Contributor, AcrPush, Azure AI User/Owner, Reader, Bookshelf Index Data Reader) with member resolution (users, groups, service principals, managed identities) across subscription, RG, and child‑resource scopes — uses VS Code Graph token with `az cli` fallback |
| **Role Summary** | **3‑persona** capability matrix (Platform Admin · Scientist · Reader, mutually exclusive top‑down) showing what each persona can and can't do based on current role assignments; collapsed by default with Expand all / Collapse all controls; Members footer row counting distinct users per persona |
| **Assignments** | Sister page to Permissions — read‑only RBAC enumeration with member‑detail browsing |
| **Network Security** | 4 checks for the AIFSPInfrastructure service principal: SP existence, NSP Perimeter Joiner custom role, role assignment, and Reader at subscription scope — with one‑click create/assign actions |
| **Quota Management** | vCPU and AI Foundry TPM quotas per region with bar charts and one‑click quota‑form data generation; NetApp Files (optional storage backend) reported informationally |
| **Resource Providers** | 20 Discovery‑relevant providers with Discovery‑specific descriptions and "Register All" |
| **Azure Policy** | Detect Deny policies and compliance issues that could block Discovery resource deployment |
| **Bicep Deployment** | Validate, configure, and deploy the bundled Bicep template with real‑time terminal output and an Infra Status bar showing live control‑plane resource state. The deploy gate is intentionally targeted — prerequisites, deployment settings, initial checks, and quota must pass plus the Owner‑or‑7‑roles rule (resource providers register during deployment, so they're not a prereq) |
| **Agents Page** | Combined catalog browser + agent inventory — enumerate deployed agents across workspaces and projects with model, tools, KBs, and Studio/Foundry links; load tool/agent definitions from the discovery‑catalog (`registry.json`) with Docker, CPU, RAM, GPU columns |
| **Tool Publishing** | End‑to‑end ACR build & push pipeline — remote builds via **ACR Tasks** (no local Docker required) — with image verification and ARM deploy; auto‑builds the per‑tool image during agent deploy when missing |
| **Agent Publishing** | Create agents from scratch or catalog — select project, model, attach tools and knowledge bases; **8‑phase deploy progress events** with retry on failure |
| **Data Plane Resources** | Discover agents, workflow agents, and investigations via the Discovery data‑plane API |
| **Architecture Export** | Export your deployment topology as PNG (2×) or SVG; Show Example mode with realistic sample data |
| **Tracking Log** | Azure Activity Log viewer with date range presets, search, sort, and expandable detail rows |
| **Cost Analysis** | Per‑RG cost queries with daily/weekly/monthly breakdowns, RG and service filters |
| **Diagnostics** | 5 signals with 6 KPI tiles and 5 collapsible data tables across main + managed RGs |
| **Documentation** | Embedded MS Learn docs browser (no git clone required) |
| **Activity Log** | Every Azure API call routed through `loggedFetch` for full traceability and troubleshooting |
| **Validation Plans** | Declarative 7‑stage build pipeline (workspace · chat model · storage account · storage container · project · agents · interactions) authored on the **Validation Setup** page. Stage 6 supports a multi‑substep composer with five kinds — `createInvestigation` · `addTask` · `addConversation` · `addMessage` · legacy `interaction` — each fanning out to its own wire step, replayed by the **Validation Execution** page and surfaced on **Validation Results** with per‑step pass / fail and run JSONL footers |
| **Validation Interactions** | Live chat with deployed Discovery agents from a dedicated page — investigations rail · conversation switcher · streaming message timeline. Backed by REST `POST /conversations/{conv}/openai/responses` (OpenAI Responses surface with Discovery `agent_reference` / `storageAssets` / `confirmations` extensions) and MCP `notifications/message` text deltas. All conversations persist as JSONL under `~/.md-toolbox/conversations/<name>.jsonl` |
| **Chat Transport Modes** | Four‑mode selector (`rest-only` · `mcp-only` · `rest-then-mcp` · `mcp-then-rest`, default `rest-then-mcp`) decides which chat path is tried first and whether the other is a fallback. Workspace‑persisted on the Interactions page top bar, with per‑message override on Stage‑6 `addMessage` validation substeps. Each delivered message is tagged with a transport badge so failures are loud, not hidden |
| **Update Checker** | Automatic version check on startup — banner on welcome page + VS Code notification when a new version is available. The checker polls `latest.json` in this folder's `vsix/` subfolder |

---

## Sections Overview

| Group | Sections |
|---|---|
| **Introduction** | Welcome · About · Onboarding Journey · Workflow · Dashboard |
| **Setup** | Prerequisites · Deployment Settings · Permissions · Assignments · Role Summary · Initial Checks · Network Security · Resource Providers · Quotas · Azure Policy |
| **Deployment** | Bicep Settings · Control Plane Resources · Bicep Deployment · Data Plane Resources · Architecture |
| **Operations** | Agents Catalog · Agent Deployment · Models · Cost Analysis · Diagnostics · Cleanup · MCP Catalog · MCP Invoke · Documentation · References |
| **Validation** | Validation Setup · Validation Execution · Validation Results · Validation Interactions |
| **Monitoring** | Tracking Log · Activity Log |

> The standalone Tools page was merged into Agents in v0.7.85; tool catalog browsing and tool publishing now live on the unified **Agents Catalog** + **Agent Deployment** pages. The Validation group was introduced in v0.12.48 alongside the four new chat / investigation services.

---

## Upcoming Features

| Feature | Description |
|---|---|
| 📚 **Bookshelves & Knowledge Bases** | Bookshelf enumeration, KB management, and data‑ingestion tracking — wired into the Agent Deploy form's Knowledge Bases multi‑select and the architecture diagram |
| ✅ **Post‑Deploy Health Smoke** | Dashboard‑level health verification, endpoint connectivity tests, and Service Health correlation. Distinct from the shipped **Validation** feature (which runs a declarative plan and asserts each stage); this is a passive, always‑on health view |
| 🧹 **Resource Deletion** | Delete actions for agents, tools, storage containers, and projects with confirmation and optional cascade |
| 🟦 **Sidebar Status Indicators** | Activity Bar badge with failed‑check count plus per‑section status icons in the tree |
| 🧪 **Centralized Input Validation** | Shared `validationRules.json` driving inline validation across every editable field |
| 📦 **Standalone Resource Provisioning** | Install workspaces, projects, and other components via the Discovery REST API for granular, per‑resource control |
| 💬 **@discovery Chat — write tools & bundled skills** | Phase 5+ follow‑on to the shipped chat participant. Adds write tools (deploy / configure) callable from chat, and bundled skill files for common workflows |

---

## Resources

| | |
|---|---|
| ⬇️ **Download** | [`vsix/` folder](https://github.com/microsoft/discovery/tree/main/utilities/discovery-toolbox/vsix) — pick the file with the highest version number |
| 🛠 **Install guide** | [README.md](./README.md#install) |
| 🔒 **Privacy & data handling** | [PRIVACY.md](./PRIVACY.md) |
| 📖 **Microsoft Learn Docs** | [learn.microsoft.com/en-us/azure/microsoft-discovery](https://learn.microsoft.com/en-us/azure/microsoft-discovery/) |
| 📰 **Azure Blog Announcement** | [Microsoft Discovery: advancing agentic R&D at scale](https://azure.microsoft.com/en-us/blog/microsoft-discovery-advancing-agentic-rd-at-scale/) |
| 🌐 **Azure Solutions Page** | [azure.microsoft.com/en-us/solutions/discovery](https://azure.microsoft.com/en-us/solutions/discovery) |
| 💬 **Send Feedback** | [Open a GitHub Issue](https://github.com/microsoft/discovery/issues/new?title=%5BFeedback%5D%20&labels=feedback) |

---

<sub>About for Discovery Toolbox **v1.1.2** · built from `8155eb4` on 2026-05-29T17:58:52.454Z.</sub>
