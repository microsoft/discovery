# QuickStart Scenario — BioPharma CDK Target Selection and Lead Discovery

> **Started from a link to this file?** If the user gave you this guide's GitHub link in a new Discovery project and asked you to run it: read this entire guide first, then follow section 5. Download the six required files listed under **Where to get the files** in section 5 into the open project folder, after asking the user's permission (about 169 MB). Keep their original filenames and verify each size/SHA256 before setup. The user does not need to download, attach or unzip anything. All approval gates in section 5 still apply; reading or downloading this guide is not permission to install or compute.

**Document revision:** 0.11-proposed, 2026-11-06 — proposed from revision 0.10 after a second-machine run; pending owner review. This single Markdown file contains the **QuickStart Scenario specification**, the **customer Quick Start guide**, and the **agent-readable Execute in Discovery instructions**. Revision 0.10 replaced all earlier dependency-selection flows with one ordinary typed **Yes** or **No** reply for the complete set of 14 pinned dependencies, retaining Required labels and descriptions. Yes selects the full set; No declines and pauses setup. Selection is neither installation nor computation consent. It changes documentation only; it creates no agents, manifest, catalog entry, app controls or replacement ZIP.

**Applies to every ingesting Discovery chat:** These instructions are portable and apply whenever this file is ingested into any Discovery chat and the user requests execution. Throughout this guide, "this chat", "current chat" and "in-chat" mean that receiving Discovery conversation, not the conversation in which this guide was edited. Present all 14 dependencies with descriptions and Required status, then ask the single full-set Yes/No question in section 5 and accept an ordinary typed chat reply. Do not invoke `ask_user` for this dependency response or use selectable cards, checkboxes, per-package questions, removal/exceptions flows, external forms or file uploads. Inspect that environment afresh; never inherit selections, installation approvals, computation approvals or readiness results from another conversation. This guide contains behavior instructions, not saved user consent or an implementation of chat controls. Merely opening or ingesting the file does not authorize installation or computation.

**When this file is ingested and the user asks to run:** Follow the section 5 intake instructions before execution. Check the current environment, then state **Ready**, **Action required**, or **Not yet verified** and list only what is missing, mismatched or unverified, with the exact next action. Explicitly check **GPT-6 Astra (`gpt-6-astra`)**, Python, dependencies, input files and local execution access. Always present the **full dependency list in this chat with Required after every package/version and a description on the next line under every dependency**, even if packages are already installed or another prerequisite is blocked. Then ask **"Do you select all 14 required dependencies listed above? Reply Yes or No in ordinary chat. This selects dependencies only; it does not authorize installation or computation."** Accept one typed response for the complete set: Yes selects all 14; No declines the set and pauses setup. Do not invoke `ask_user` or require any selection UI. Astra is a manual model selection, not an installable package. Do not infer readiness or installation/computation consent from this file, its examples or a previous session.

**Readiness:** Scenario specification and customer directions are documented. The bounded frozen-input computation has local execution evidence. Stable component identifiers, immutable GitHub references, catalog integration and customer-instance validation are **PENDING**. This is not yet a published, catalog-selectable, fully pre-validated QuickStart Scenario.

**Purpose:** Launch the BioPharma scenario from Discovery with **frozen-input reference computation as the default**: recompute decision-model draws, solubility predictions and integrated candidate ranking from the supplied snapshot, then deliver native exports and a dashboard. **Fresh-data discovery is a separate, explicitly approved mode** covering new evidence, qualification, docking and training; it is not exact reproduction.

**Which scenario this reproduces:** The owner-validated scenario is the full fresh-data campaign, which took several hours with GPT-6 Astra. This QuickStart's default reproduces only that campaign's final fixed-input stages from the supplied snapshot (about two minutes of analysis). It does not rerun the whole campaign.

**Reference and revision history:** The campaign executed on 2026-11-02. Revision 0.3 introduced the bounded operational launcher; revision 0.4 defined the QuickStart Scenario and its component-reference requirements; revision 0.5 made missing prerequisites and manual actions explicit at intake; revision 0.6 added per-dependency Yes/No approvals; revision 0.7 introduced checklist-based selection; revision 0.8 added batch text selection and Required labels. Revision 0.9 (2026-11-04) introduced click-only Select all / remove-exceptions cards; that behavior and all earlier dependency-selection interfaces are superseded by revision 0.10 (2026-11-05): one ordinary typed Yes/No reply for the complete required set, with separate installation and computation approvals. The operational ZIP's bundled guide remains revision 0.3; document revision 0.10 is not a scenario release or execution-profile version. Revision 0.11-proposed (2026-11-06) adds Python 3.13.14 install steps, package-index reporting, a consistent rule that the frozen run does not use CLIO, an explicit computation-approval prompt, the expected silent verification time and behavior during the run, guide-overwrite and extraction-path guidance, and measured second-machine timing. It changes no pins, scientific scope, launcher or ZIP. The version 0.2 fresh-science prompt is preserved below as a separate extension. The default does real fixed-input computation, not only viewing, hashing or HTML rendering. It reuses original docking, preparation, evidence curation and fitted-model training; it is not a new end-to-end discovery run.

**Exclusions:** No molecular dynamics, GPU computation, paid scientific services, Discovery Engine, Bookshelves, unrelated-project data or private-data uploads. Default reproduction explicitly permits only the hash-pinned supplied snapshot. Fresh mode must retrieve its own evidence.

**Customer distribution:** The QuickStart Scenario is intended to be published in GitHub and referenced by a Discovery scenario catalog. This Markdown is its customer guide and directions, not the catalog itself. Existing ZIPs are supporting implementation/data assets, not the definition of a QuickStart Scenario and not a mandatory product-wide packaging format. Their inventories are in **Appendix A**. No personal file handoff or internal collaboration-system access is required. All required files are publicly available: see **Where to get the files** in section 5. Catalog availability remains **PENDING**.

**Reader entry points:** Engineering should start with **section 0**, which defines the scenario, reusable references and catalog contract. Customers should start with **section 5, Execute in Discovery**, which distinguishes future catalog selection from the existing manual execution path. Sections 1–4 explain the configuration; section 6 is a separately approved fresh-science extension, not the validated default.

## 0. QuickStart Scenario specification

### 0.1 Definition and boundaries

A **QuickStart Scenario** defines a pre-packaged, referenceable set of agents, tools, skills, prompts, inputs and expected outputs based on a pre-validated scenario. Its accompanying Markdown provides the directions needed to reproduce that validated scope in a customer's Discovery instance.

A QuickStart Scenario is not synonymous with a starter kit, a ZIP, an agent or this guide alone. It may use no starter kit, one starter kit or selected components from a starter kit. Agents are independently reusable: the same agent identity can be referenced by multiple scenarios without creating a scenario-specific duplicate.

For this BioPharma scenario, the **default reference scope** is frozen-input decision scoring, saved-model solubility inference, candidate ranking/native exports and retained-report rendering. Evidence curation, preparation, docking and training are reused. The full fresh-discovery prompt is an extension and must not inherit the default's validation status.

| Scenario field | Value / status |
|---|---|
| Display name | BioPharma CDK Target Selection and Lead Discovery |
| Stable scenario identifier | **PENDING — engineering-owned identity convention and assignment** |
| Scenario release/version | **PENDING — not the same as this document's revision 0.10 or the local computation profile name** |
| Customer guide | This Markdown file; guide revision 0.10 |
| Default execution profile | `cdk-frozen-reference-v1`; existing local profile name, not a globally registered scenario ID |
| Audience | Customers and engineers reproducing the reference scenario; scientists and executives reviewing its outputs |
| Reference evidence | Historical campaign records and local frozen-replay receipts described in sections 5–7 |
| Validation designation | Locally checked frozen computation with documented presentation recovery; customer-instance/catalog launch not validated |
| Starter-kit dependency | None declared for the current manual reference path. No starter kit identity or membership is inferred from repository naming |
| Selected starter-kit agents | **PENDING if a kit is adopted**; explicitly list only selected agent references, not every agent in the kit |
| GitHub scenario source and immutable revision | **PENDING — repository owner/name, scenario location and immutable revision have not been supplied** |
| Publication and catalog status | **PENDING — no published catalog record or selectable UI entry is claimed** |
| Discovery app support | Local reference execution exists; catalog resolution, automatic configuration and customer-instance launch remain pending |
| Discovery Services support | **PENDING / not validated**; do not infer service compatibility from the local run |
| Maintainer and support destination | Publishing maintainers; public support URL **PENDING** |

### 0.2 Reusable component references

The labels below are **document-local reference labels**, not invented GUIDs, catalog identifiers or a proposed machine-readable schema. Engineering must assign or resolve durable identifiers using its GitHub-compatible convention. A runtime tool name, model ID, filename or display name is not a substitute for an agent's stable identifier.

For every published reference, record the stable component identity **and separately** its validated version/immutable source revision, GitHub locator, required permissions and compatibility requirements. Reuse an existing component identity across scenarios; pin the version validated by each scenario. Do not silently resolve to a newer version.

| Local reference label | Component kind and current reference | Use in this scenario | Stable identifier / immutable published reference |
|---|---|---|---|
| `coordinator` | Existing Discovery scientific assistant; role and tools in section 2.1 | Required for guided app execution; coordinating model `gpt-6-astra` | **PENDING**; historical agent instruction revision was not captured |
| `investigator` | Existing persistent CLIO investigation capability/session | Historical campaign and fresh extension; not required by the default deterministic launcher | **PENDING**; a session/run ID is not a reusable agent ID |
| `local-command-tools` | Local command/process interfaces listed in section 2.3 | Required for preflight, approved execution, logs and process control | **PENDING per referenced tool**; confirm runtime exposure and permissions |
| `workspace-tools` | File inspection/editing interfaces listed in section 2.3 | Required to read inputs, preserve originals and deliver results | **PENDING per referenced tool** |
| `approval-tool` | `ask_user` or the supported runtime approval interface for separate installation/scope approvals only; ordinary chat for dependency selection | Capture missing installation/scope approvals; never invoke `ask_user` for the dependency Yes/No response or infer installation consent from selection or ingestion | **PENDING**; exact runtime binding must be confirmed |
| `research-tools` | Public web/data retrieval interfaces and sources in sections 2.2–4 | Fresh extension only; no new scientific retrieval in the default | **PENDING per referenced tool/source binding** |
| `investigation-skill` | `investigate` in the historical skill catalog | Historical investigation/fresh extension; not a scientific engine | **PENDING**; skill display name is recorded, versioned published definition is not |
| `report-skill` | `scientific-report` in the historical skill catalog | Historical report creation/fresh extension; default rendering uses retained assets and scripts | **PENDING**; the frozen renderer does not require invoking this skill |
| `scenario-intake-prompt` | Agent-readable intake instructions in section 5 | Resolve scope/references and identify blockers before execution | Inline in guide revision 0.10; standalone prompt ID/publication **PENDING** |
| `frozen-execution-prompt` | Exact copy/paste launch instruction in section 5 | Default bounded reference computation | Inline in this guide; durable prompt ID/immutable published revision **PENDING** |
| `fresh-extension-prompt` | Consolidated prompt version 0.2 in section 6 | Optional, separately approved fresh research; not the default acceptance contract | Durable prompt ID/immutable published revision **PENDING** |
| `scientific-runtime` | Pinned Python requirements, `profile.json` and source scripts | Default numerical computation and rendering; versions in section 2 | Local pins available; published component/source locator **PENDING** |
| `reference-inputs` | Hash-pinned `cdk_non_md_deliverables.zip` in section 5 | Required frozen scientific inputs and baseline outputs | Content hash recorded; public download: [`cdk-frozen-reference-v0.11` release](https://github.com/microsoft/discovery/releases/tag/cdk-frozen-reference-v0.11) |
| `expected-outputs` | Default output contract in section 0.4 and detailed checks in section 5 | Establish successful delivery without claiming validated drug leads | Artifact paths and comparisons recorded; catalog contract/version reference **PENDING** |

Local Python and Vina worker processes are **not agents** and must not receive fictitious agent GUIDs. `gpt-6-astra` identifies the coordinating model, not the coordinator agent. The model ID is not an immutable backend revision.

### 0.3 Catalog and selection contract — engineering-owned

When implemented, selecting this QuickStart Scenario in the Discovery app or Services UI must resolve its references from an existing/live catalog of scenarios known to be published and available in GitHub. This is a **required product behavior**, not a claim that the current app exposes such a catalog or UI control.

Engineering owns the identifier convention (including whether tags, GUIDs or another GitHub-compatible mechanism are used), catalog schema/storage, publication discovery, refresh policy, version resolution, permission handling and UI implementation. This document does not select or implement any of them.

| Information the catalog/resolver must supply | BioPharma status |
|---|---|
| Stable scenario identity, display name, summary and published scenario version | Display name/scope documented; identity and published version **PENDING** |
| Verified GitHub scenario locator and immutable validated revision | **PENDING** |
| Guide and prompt references bound to that scenario version | Inline guide/prompts documented; published bindings **PENDING** |
| Referenced agents, tools and skills, with stable IDs and validated versions | Logical references in section 0.2; engineering bindings **PENDING** |
| Optional starter-kit identity/version and explicit selected component subset | No current kit dependency; any future binding **PENDING** |
| Input assets, integrity metadata, dependencies and permissions | Local inputs/pins documented; published resolution/installation integration **PENDING** |
| Expected outputs, acceptance contract and validation evidence | Local evidence documented; catalog-linked evidence and approval **PENDING** |
| Supported app/Services versions, platforms and execution profiles | Historical local runtime recorded; compatibility certification **PENDING** |
| Publication/availability state, maintainer and support destination | **PENDING** |

Resolution must not invent missing IDs, substitute a similarly named agent, install a whole starter kit when only selected agents are required, or silently change versions. An unavailable or incompatible required reference must produce an explicit blocker. Optional fresh-extension components must not become hidden prerequisites of the default frozen run.

### 0.4 Default expected-output and acceptance contract

| Deliverable | Expected reference result / acceptance |
|---|---|
| Target decision | Recomputed fixed-assumption assessment matches retained baseline: conditional CDK4 recommendation; CDK2 alternative. The 68.538% rank-winning frequency is not an approval probability |
| Solubility inference | Predictions and status/domain fields for 1,100 eligible parents match the retained baseline using the saved model; no retraining |
| Candidate exports | 100 exploratory structures with matching CSV identities/order, SMILES and valid SDF structures; detailed numeric/coordinate tolerances in section 5 |
| Reused docking evidence | Reconcile the same 1,100 parents across six CDKs and 6,600 retained primary pairs; no claim of newly executed docking |
| Customer-readable results | `work/outputs/cdk_campaign_report.md` and `work/outputs/cdk_executive_dashboard.html`; retained narrative and visual assets, with HTML regenerated after semantic acceptance |
| Execution/provenance evidence | Preflight, run receipt, stage logs, semantic acceptance and new artifact hashes as listed in section 5 |
| Scientific limitations | Zero experimentally established broad threefold-selective leads; failed CDK7 native-pose gate; solubility prediction is not full ADME |
| Catalog/customer-instance acceptance | **PENDING** until the published references resolve and the selected scenario is reproduced in the supported customer environment |

Local computation passing is evidence for the stated frozen scope, not approval of unresolved catalog integration or of the fresh extension. Changes to component versions, prompts, inputs or execution scope require validation appropriate to those changes before a new scenario version is designated pre-validated.

## 1. Scenario execution identity

| Field | Value |
|---|---|
| Scenario and observable outcome | Full scientific scenario: compare CDK target–indication opportunities, screen at least 1,000 parents across a CDK panel and prioritize 100 exploratory structures. Default executable mode: reproduce fixed-input decision scoring, solubility inference and ranking using the supplied evidence, docking and fitted model; export native structures, dashboard and receipts. Fresh scientific execution is separately approved and agent-led. |
| Audience / vertical | BioPharma discovery scientists, research leaders, startup/investment decision-makers and demo reviewers. |
| Delivery mode | Discovery app with hosted model access and local scientific computation. Microsoft Discovery service deployment is not part of this recipe. |
| Tested configuration / profile identifier | Default executable `cdk-frozen-reference-v1`, defined by bundled `profile.json`. Fresh mode: `biopharma-cdk-non-md-cpu4-v0.2`, a consolidated agent-led recipe, not an automated pipeline. Snapshot cutoff: 2026-11-02 UTC. |
| Maintainer / document version / validation | Publishing repository maintainers handle distribution/support. Guide revision 0.11-proposed (from 0.10); local launcher profile and fresh prompt remain unchanged. Scenario release identity is PENDING. Historical artifacts validated 2026-11-02; operational evidence is in `validation/engineering_validation.json` in the existing operational release. This documentation revision does not constitute a new app/customer-instance validation. |

## 2. Configuration matrix

The coordinating chat configuration is distinguished from unrecorded investigator settings.

| Component | Applicability | Configuration to record |
|---|---|---|
| Model | Core | **GPT-6 Astra**, model ID **`gpt-6-astra`**, used in the coordinating chat; OpenAI model accessed through the Discovery app's hosted model integration. Exact backend revision, temperature, top-p, context/output limits and model seed: Not recorded. Model ID is not an immutable version pin. |
| Agents | Core | Discovery scientific assistant for planning, coordination and delivery; CLIO investigation capability for sustained execution and artifact tracking in the historical campaign and the fresh extension only. The default frozen run uses the coordinating assistant and local execution and does not start CLIO. Two logical roles are evidenced, not a verified count of every participating session. Investigator/subagent model IDs, agent build versions and instruction hashes: Not recorded. Do not assume every delegated call used Astra. |
| Orchestration | Core | Default: preflight → safe extraction/hash verification → fixed decision scoring → model inference → ranking/native exports → semantic comparison → presentation → receipts/hashes. Serial one-thread stages. Fresh mode retains the historical stage mapping below, maximum four total scientific threads and 30-minute progress updates. |
| Execution policy | Core | Default frozen launcher: serial stages, one numerical thread, no GPU, 1,800-second timeout per stage, no automatic retry, explicit installation/computation approval and checkpoint-checked resume. Fresh historical campaign: maximum four scientific threads, no overall cutoff after approval; historical global retry/stage-timeout settings were not recorded. |
| Tools / APIs | Core | Public web search/fetch; ChEMBL compounds/assays; RCSB/wwPDB structures; AqSolDB solubility; KIBA and permitted public mappings; literature, clinical and competitive sources. PowerShell/Python, RDKit, Meeko, AutoDock Vina, pandas/NumPy/SciPy, scikit-learn/joblib and offline reporting/ZIP/hash tools. |
| Scientific versions | Core | Python 3.13.14, 64-bit AMD64; Python dependencies below. AutoDock Vina 1.2.7 is required for separately approved new docking, not default inference/ranking. No Vina binary or installed environment is bundled. |
| Reporting capabilities | Core | Evidence-grounded Markdown and offline HTML with embedded tables/charts/molecular depictions; native CSV/SDF/SMILES; manifest/checksum validation. Investigation and scientific-report capabilities were used; exact capability versions/hashes: Not recorded. |
| Azure Container Apps (ACA) | N/A | No ACA deployment, images, replicas, service region or secret store required. |
| Sample inputs | Core | Default: hash-pinned `cdk_non_md_deliverables.zip` with 1,100-parent library, prepared panel, native docking, trusted fitted model and evidence/assays. Fresh run: independently retrieved public inputs. The available earlier clean release is intentionally pinned; it is not the missing timed release. |

### 2.1 Agents, corresponding tools and capabilities

The reference workflow used a coordinating assistant and a persistent investigation session. The stage responsibilities below do **not** imply that separate target-selection, docking, ADME or reporting agents were created. Scientific packages are invoked through local execution; they are not assumed to be individually registered MCP tools.

| Agent / execution component | Corresponding tools or interfaces | Capabilities and responsibilities | Access / setup requirement |
|---|---|---|---|
| **Discovery scientific assistant — coordinator** | Hosted `gpt-6-astra`; ordinary chat for the full-set dependency Yes/No response (`ask_user` must not collect it); `ask_user` for separate approvals where supported; `clio-start`, `clio-wait`, `clio-steer`, `clio-status`, `clio-stop` (fresh extension only; not used in the default frozen run); file inspection and local execution as needed | Clarify objectives; present the plan; obtain authorization; launch and steer the investigation; monitor progress; communicate blockers; check delivery artifacts and explain limitations | Discovery chat with Astra access, investigation connection, local workspace access and approval for scientific execution |
| **CLIO investigation session — execution agent (historical campaign and fresh extension only)** | Not started by the default frozen run. Started/resumed through `clio-start`; progress/results through `clio-wait`; steering through `clio-steer`; status/stop through the corresponding controls. Uses the scientific execution stack below through its own available tools | Sustain the multi-stage campaign; gather evidence; coordinate dependent/parallel work; execute scripts; retain checkpoints and provenance; recover missing jobs; produce results and package | Verify the investigator itself has web retrieval, file and local-command access. Parent-tool availability does not prove child access. Exact historical investigator model and tool-permission manifest were not retained |
| **Local scientific worker processes — not LLM agents** | `powershell`, `read_powershell`, `stop_powershell`; isolated Python executable; Vina executable and Python libraries | Retrieve/curate data, prepare structures, run docking, train/predict solubility, compute ranking and export artifacts | Run-owned environment and writable folders; CPU-only; shared maximum of four scientific threads, including nested numerical-library threads |

**Agent count and identity:** One coordinating chat and one durable investigation lineage are evidenced. That investigation was resumed across interruptions; continuation IDs do not represent separate simultaneous scientific campaigns. A complete historical count of internal delegated sessions, their models and their permissions is not available. The recipe does not require users to create a suite of named specialist agents that did not exist in the recorded run.

### 2.2 Stage-to-tool capability mapping

This table maps work to the recorded execution stack and source artifacts. It describes scientific responsibilities within the investigation, not additional agent definitions.

| Stage / responsible component | Tools, packages and sources | Capability | Output / completion evidence |
|---|---|---|---|
| **Planning and orchestration — coordinator + investigator** | CLIO controls; user approval; session task tracking (`sql` where exposed); local process controls | Plan dependencies, enforce resource/data policy, checkpoint and resume work, provide 30-minute progress updates | Approved plan, campaign configuration, stage status and execution logs |
| **Target and competitive assessment — investigator** | Public web search/fetch; clinical/literature/company sources; `assessment.py`; NumPy/pandas | Compare biology, therapeutic window, clinical evidence, selectivity, differentiation, market and execution/IP; run uncertainty and sensitivity analyses | Source ledger, criterion scores, 50,000-draw ranking results, runner-up and reversal scenarios |
| **Compound and assay qualification — investigator + Python workers** | ChEMBL API/data; KIBA and permitted mappings; requests, pandas, RDKit; qualified-library/evidence and clearance scripts | Normalize parent identities; curate assay evidence; deduplicate; exclude known potent selected-target binders; distinguish controls from discoveries | `data/library_qualified.csv`, assay provenance, exclusion records and eligibility counts |
| **Receptor/ligand preparation — investigator + Python workers** | RCSB/wwPDB structures; Biopython, Gemmi, RDKit, Meeko; retained structure-preparation source and panel records | Prepare receptors/ligands and docking inputs; retain grids and coordinate provenance; perform native-pose checks | Prepared structures, `structures/panel.json`, preparation provenance and receptor-validation status |
| **Cross-CDK docking — local workers under investigator control** | AutoDock Vina 1.2.7; `engine.py`, `batch.py`; CPU scheduler | Dock identical eligible parents across the panel; save native scores/poses; recover missing-only jobs and assess controls/seed sensitivity | Native pose/log files and reconciled target-parent results; reference total 6,600 primary pairs |
| **Solubility modeling — investigator + Python workers** | AqSolDB; RDKit descriptors/fingerprints; NumPy/pandas/SciPy; scikit-learn/joblib; `solubility.py` | Prepare scaffold-separated data; fit/evaluate baseline and predictive model; estimate uncertainty and domain applicability | Training/split provenance, trusted model artifact, held-out metrics, prediction and applicability flags |
| **Integrated prioritization — investigator + Python workers** | RDKit, pandas; `rank.py`; docking, assay and solubility outputs | Apply physicochemical/PAINS flags; assess diversity; integrate measured evidence and predictions without claiming validated selectivity | Ranked tables, filter counts, 100 exploratory CSV/SDF/SMILES exports and explicit unmet gates |
| **Report and reproducibility delivery — investigator; coordinator checks handoff** | `scientific-report` guidance; Markdown/HTML rendering; RDKit depictions; standard-library CSV/JSON, `hashlib` and `zipfile`; package/replay scripts | Generate matching evidence-grounded reports; embed offline data/graphics; preserve native artifacts; validate links, identities, counts and hashes | Markdown report, offline dashboard, manifest, checksum, validation receipt and clean ZIP |

**Important capability boundaries:** Docking ranks hypotheses; it does not measure potency or establish cross-target affinity ratios. The ADME-related capability exercised here is **solubility prediction**, not a comprehensive ADME/toxicology platform. Patent assessment is preliminary, not legal clearance. Failed validation and out-of-domain predictions remain visible in the outputs.

### 2.3 Runtime tools, skills and readiness checks

| Capability layer | Reference interfaces | What to verify before launch |
|---|---|---|
| Investigation control | `clio-start`, `clio-wait`, `clio-steer`, `clio-status`, `clio-stop`; optional `clio-archive` | A connected investigation capability is available, a bounded objective can be launched, and its status/results can be retrieved. Resume existing lineage rather than duplicating active work |
| Research retrieval | `web_search`, `web_fetch`; requests-based public data retrieval | Required public sources are reachable and retrieved material can be recorded with provenance; no authenticated browser-session access is assumed |
| Workspace inspection/editing | `glob`, `rg`, `view`, `apply_patch` or supported equivalents exposed in that session | Read and write a run-owned location; preserve original sources; do not assume tool names remain identical across model/tool configurations |
| Local execution | `powershell`, `read_powershell`, `stop_powershell`, `list_powershell` | The isolated Python and Vina executables run; process IDs/logs can be tracked; only run-owned processes are stopped |
| Investigation guidance | `investigate` skill | The capability is available in the active skill catalog. It guides investigation; it is not itself a chemistry engine or an additional scientific dataset |
| Report guidance | `scientific-report` skill | The capability is available and can generate Markdown plus offline HTML using actual evidence. It does not install scientific dependencies |
| User approval and task state | Ordinary chat for the dependency Yes/No response, never `ask_user`; `ask_user` or supported approval interface for separate installation/scope approvals; session `sql` where available | Dependency selection, installation/scope approvals and stage status are captured separately; these interfaces do not replace scientific validation |

Tool names above are the exposed interfaces from this session, not a separately exported, version-pinned plugin installation specification. Verify them in the recipient's runtime and in the investigator's context before launching. If missing, connect the appropriate reviewed capability through the app's supported GitHub URL, MCP server or local-folder flow. Record actual registration/version and permission details; do not treat a file on disk as proof of activation.

**Not required:** Discovery Engine, Bookshelves, ACA/HPC deployment, molecular-dynamics engines, GPU tools, browser automation, internal collaboration-system access or a personal handoff from the scenario author.

**Pinned Python requirements** — retained `requirements.txt`:

```text
numpy==2.4.3
scipy==1.17.1
pandas==2.2.3
scikit-learn==1.8.0
joblib==1.5.3
rdkit==2025.9.6
meeko==0.7.1
gemmi==0.7.5
biopython==1.86
requests==2.32.5
Markdown==3.10.2
beautifulsoup4==4.13.4
openpyxl==3.1.5
Pillow==12.1.1
```

**Scientific parameters:** 50,000 decision-model draws, seed 20261102; weights: biology 20%, therapeutic window 20%, clinical translation 15%, selective tractability 15%, differentiation 15%, commercial opportunity 10%, execution/IP 5%. Primary batch docking: seed 20261102, one CPU per Vina job, exhaustiveness 1, three poses, energy range $4\,\mathrm{kcal\,mol^{-1}}$, batch chunk size 50, maximum four workers. Other recorded seeds: 20261103 and 20261104. Low-exhaustiveness screening is exploratory, not an affinity measurement.

**Reference receptor panel:** CDK4/7SJ3, CDK6/2EUF, CDK2/1H1Q, CDK1/4Y72, CDK7/7B5O and CDK9/3BLR. Retain preparation, native-ligand and coordinate/grid provenance. CDK7 native-pose validation failed in the reference campaign.

## 3. System requirements

No hardware minima or cross-platform compatibility matrix was established. Recommendations are guidance, not benchmarks. “Actually tested” records the historical host/runtime, not a new survey of the recipient computer.

| Applies to | Requirement | Minimum | Recommended | Actually tested |
|---|---|---|---|---|
| App | OS and version | Not validated | Windows 11 matching the reference environment | `Windows-11-10.0.26300-SP0` in historical readiness record |
| App | CPU architecture | 64-bit | x64/AMD64 (validated). Windows ARM64, macOS and Linux are unvalidated; see section 5 for the Python route per platform | AMD64, 64-bit Python |
| App | CPU family / cores | Not validated | Capacity for up to four concurrent scientific threads; shared cap remains four | 22 logical CPUs reported; processor family and physical-core count Not recorded |
| App | RAM | Not validated | Size for data/model preparation and concurrent jobs; no numerical recommendation validated | Not recorded |
| App | GPU / VRAM | N/A | CPU-only; no GPU | No GPU scientific computation in scope |
| App | Free storage | Not validated | Short local workspace with room for raw data, environments, poses, logs and packaging copies; default launcher requires a 3 GB free-space safety allowance, not a measured minimum | Historical readiness recorded 436,270,391,296 free bytes. Default snapshot is 168,396,900 bytes compressed and 1,053,234,791 bytes uncompressed, before filesystem overhead; every new run extracts its own copy |
| App | Network | Not validated | Hosted-model and public scientific-source access during a fresh run | Public retrieval used; throughput/proxy/latency Not recorded |
| Services | General node pool: node count; SKU/size | N/A | N/A | Services not used |
| Services | General pool: vCPU/RAM/GPU per node; scale limits | N/A | N/A | Services not used |
| Services | SuperComputer Nodepool: node count; SKU/size | N/A | N/A | Services not used |
| Services | SuperComputer: vCPU/RAM/GPU per node; scale limits | N/A | N/A | Services not used |

**Bookshelf — Services:** N/A; the campaign explicitly excluded Bookshelves and former-project grounding.

| Field | Tested profile value |
|---|---|
| Source corpus | N/A for Bookshelf; public source records are retained directly with the campaign. |
| Index | N/A |
| Indexing recipe | N/A |
| Index-ready condition | N/A |

## 4. Prerequisites

- **Access:** Discovery app access and entitlement to select GPT-6 Astra; permission for local commands and isolated dependency installation; access to public sources. No Discovery service subscription, ACA quota or GPU allocation is required. Exact app build and authentication-provider configuration: Not recorded.
- **Capabilities:** Default frozen mode needs the existing scientific assistant and local command/file capability; investigation and public scientific retrieval are not required. Fresh mode additionally needs the investigation, retrieval and reporting capabilities in sections 2.1–2.3. CLIO is not Discovery Engine. Missing capabilities can be added through supported GitHub URL, MCP server or local-folder import flows; verify activation rather than assuming a file registers a capability.
- **Environment:** Python 3.13.14 64-bit; validated on Windows x64, other platforms unvalidated (install steps in section 5, *One-time setup: install Python 3.13.14*) and the pinned requirements; use an isolated virtual environment for customer setup. Vina 1.2.7 is required only for separately approved docking, not default replay. Edge or another browser displays delivered HTML. PowerShell instructions below assume Windows.
- **Fresh-mode endpoints only:** ChEMBL: `https://www.ebi.ac.uk/chembl/api/data/`; structures: `https://files.rcsb.org/`; solubility metadata: `https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/OVHAW8`; engine: `https://github.com/forlilab/AutoDock-Vina/releases/tag/v1.2.7`. The default scientific replay does not retrieve these sources. Hosted chat and opt-in dependency installation still require their own network access.
- **Authentication:** Use the app's supported sign-in/connection configuration for hosted-model access; do not put credentials in prompts or files. Public scientific endpoints were used without project secrets. Public GitHub release downloads require no internal organizational account; model access remains a separate prerequisite.
- **Data:** Fresh public retrieval for the fresh-run profile. Preserve ChEMBL CC BY-SA 3.0, KIBA CC BY 4.0, AqSolDB/wwPDB CC0 and source-specific notices. The unspecified-license DeepDTA mapping was not redistributed. Do not package copyrighted article full text or private data. Load joblib/pickle models only from trusted, hash-verified artifacts.

## 5. Setup — one reproducible reference path

### Execute in Discovery — default frozen-input computation

**Catalog selection path — pending engineering integration:** Once published and indexed, the customer selects the named QuickStart Scenario and its validated version through the supported Discovery app or Services scenario-selection experience. That selection must resolve the component references in section 0, present this guide and the bound prompts, check compatibility/permissions, and expose missing prerequisites before execution. Exact UI labels, navigation and automatic population behavior are not specified here because the engineering implementation is pending. Do not assume the current UI already supports these steps.

**Manual path available now:** The existing local execution procedure below can be followed using the supplied implementation assets and verified runtime capabilities. It does not register a catalog entry, resolve pending agent IDs or validate the future catalog-selection experience. Merely ingesting this Markdown neither supplies the scientific inputs/scripts nor installs or activates tools.

**Required first readiness response:** After safe inspection, give one status sentence and a short action table. Use the format **Item | Observed | Required action**, showing only missing, mismatched or unverified items; summarize checks that passed in one line. Show this table in a normal chat message, never inside an approval or question dialog: dialog text renders as plain text, so Markdown tables and bold appear as raw characters. Do not open with the scenario history, a publication checklist or a raw traceback. If inspection is blocked, say what could not be checked instead of assuming it is missing. Show all independently discoverable blockers together, then always present all 14 pinned dependencies with descriptions and Required labels and ask the single ordinary-chat Yes/No question below, even when installation is not needed or other gates are blocked. The action table is not a substitute for the full dependency list. Capture selection and separate approval before installation.

| Check before execution | What to tell the user if action is needed |
|---|---|
| Coordinating model | "Select **GPT-6 Astra (`gpt-6-astra`)** in the app's model selector. Current model: `<observed model or unknown>`." Recheck the runtime after the switch; a promise to switch is not confirmation. Do not claim the agent can change the UI selection or silently substitute another model. |
| Supplied files | Identify the missing `cdk_operational_bundle_v1.zip`, its integrity attachments, or `cdk_non_md_deliverables.zip` by name and request their location or matching release URL. For an already extracted bundle, check `workflow.py`, `profile.json`, `launch.ps1`, integrity records and the unextracted snapshot beside them. Verify the supplied hashes before use; never substitute the timed ZIP. |
| Python runtime | Report the detected version, architecture and interpreter path. Require **Python 3.13.14, 64-bit**. Also report the OS and CPU architecture; Windows x64 is validated, other platforms are unvalidated and must be labelled so. If Python is absent or mismatched, show the user the *One-time setup: install Python 3.13.14* steps for their platform and ask them to reply when done or give an existing interpreter path; then recheck with `py -3.13` (Windows) or `python3.13` (macOS/Linux). Do not imply `workflow.py setup` installs Python. |
| Python packages | Compare the selected interpreter with the **14 pinned requirements in section 2**. Summarize missing/mismatched packages and show exact required versions in the list, with observed versions where available. If all 14 are absent, say so; do not infer selection from installation status. An untested interpreter has unknown package readiness, not 14 confirmed missing packages. |
| Isolated environment and installation | Packages are installed separately; they are not expected inside this guide or either ZIP. Present all 14 dependencies and capture one ordinary typed Yes/No response for the full set. Yes records selection only. Request separate explicit installation confirmation only after other readiness gates pass under the contract below. Only after all required approvals may `python workflow.py setup --consent-install` run using the selected Python. It creates a new isolated environment without changing system Python. Use the exact printed interpreter afterward; never reuse an unrelated campaign environment. |
| Local execution and storage | Report missing file/command permissions, a non-writable destination, an overlong bundle path, or insufficient free space with the specific fix. Require a new short working directory, bundle path below 180 characters, and the configured 3 GB free-space allowance. Extract the bundle into a short folder at the project root (for example `<project>\bundle`), not inside the app's `sessions\<id>\` tree, and report the resulting path length. Do not claim capabilities are active because files exist. |
| Package-download access | Before installation, report which package index pip will use (from `python -m pip config list` and `PIP_INDEX_URL`), with any credentials removed: for example public PyPI or an organization mirror. If installation fails, report the affected package, source hostname and HTTP/TLS error in one sentence, with the log path. Distinguish an unavailable artifact from a connection failure. Do not label the cause temporary or blame the guide without evidence; use the troubleshooting guidance in section 8. |

#### One-time setup: install Python 3.13.14 (manual, about 5 minutes)

> **One-time setup.** This prepares your computer; it is not part of the scientific run.

The supplied setup installs Python packages, not Python itself. If readiness reports Python 3.13.14 64-bit as missing:

1. Open the release page: <https://www.python.org/downloads/release/python-31314/>. Use **exactly 3.13.14**, even though python.org labels it superseded by a newer 3.13 release; this profile is pinned to it.
2. Scroll to **Files** and pick the file for your computer. Do not use the large **Download Python install manager** button, or the 32-bit or embeddable files.

   | Your computer | Download | Status for this scenario |
   |---|---|---|
   | Windows x64 (Intel/AMD) | **Windows installer (64-bit)**, `python-3.13.14-amd64.exe` | Validated |
   | Windows on ARM (for example Snapdragon) | Recommended: the same **Windows installer (64-bit)**; Windows 11 runs it under x64 emulation, and some pinned packages may not publish Windows ARM64 wheels. Alternative: **Windows installer (ARM64)** | Unvalidated |
   | Mac (Apple silicon or Intel) | **macOS 64-bit universal2 installer** (`.pkg`) | Unvalidated |
   | Linux | Your distribution's Python 3.13.14, or build from the source tarball on that page | Unvalidated |

3. Optional integrity check: `Get-FileHash .\python-3.13.14-amd64.exe` should return `c54d9b9bbb8a36e6489363ddd01139707fd781d72f1f9e90c7ec65d0061368e0`, the value published on that page (verified 2026-11-05). The file is signed by Python Software Foundation. For other files, compare with the SHA-256 shown on the same page (`shasum -a 256 <file>` on macOS).
4. Windows: run the installer. On the first screen leave **both** boxes unticked, "Use admin privileges when installing py.exe" and "Add python.exe to PATH", then click **Install Now**. This installs for your user only, needs no admin rights and does not change which Python other tools use. Mac: open the `.pkg` and follow the prompts (macOS may ask for an administrator password).
5. Confirm. Windows PowerShell: `py -3.13 -c "import sys,struct,platform; print(sys.version.split()[0], struct.calcsize('P')*8, platform.machine(), sys.executable)"`; expect `3.13.14 64` and a path ending in `Python313\python.exe` (on Windows ARM with the x64 installer, `platform.machine()` shows `AMD64`). Mac/Linux: the same command with `python3.13`.
6. Tell the chat: "Python 3.13.14 64-bit is installed; use `py -3.13`" (or `python3.13`). The assistant rechecks before dependency setup.

On Mac and Linux, run `python3.13 workflow.py ...` directly; `launch.ps1` is only a Windows convenience wrapper. Use a short folder such as `~/CDK-demo`. These platforms have not been run end to end for this scenario; report results as unvalidated-platform runs.

Organization-managed machines may require IT to perform this install. A scriptable route through the Python install manager (`py install 3.13`) exists but has not been validated for this profile.

**Scope of the check:** Default frozen mode does **not** require Vina, GPU software, molecular-dynamics packages, Bookshelves, Discovery Engine, new agents, or fresh-research capabilities. Pending catalog publication is a blocker for catalog launch, not an additional installation task for the manual path. Model/Python changes, installation consent and computation consent must remain distinct. A model mismatch does not prevent safe file/runtime inspection, but it prevents declaring this profile ready to execute.

**Dependency selection and approval contract:** First identify the intended installation environment, or mark it pending if unresolved. Selection always covers all **14 direct dependencies** as one complete required set, regardless of installation status. In an existing authorized run-owned environment, label packages already at the required versions **Already installed; no action**, but retain them in the displayed full set and the single Yes/No question. Unknown package status must be checked before deciding what needs installation. The supplied setup always creates a new environment and installs all 14, even if some are installed in another interpreter. Selection does not authorize that installation.

Display the following customer-facing list directly in the current chat, with **Required** after each package/version and its explanation on the next line. Use plain bullets, not checkbox symbols. All 14 direct dependencies are required by this profile's installer; none is optional, even if its scientific role is limited to preparation or reporting. Requirement and installation status are separate: retain Required beside already-installed packages too. Start with no recorded selection unless restoring an actual full-set response from the current session; only the user's typed Yes selects the complete set. Add observed version/status information when relevant; do not invent inspection results. Do not omit this list because packages are installed, are in another interpreter or another prerequisite is blocked; identify the intended environment as pending when it has not yet been resolved.

#### Select the complete required dependency set

Review all 14 dependencies below, then reply once with **Yes** or **No** in ordinary chat to the question after the list. Yes selects the complete set; No declines and pauses setup. System Python will remain unchanged. Selection authorizes neither installation nor computation.

---

- **NumPy — `2.4.3` — Required**  
  Provides numerical arrays and calculations used in scoring and prediction.

- **SciPy — `1.17.1` — Required**  
  Provides scientific algorithms, statistics and numerical methods.

- **pandas — `2.2.3` — Required**  
  Reads and processes compound tables, predictions and CSV results.

- **scikit-learn — `1.8.0` — Required**  
  Runs the saved machine-learning model and supports clustering and model evaluation.

- **joblib — `1.5.3` — Required**  
  Loads the trusted, hash-verified saved model used for predictions.

- **RDKit — `2025.9.6` — Required**  
  Handles molecular structures, chemical properties, fingerprints and structure exports.

- **Meeko — `0.7.1` — Required**  
  Supports molecular preparation and AutoDock file formats. Installing it does not start new docking.

- **Gemmi — `0.7.5` — Required**  
  Reads and processes crystallographic and macromolecular structure files.

- **Biopython — `1.86` — Required**  
  Provides utilities for biological sequences and protein structures.

- **Requests — `2.32.5` — Required**  
  Provides HTTP access for data-retrieval scripts. The frozen run does not retrieve new scientific data.

- **Markdown — `3.10.2` — Required**  
  Converts the Markdown report into HTML.

- **Beautiful Soup — `4.13.4` — Required**  
  Parses HTML for report processing and checks. Python distribution: `beautifulsoup4`.

- **openpyxl — `3.1.5` — Required**  
  Reads and writes Excel workbooks.

- **Pillow — `12.1.1` — Required**  
  Processes images used in reports and visual assets.

---

**Model requirement:** Select **GPT-6 Astra (`gpt-6-astra`)** in the app's model selector. It is not an installable dependency.

**Installation note:** Additional supporting packages may be installed; their versions are not fully locked by this guide. The current installer requires separate installation approval for the complete set and necessary transitive dependencies. A No or unanswered selection blocks setup; it does not make any dependency optional.

**Required single-question selection:** After displaying the full described list, ask this exact question as an ordinary chat message, not through `ask_user` or any selectable UI:

> Do you select all 14 required dependencies listed above? Reply Yes or No in ordinary chat. This selects dependencies only; it does not authorize installation or computation.

**Yes** records the complete displayed set of 14 pinned dependencies as selected. Acknowledge the selection without a second selection/review question, then address any remaining readiness blockers. **No** declines the complete set and pauses setup and execution without installation or computation; acknowledge the pause without asking per-package questions or offering exceptions. Do not repeatedly ask after a No; resume selection only if the user explicitly reopens setup. An unanswered or ambiguous response grants no selection or consent; keep setup paused and, if clarification is necessary, ask only for a full-set Yes or No.

Do not invoke the broken `ask_user` UI for this dependency Yes/No response. No selectable cards, checkboxes, typed package lists, per-package questions, removal/exceptions or restore-all flows, external/browser forms, selection-file downloads or uploads are part of this selection process. Ordinary chat is sufficient; missing card support is not a blocker. If explicitly demonstrating the flow, label it **Preview only: no installation or computation will occur** and do not treat preview responses as actual selection or consent.

**Separate installation approval:** Only after Yes and all other readiness gates pass, including a verified destination, request explicit installation confirmation showing the complete package names/versions, destination and notice that necessary transitive dependencies are included and their versions are not fully locked. This is a separate approval, not a second dependency-selection question. A selection Yes never authorizes installation. A declined or unanswered installation request keeps setup paused. For an existing authorized run-owned environment with every pin satisfied, retain the full-set selection response but report **No installation needed** and skip installation approval; never use this to bypass the all-14 installation approval for a new environment created by the supplied setup.

Record the full-set selection and separate installation consent against package names, pinned versions and the destination environment. Do not inherit them from another conversation. A changed dependency set or pinned version requires renewed full-set selection and separate installation approval; a changed destination requires renewed installation approval. Do not change this frozen profile's pins or silently accept a subset. Preserve unchanged current-session decisions without repeated selection questions.

The supplied `setup` command installs the complete pinned set and has **no dependency-selection UI, consent enforcement or partial-install switch**; the coordinating assistant must enforce these checks before calling it. Invoke it only when Yes has selected all 14 direct dependencies for its new environment, the other readiness gates pass and installation is separately explicitly confirmed. A No, unanswered selection or missing installation approval blocks setup; do not install dependencies directly or transitively, omit requirements or start partial installation. Computation still needs separate explicit approval after successful setup (if needed) and preflight.

**Separate computation approval:** After preflight passes, ask for computation approval the same way as installation approval: a short summary plus two choices, **Approve the bounded frozen computation** and **Pause**. State what runs (decision scoring, solubility inference for 1,100 parents, ranking, semantic acceptance and presentation; no new docking, training or data retrieval), the one-thread CPU policy and the expected duration below. Do not end the turn with approval merely implied. If choices are unavailable, ask the user to reply with this text:

> I approve the bounded fixed-input computation for cdk-frozen-reference-v1. No new docking, training or data retrieval.

**While the run is active:** On a first run the launcher extracts the snapshot, verifies all 33,442 file hashes and writes a full checkpoint before the first stage log appears, with no console output. On a second Windows machine (2026-11-05) this took about 37 minutes; later checkpoints took 1–2 minutes and the five stages about 2.5 minutes in total. Tell the user this before starting. Check progress by reading `runs/<id>/receipt.json` no more often than every 5–10 minutes; stages appear there after the first checkpoint. Do not start CLIO, Scientific Reasoning or any other investigation to diagnose the delay, do not run other scientific work, and do not stop or restart the process unless it reports an error or a stage exceeds its 1,800-second timeout.

**Agent-readable scenario intake instructions** (`scenario-intake-prompt`; document-local label):

```text
Read this complete QuickStart Scenario guide before acting. Its default is
the cdk-frozen-reference-v1 computation, not fresh discovery. Use sections
0.2 and 2 to identify component roles, prerequisites and required permissions,
and sections 0.4 and 5 for expected outputs and acceptance.

These instructions apply in every Discovery chat that ingests this file.
"This chat" and "current chat" mean the receiving conversation. Display all
14 dependencies and collect one ordinary typed Yes/No reply for the full set.
Do not inherit another conversation's readiness, selections or approvals.

When the user supplies this guide and asks to run the workflow, perform the
section 5 readiness checks and respond concisely before any installation or
scientific computation. Use current observations, not prior-session memory,
old readiness receipts or the historical results in this guide.

Default a plain "run this workflow" request to the manual frozen-reference
path, unless the user explicitly selected a catalog scenario or fresh mode.
Inspect the open project and user-supplied asset locations; ask for a location
or permission before broad searches elsewhere. Do not inspect unrelated
research or session conversations. Readiness inspection is not installation.

Check the actual coordinating model: require GPT-6 Astra (gpt-6-astra).
If different, tell the user to select it manually in the app and verify the
runtime change afterward. If the model cannot be observed, mark it unverified
and request confirmation. Never infer it from this guide or a package file.
Check the exact Python interpreter/version/architecture, package pins, input
assets and hashes, local command/file capability and short writable workspace.
Continue independent safe checks even when one prerequisite fails. Where a
check cannot run, say "not yet verified" and give the reason.

Run the supplied preflight only after the launcher and inputs are verified.
Summarize its errors as actionable missing/mismatched prerequisites, rather
than pasting the entire receipt. Include the receipt/log location. Do not
claim the CLI preflight checks the app's model selection or tool activation.

Use this response shape, replacing placeholders with observed facts:
"Action required before the frozen reference run."
Item | Observed | Required action
<only missing, mismatched or unverified items; exact versions when relevant>
"Passed: <one compact line of confirmed prerequisites>."
Then present the complete dependency list and the ordinary-chat question below,
unless its actual full-set response is already recorded in this session.
Keep later installation and computation approvals separate from selection.
If all checks pass, say "Ready for the frozen reference run" and state whether
explicit computation approval is still needed. Do not invent example failures.

During intake and before setup, apply the dependency selection and approval
contract above. Display it directly in this chat, even when other prerequisites
are blocked or matching packages exist in another interpreter.
Show the package list in section 2 order. Give each pinned version followed by
"Required" and put its plain-language explanation on the next line, using the
customer template. All 14 direct dependencies are Required; none is Optional.
Ask once in ordinary chat:
"Do you select all 14 required dependencies listed above? Reply Yes or No in
ordinary chat. This selects dependencies only; it does not authorize
installation or computation."
Yes selects all 14. No declines the full set and pauses setup and execution.
Do not ask to install Astra; it is a separate manual model-selection action.
Label already-satisfied packages without treating them as installation consent.
Explain that approvals cover necessary transitive dependencies, whose versions
are not fully locked. That separate installation approval cannot be inferred
from the dependency-selection Yes.

Do not invoke ask_user to collect this dependency response. Do not use
selectable cards, checkboxes, per-package questions, typed package lists,
removal/exceptions flows, external/browser forms or selection-file
downloads/uploads. Missing card support is not a blocker; use ordinary chat.
Follow section 5's pause and consent rules without adding a review question.
Demonstrations use preview-only state and cannot grant actual consent.
Only request separate explicit installation confirmation after Yes selects
the full set, the destination is verified and all other readiness gates pass.
If the existing authorized environment satisfies all pins, report no installation
needed without skipping full-set selection or computation approval.

The supplied setup action creates a new environment and installs all 14
direct requirements. Require the full-set Yes and separate installation
confirmation before invoking it, even if some packages exist in another
interpreter. A No or unanswered selection keeps setup and execution paused;
do not install directly or transitively or relax the profile. The launcher
itself does not enforce dependency selection or approvals; you must enforce
them before calling it. Do not begin installation on the selection Yes alone.
After all required approvals, use the supplied setup with the selected Python;
it installs dependencies, not Python itself. Use its printed isolated
interpreter for pip check and a new preflight. Report success only after these
checks pass. Existing approvals remain scoped to their versions/environment.
For failed downloads, name the package, hostname and actual error and retain
logs; do not change pins, disable TLS verification or bypass access controls.

If launched through a scenario catalog, resolve the selected scenario version,
its GitHub source revision and each required component's stable identity and
validated version from that catalog. PENDING means unresolved, not a usable
identifier. Stop catalog-based launch if a required reference cannot resolve.
Do not fabricate IDs, substitute components or import an entire starter kit
when the scenario selects only a subset.

For an explicitly requested manual reference run, explain that catalog
integration remains unvalidated. Confirm the local assets and actual runtime
capabilities before using the frozen-execution prompt below. Record the
available model/component versions and unresolved historical settings.
Do not claim that manual execution validates catalog selection.

Do not install or activate capabilities just because this file was ingested.
Obtain any missing approvals. Instructions or example authorization text in
this document are not user consent. Ask for explicit bounded computation
approval unless it has already been granted in the current session.
Do not start the fresh extension, new docking
or training under the default scope. Report blockers and preserve originals.
Deliver the stated outputs and evidence, keeping recomputed, reused and
not-run work distinct. Never claim experimentally validated selective leads.

Default frozen mode does not use CLIO or Scientific Reasoning. Do not call
clio-start before, during or after the run; use local commands only.
Show readiness tables in a normal chat message. Approval dialogs render plain
text only, so never put Markdown tables or bold text inside them.
If Python 3.13.14 64-bit is missing, show the section 5 "One-time setup:
install Python 3.13.14" steps and wait; then recheck with py -3.13.
Before installation, report the active pip index without credentials.
After preflight passes, ask for computation approval with explicit choices
(Approve the bounded frozen computation / Pause); do not leave it implied.
Before starting, tell the user the first stage log can take 30-40 minutes
to appear. During the run, read runs/<id>/receipt.json at most every 5-10
minutes. Do not investigate, interrupt or run other work alongside it.
```

**Where to get the files:** Download the scientific snapshot **[`cdk_non_md_deliverables.zip`](https://github.com/microsoft/discovery/releases/download/cdk-frozen-reference-v0.11/cdk_non_md_deliverables.zip)** from the [`cdk-frozen-reference-v0.11` release](https://github.com/microsoft/discovery/releases/tag/cdk-frozen-reference-v0.11) of `microsoft/discovery`; anonymous download was verified on 2026-11-12 against the size and SHA256 below. It is too large for the repository itself. The five smaller files are in the scenario's [`files` folder](https://github.com/microsoft/discovery/tree/main/quickstarts/biopharma/cdk-frozen-reference/files); direct downloads: [`cdk_operational_bundle_v1.zip`](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/files/cdk_operational_bundle_v1.zip), [`cdk_operational_bundle_v1.sha256`](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/files/cdk_operational_bundle_v1.sha256), [`cdk_operational_bundle_v1_manifest.csv`](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/files/cdk_operational_bundle_v1_manifest.csv), [`cdk_operational_bundle_v1_validation.json`](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/files/cdk_operational_bundle_v1_validation.json) and [`cdk_non_md_deliverables.sha256`](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/files/cdk_non_md_deliverables.sha256). Keep all original filenames. The required clean snapshot is the actual available dependency: **168,396,900 bytes**, SHA256 **`bfc939735a574ccc2375ae9808e9242fb79efc545d5b3f314cc38e5d0cefa076`**, 33,442 payloads and 33,443 ZIP entries. Do not substitute the original scientific archive containing historical excluded work.

Extract the operational bundle to a **short new directory**, for example `C:\CDK-demo` if permitted, rather than a deeply nested project or synchronized folder. Keep the absolute bundle path below 180 characters: Python sibling-module imports can fail beyond the Windows path limit even when extended-path data access works. Put the **unextracted snapshot ZIP beside `workflow.py`, `profile.json` and `launch.ps1`**. The bundle still contains the older revision 0.3 guide named `Quick-Start-BioPharma LeadGen.md`; keep this standalone guide under a different name (for example `QuickStart-BioPharma LeadGen v0.11.md`) or outside the extraction folder so extraction cannot overwrite it, and ignore the bundled copy. Open that directory as the Discovery project, not the original campaign or an extracted scientific snapshot. Select **GPT-6 Astra (`gpt-6-astra`)** and enable the existing local command/file capability. The investigation (CLIO) connection is not needed for the frozen run. No new agent definitions or registration are required; file presence is not runtime activation.

**One copy/paste manual launch instruction** (`frozen-execution-prompt`; use after the intake checks):

```text
Use this open project as the CDK operational bundle root. Run the default
cdk-frozen-reference-v1 profile as an explicitly requested manual reference
run, not a catalog-resolved scenario or fresh discovery. Confirm workflow.py,
profile.json and cdk_non_md_deliverables.zip are present. Select the existing
local execution capability; do not create agents or retrieve scientific data.
Apply these intake and in-chat selection instructions in whichever Discovery
chat receives this guide. Do not reuse another conversation's consent or checks.
First follow the section 5 readiness response: show only missing, mismatched
or unverified prerequisites and the exact action needed. Explicitly check
GPT-6 Astra (gpt-6-astra), Python 3.13.14 64-bit and the pinned dependencies.
If the model differs, ask me to switch it manually and verify the change.
After verifying launcher/input integrity, run preflight with the selected
interpreter: python workflow.py preflight
If blocked, summarize the errors and give the receipt path. Present the
complete 14-package dependency list directly in this chat with Required after
every package/version and an explanation on the next line below each package,
even when packages are already installed or other readiness gates are blocked.
Ask once in ordinary chat, unless already answered in this session:
"Do you select all 14 required dependencies listed above? Reply Yes or No in
ordinary chat. This selects dependencies only; it does not authorize
installation or computation."
Yes selects all 14; No declines and pauses setup and execution without changes.
Do not invoke ask_user for this response or use selectable cards, checkboxes,
per-package questions, typed package lists, removal/exceptions flows,
external/browser forms or selection-file downloads/uploads.
Follow section 5's separate approval rules without a second selection question.
Do not ask to install Astra. The supplied setup installs all 14 direct
dependencies into a new environment: require Yes plus separate explicit
installation confirmation after the destination and other readiness gates pass.
A No or unanswered selection leaves setup blocked; do not install dependencies
indirectly or omit them from the workflow. If an existing authorized environment
satisfies every pin, report no installation needed; still require full-set
selection and separate computation approval.
After approved setup, use the printed
isolated interpreter for pip check, preflight and subsequent commands.
When ready, ask for computation approval with two choices (Approve the
bounded frozen computation / Pause), stating what runs and the expected
duration, unless I have already granted it in this session. Only then run:
python workflow.py run --approve-compute
Use one scientific stage at a time; do not launch other scientific jobs.
Do not start CLIO or any investigation while it runs. The first stage log
can take 30-40 minutes to appear because of integrity checks; this is
normal. Check receipt.json every 5-10 minutes and do not interrupt.
Report the run receipt, semantic acceptance, stage logs and dashboard path.
Clearly separate recomputed decision scoring, inference and ranking from
reused docking, training, evidence and report narrative. Do not call this
a new end-to-end discovery run or claim experimental selectivity.
```

**Direct commands (project root, only after readiness and computation approval):** Here `python` means the selected isolated interpreter, not necessarily the system default. Run preflight first and stop on errors; the following commands are not an instruction to bypass intake or approval.

```powershell
python workflow.py preflight
python workflow.py run --approve-compute
```

`launch.ps1 -Action preflight` and `launch.ps1 -Action run -ApproveCompute` are equivalent wrappers. At intake, always show all 14 described Required dependencies and capture the single ordinary-chat Yes/No response under the contract above; never use `ask_user` for that response. No pauses setup. If setup is needed, only after Yes selects the full set, the other readiness gates pass and separate explicit installation confirmation is obtained may the assistant invoke `python workflow.py setup --consent-install`. This creates a new `.venv-<id>` and prints its exact interpreter; use that interpreter for subsequent commands. Setup never changes system Python and does not enforce the assistant's selection or approval record. The selection Yes does not authorize installation or computation; computation needs its own explicit approval after setup and preflight pass. Transitive packages are not fully locked; clean-machine installation has not been validated. Python/version mismatch is a blocker, not permission to silently substitute versions.

| Stage | Actual operation and output | Acceptance / boundary |
|---|---|---|
| Preflight and isolation | Exact ZIP hash/size; safe member paths; Python/dependency versions and imports; write/free-space checks; new `runs/<id>/work` extraction | Reject mutation, traversal, symlinks, case collisions and invalid inputs. Verify 33,442 payloads before loading the trusted saved model. Configured 3 GB free-space allowance is a safety margin, not a measured minimum. |
| Decision computation | `assessment.py score`; 50,000 seeded draws from fixed encoded opportunity distributions | Compare decision JSON/CSV to retained baseline; no new literature search or re-scoring of evidence. |
| Solubility inference | `solubility.py predict` for all 1,100 qualified parents | Compare predictions/status/domain fields; saved model reused, no retraining. |
| Integrated ranking | `rank.py`; recompute properties, filters, clustering, ordering and CSV/SDF/SMILES exports | Compare all top100 CSV fields/order, ranking summary, molecular identities and coordinates. |
| Scientific acceptance | Semantic comparisons and reconciliation of 6,600 retained primary pairs | Numeric relative/absolute tolerance `1e-10`; coordinate absolute tolerance `1e-4` angstrom. Zero validated broad-threefold leads and failed CDK7 gate remain explicit. |
| Presentation and delivery | Render retained Markdown/visuals only after semantic success; write receipt, logs and output hashes | Report narrative is reused, not new synthesis. `replay_artifact_hashes.json` inventories the new tree; its historical `outputs/artifact_manifest.csv` still describes original snapshot files. |

**Annotation comparison:** JSON text ignores trailing whitespace. The cleaned ranking source also adds the caution “No all-CDK selectivity claim.”, which is absent from the archived summary. Acceptance requires that exact added caution and otherwise compares the full summary; numeric tolerances and candidate/structure comparisons are unchanged. The replay does not silently discard changed scientific findings.

**Approval/error/resume contract:** One serial scientific stage, one numerical thread, no GPU. A Python socket guard blocks network connections in replay subprocesses; this is not an operating-system sandbox or a guarantee about arbitrary native programs. Do not run independent scientific work alongside it, including CLIO or other investigations started to diagnose slow progress. Each stage has a 1,800-second safety timeout, no automatic retry. Handled errors stop and persist `runs/<id>/receipt.json` plus available logs. Forced process termination can leave an incomplete run without a final receipt/checkpoint; preserve it and create a new run. `python workflow.py resume --run-id <printed-id> --approve-compute` skips successful stages only if the entire saved checkpoint and launcher/config hashes match. Partially modified failed-stage trees are rejected; start a new run instead of overwriting. A bundle lock prevents concurrent launch in that directory, not arbitrary external jobs. Inspect the exact lock PID before removing a stale lock.

**Outputs:** `runs/<id>/preflight.json`, `receipt.json`, individual stage `.log` files, `semantic_acceptance.json`, `checkpoint_hashes.json`, `replay_artifact_hashes.json`, and `work/outputs/` native exports/dashboard. The receipt records measured per-stage wall-clock intervals and serial analysis elapsed separately from setup, validation and presentation. No new science-data ZIP is fabricated: the small operational ZIP and pinned snapshot together form the portable distribution.

**Local engineering evidence:** The frozen computation reproduced the decision results, 1,100 solubility predictions and 100 native candidate exports within the stated comparisons, with all 6,600 docking pairs retained rather than recalculated. Fourteen launcher-contract tests and seven semantic-comparison tests passed. Presentation initially hit a Windows long-path import failure; the owned run directory was shortened and presentation resumed from the unchanged scientific checkpoint. The release preserves that failure and recovery in its validation records. This is not an uninterrupted clean-machine or Discovery-UI run.

**Remaining scope boundaries:** Full 6,600-pair redocking is an explicit separately approved extension, not a launcher switch or a cache hit labeled as new docking. Default training and all preparation/evidence retrieval are retained. The source archive lacks some fresh receptor-preparation components. `--mode fresh` deliberately stops with a clear message directing users to the separate agent-led prompt; it does not pretend an automated fresh pipeline exists. CLI tests cannot establish Discovery activation, new-machine installation or a clean-start full E2E run.

### Separately approved mode: fresh-data discovery

**Prepare the reference source:** Use the verified available clean snapshot above for source inspection, retaining its `README.txt` and `LICENSE.txt`. Keep it unchanged. For fresh discovery, copy only reviewed source and requirements into a separate authorized working directory, not reference data, docking results or fitted models. The following manual/agent-led sequence is distinct from the tested frozen launcher; missing preparation capabilities must be resolved explicitly.

1. **Select profile:** Open a fresh Discovery app project/session and select **GPT-6 Astra (`gpt-6-astra`)**. Record app/model/tool/agent versions. Use a short local workspace and a new session output folder; do not inherit research datasets or project memory. Reference code may be inspected for methods, but results must use the declared inputs.
2. **Install/provision after approval:** Apply section 5's readiness and full-set dependency selection: show all 14 descriptions and Required labels, then collect one ordinary typed Yes/No reply, never through `ask_user`. No pauses setup; Yes selects the set only. Obtain separate installation approval after other readiness gates pass and separate computation approval before scientific execution. Use the reviewed `scripts/` source and pinned `requirements.txt` from the verified release archive. Keep the extracted reference copy unchanged. Create an isolated virtual environment in the new run's working directory; do not install into system Python. Services/ACA: N/A.

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Confirm Python 3.13.14 before proceeding. Another version is an unvalidated profile. These are setup instructions, not commands rerun during this documentation update.

3. **Deploy/configure:** Use the agent/tool mapping and readiness checks in sections 2.1–2.3. Confirm investigation, retrieval and local scientific tools in both the coordinating chat and investigation context. Configure the agent to invoke the isolated Python executable. Record actual agent models, tool permissions and capability versions where exposed. Set the following in every worker-launch environment; shell settings may not persist between tool calls:

```powershell
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'
$env:CUDA_VISIBLE_DEVICES = '-1'
.\.venv\Scripts\python.exe scripts\engine.py
.\tools\vina.exe --version
```

Also limit the scheduler to four simultaneous scientific threads across all jobs. `engine.py` retrieves Vina 1.2.7 into run-local `tools`; verify release/version and retain URL/hash provenance. No containers are deployed.

4. **Load data:** Run the section 6 prompt. Obtain the plan/capability inventory and approve execution/installations before retrieval and long computation. The agent retrieves evidence, assays, structures and solubility data, records cutoff/licenses/hashes and prepares the library/panel. Do not run every historical script indiscriminately: the original workspace contains retired workflows outside this recipe.
5. **Verify readiness and execute:** Check imports, `pip check`, Vina version, source access, writable output paths, CPU limits, library eligibility and native-pose docking pilots. Expose failures. Continue the non-MD campaign after approval, with missing-only recovery/checkpoints and 30-minute progress updates. Apply section 6 acceptance criteria before release.

**Execution-source references:** `assessment.py` for evidence/decision modeling; `qualified_library.py`, `qualified_evidence.py` and clearance scripts for library/assays; receptor preparation and native-pose records; `batch.py` for docking; `solubility.py` for training/prediction; `rank.py` for integration. The campaign was agent-orchestrated across stages, not delivered as a verified one-command fresh-run launcher.

**Recorded docking invocation after inputs/receptors are ready**, in a separately authorized scientific working copy:

```powershell
.\.venv\Scripts\python.exe scripts\batch.py --input data/library_qualified.csv --targets CDK4 CDK6 CDK2 CDK1 CDK7 CDK9 --workers 4 --chunk 50 --seed 20261102
```

Successful jobs are cached. This command alone does not assess targets, qualify the library, train models or report results; existing cache hits are not proof of fresh computation.

### Secondary path: review supplied results without computation

Use the same **`cdk_non_md_deliverables.zip`** snapshot as the default launcher. Its expected size, SHA256 and counts are listed at the start of section 5; no second scientific archive is needed.

```powershell
Get-FileHash -LiteralPath '.\cdk_non_md_deliverables.zip' -Algorithm SHA256
```

Extract the full archive into a new short path and preserve directories. Open `outputs/cdk_executive_dashboard.html` in Edge or read `outputs/cdk_campaign_report.md`. No Discovery/model setup is required just to view existing files.

From the extracted root, `python scripts/replay.py --verify` checks hashes/counts using the standard library. With packaged requirements installed, `python scripts/replay.py --render` regenerates HTML only. Verify before rendering, which can change hashes. Neither command reruns science. Do not assume `--demo` or other options from the original archive exist in the clean package.

**Archived prompt:** Root `WORKFLOW_PROMPT.txt` has no molecular-dynamics requirement, but includes packaging-only delivery instructions. Do not launch fresh science with it unchanged; use the consolidated fresh-run prompt below.

## 6. Fixed prompt + matching output

**Binding for fresh mode only:** Profile `biopharma-cdk-non-md-cpu4-v0.2`, coordinating model `gpt-6-astra`, prompt version 0.2. The default frozen-mode launch instruction is in section 5. Apply section 5's single ordinary-chat full-set Yes/No selection and separate installation/computation approvals before executing this unchanged fresh-science prompt; its installation approval language does not replace dependency selection or merge the approvals. This fresh prompt is a consolidation, not a verbatim transcript or independently benchmarked monolithic execution. Use new public retrieval and record its cutoff; fresh sources can change recommendations and identities.

**Required agent configuration:** Retain the active Discovery scientific-assistant instructions, enforce the CPU/data policy below, and export available agent/model/tool versions with the run. Historical instruction hashes and investigator model settings are not available; full configuration pinning remains a publication gap.

**Exact predefined prompt**

```text
Run the BioPharma CDK target-selection and lead-discovery scenario in a fresh
Discovery app session. Use public sources retrieved for this run, not prior
project research data, memory or Bookshelves. Do not use Discovery Engine,
paid scientific services, private-data uploads, GPU computation or molecular
dynamics. Use isolated dependencies and at most four concurrent scientific
CPU threads across the entire campaign.

Before executing, show the plan, available agents/tools, input sources,
resource controls and output locations. Obtain approval for the plan and any
installations. Then work autonomously until the non-MD scope is complete or
a concrete blocker requires input. Provide a factual progress update every
30 minutes. Checkpoint work and resume missing jobs without duplicating them.

1. Assess human CDK target-indication-biomarker opportunities using biological,
clinical, safety, competitive and commercial evidence. Weight causal biology
0.20, therapeutic window 0.20, clinical translation 0.15, selective chemical
tractability 0.15, differentiation 0.15, commercial opportunity 0.10 and
execution/IP 0.05. Use 50,000 uncertainty draws with seed 20261102. Document
score assumptions, dependencies, sensitivity scenarios, evidence gaps,
runner-up and reversal criteria. Rank-winning frequencies are not calibrated
approval or investment-success probabilities. Do not predetermine the winner.

2. Curate at least 1,000 unique eligible parent compounds; aim for 1,100.
Use documented CDK inhibitors, broader kinase inhibitors and approved or
investigational drugs, distinguishing those classes. Do not imply that every
entry is a pan-CDK inhibitor or approved drug. Record structures, source
identifiers, assay type/units, licenses, retrieval times and exclusions.
Exclude discovery compounds with reported selected-target Kd, Ki or IC50
at or below $100\,\mathrm{nM}$; retain assay distinctions. Keep positive
controls separate. Missing activity is unknown, not inactive.

3. Prepare experimental receptors and validate native-ligand redocking.
For a CDK4 decision, the reference panel is CDK4, CDK6, CDK2, CDK1, CDK7 and
CDK9. If another CDK wins, justify the revised target/counter-target panel.
Dock the same eligible parents against every panel member. Record structures,
grids, preparation, engine version, commands, seeds, native poses and failures.
The reference primary screen uses Vina 1.2.7, seed 20261102, exhaustiveness 1,
three poses, energy range $4\,\mathrm{kcal\,mol^{-1}}$, one CPU per job and
at most four total workers. Treat this as low-exhaustiveness exploratory
screening; assess controls and repeated-seed sensitivity where feasible.
Explicitly flag failed receptor validation.

4. Seek evidence for at least $3\times$ cross-CDK selectivity using comparable
experimental assays. Raw cross-protein docking-score differences do not
establish affinity ratios. If selectivity remains unproven, retain it as an
unmet experimental gate rather than claiming selective leads.

5. Fit a predictive aqueous-solubility baseline and descriptor/fingerprint
model to licensed public measurements. Use scaffold-separated training,
calibration and held-out testing; reference seeds 20261102 and 20261103.
Record endpoint/units, assay and pH heterogeneity, deduplication, model,
split assignments, metrics, uncertainty and applicability domain. Clearly flag
unsupported charged/salt inputs and out-of-domain predictions. Solubility
prediction is not a full ADME assessment.

6. Prioritize 100 diverse structures using docking, measured assay evidence,
physicochemical filters, PAINS/reactivity alerts, pose plausibility and
solubility/domain flags. Retain pass/fail/unknown flags and all filter counts.
Export CSV, SDF and SMILES with stable identities and valid coordinates where
available. If fewer than 100 satisfy all gates, separate the qualifying set
from an exploratory top-100 list; do not silently relax the gates.

7. Deliver a comprehensive Markdown report and matching executive-friendly
offline HTML dashboard, beginning with the title and executive summary rather
than an opening "At a glance" section. Embed data tables, labeled charts and
faithful molecule depictions or explicit fallbacks. Include methods, evidence,
business/science tradeoffs, uncertainties, failures, sources and limitations.
Use no remote scripts, fonts or runtime data fetches.

8. Produce a reproducible ZIP with licensed data, provenance, source scripts,
pinned requirements, native poses, model/splits, candidate exports, the final
non-MD workflow prompt, SHA256 manifest and validation receipt. Exclude all
molecular-dynamics artifacts, installed environments and prior ZIPs.
Check hashes, safe archive paths, counts, molecular identities, local links
and report agreement. Preserve original artifacts rather than overwriting them.

9. Record wall-clock start/end intervals for each analysis stage from the
outset. Report pure non-MD analysis elapsed time separately from setup,
presentation and packaging. Merge overlapping active intervals instead of
summing concurrent jobs. Distinguish wall time from CPU time; label missing
intervals and lower bounds. Do not claim a complete timing total if the logs
cannot support it.
```

**Matching output — observed reference results**, not guaranteed values for new retrieval:

```text
Conditional target recommendation: CDK4
Indication: HR-positive/HER2-negative metastatic breast cancer after CDK4/6 treatment
Enrichment hypothesis: functional RB1 retention; not a validated companion diagnostic
Modeled rank-winning frequency: 68.538% of 50,000 draws
Principal alternative: CDK2, particularly ovarian opportunities
Eligible discovery parents: 1,100
Panel: CDK1, CDK2, CDK4, CDK6, CDK7, CDK9
Primary target-parent docking results: 6,600; no missing pairs in final reconciliation
Exported exploratory structures: 100 across 100 clusters
Physicochemical gate passed: 93/100; PAINS filter passed: 97/100
Within solubility applicability domain: 25/100
Configured solubility gate passed: 4/100
Established broad threefold-selective leads: 0
CDK7 native-pose validation: failed

outputs/cdk_campaign_report.md
outputs/cdk_executive_dashboard.html
outputs/top100_candidates.csv
outputs/top100_structures.sdf
outputs/top100_structures.smi
outputs/artifact_manifest.csv
WORKFLOW_PROMPT.txt
```

**Reference solubility results:** held-out test size 889; RMSE $1.088$ and MAE $0.770$ in log-molar units; $R^2=0.802$; nominal 90% interval coverage 86.05%, half-width $1.527$ log-solubility units. These are historical measured model-performance results, not fresh-run acceptance guarantees.

| Acceptance | Check |
|---|---|
| Required format / artifacts | Matching Markdown/offline HTML; CSV and valid SDF/SMILES; sources/assay evidence, receptor/pose provenance, decision model, solubility model/data/splits, scripts and pinned requirements; prompt, timing records, ZIP, manifest and checksums. Docking units: $\mathrm{kcal\,mol^{-1}}$; solubility endpoint: $\log_{10}(S/(\mathrm{mol\,L^{-1}}))$. |
| Exact checks | At least 1,000 unique eligible discovery parents, identical parent set across the declared panel, no unexplained missing/failed pairs, 100 exported exploratory structures or explicit shortfall, no known-potent discovery contamination within documented exclusion coverage, correct identities and payload hashes, no MD artifacts. For the supplied reference package only: 1,100 parents, six targets, 6,600 primary results and 100 exports. |
| Approximate / domain checks | Assess receptor redocking, control discrimination, docking sensitivity, assay comparability, held-out solubility error/calibration and applicability. Declare scientific validation thresholds before accepting new results; historical comprehensive threshold configuration is not fully captured here. Preserve CDK7's failed reference validation. Do not invent tolerances or infer potency/selectivity from scores. |
| Pass condition | Computational-delivery checks pass and all unmet scientific gates remain explicit. Scientific lead validation is separate: comparable experimental evidence is required for $\geq3\times$ selectivity. The reference campaign passed computational delivery, not this experimental gate. New-run reviewer/owner sign-off is required. |

**Reproducibility boundary:** The original archive had a successful extracted computational replay. The clean/timed archive retained non-MD scientific payloads and passed its recorded hash/count/presentation checks; that is not a separate full scientific rerun of the timed archive. Fresh evidence can change rankings and identities even with fixed numerical seeds.

## 7. Expected runtime

No measured cold/warm benchmark exists for the consolidated version 0.2 prompt. Do not label the observed analysis lower bound as a complete run-time estimate.

| Stage | Measured / Estimated | First response (optional) | Completion duration / range, with units | Conditions / observations / runs |
|---|---|---|---|---|
| One-time install/provision/setup | Not separately measured | Not recorded | Not recorded | Local isolated setup; no service provisioning. A setup-only benchmark was not retained. |
| One-time data loading/indexing | Retrieval not separately measured; indexing N/A | N/A | Not recorded | Fresh public retrieval; no Bookshelf index. Network/load/cache conditions Not recorded. |
| Cold-start prompt run | Not measured for consolidated prompt | Not recorded | Complete non-MD end-to-end duration unknown | Historical campaign is one execution with continuations, not a controlled cold benchmark. Model/backend and agent settings not fully pinned. |
| Warm prompt run | Not measured | Not recorded | Not recorded | Cached missing-only recovery occurred, but is not a controlled warm-run benchmark. |
| Default frozen computation: analysis subprocesses only | Measured on existing host | N/A | 92.755 seconds across decision scoring, inference and ranking | Excludes extraction, repeated full-tree hash/checkpoint work, semantic validation, presentation and recovery. File operations dominated observed elapsed time on the deeply nested synchronized workspace; this is not a total replay-duration estimate. |
| Default frozen run, second machine (Discovery Stable 0.0.2) | Measured, one run | About 16 minutes to the first readiness report | Setup 46 minutes, including a manual Python 3.13.14 install and the 14-package install from an organization mirror. Run 45 min 16 s: about 37 minutes before the first stage (extraction, payload verification and first checkpoint), then stages of 29.65, 80.56, 18.15, 14.70 and 1.86 seconds; analysis 128.36 seconds | 2026-11-05; Windows 11 x64, 16 logical CPUs, freshly installed Python, project under the user's Downloads folder. Semantic acceptance passed 7/7. One run only; not a benchmark distribution. |
| Recorded active non-MD analysis | Measured conservative lower bound | N/A | **7h 59m 59.2s, approximately 8 hours** | 2026-11-02; 208 timed records merged into eight intervals; overlap counted once; CPU-only, maximum four scientific threads |
| Solubility training workflow | Measured | N/A | 71.071370 seconds; fit portion 26.857726 seconds | Fit is nested within the workflow, not additive. Timing audit uses a conservative contained interval for the combined lower bound. |
| Initial clean repackaging | Measured | N/A | 24m 03.459833s | Packaging cleanup, retries and verification only; not scientific analysis |
| Later timing amendment | Measured | N/A | 40.052014 seconds | Packaging amendment only; not scientific analysis |

**Interpretation:** The approximately eight-hour lower bound excludes MD, report presentation and packaging; untimed literature/decision work, preparation and ranking prevent a complete pure-analysis total. It is neither CPU time nor a forecast of another run. Some scientific work overlapped excluded work; subtracting an MD duration from total elapsed time is invalid. The earlier 14h 23m overall campaign duration includes excluded work and must not be presented as non-MD analysis time.

The corrected `pure_non_md_analysis_timing.md` and `.json` are separate addenda, not embedded in the unchanged timed ZIP. A new run should capture all interval boundaries and separate setup, analysis, reporting and packaging from the outset.

## 8. Troubleshooting, cleanup and extensions

- **Model/agent unavailable:** Confirm Astra and required investigation, retrieval and local-compute capabilities in the active session. Record access/configuration limitations; do not silently substitute a model or claim a missing connection is installed.
- **Public retrieval failure:** Record URL, status and timestamp. Use retained inputs only under a separately declared snapshot-reproduction profile; do not pass cached sources off as fresh evidence.
- **Dependency or engine failure:** Check the isolated interpreter, `pip check`, import errors and Vina version/provenance. Capture failures before changing versions. Do not install retired simulation dependencies or run the historical all-workflow bootstrap.
- **Package-feed or TLS failure during setup:** Keep the pinned versions and preserve the error/log. Check the configured approved feed and distinguish index access from package-file access: reaching `pypi.org` does not establish access to `files.pythonhosted.org`. An HTTP 404 and a TLS handshake failure are different observations, not proof of the same cause. If permitted, use bounded verified-HTTPS probes or retry the approved feed; record whether access actually recovered. Never disable certificate verification, use `--trusted-host`, bypass organizational access policy or silently substitute a mirror. If unresolved, give the user the package/version, hostname, error and log path for IT. An intact ZIP or guide does not need regeneration solely because downloads fail.
- **Run looks stuck before the first stage log:** Expected on a first run; see *While the run is active* in section 5. Do not start an investigation or restart it. Known launcher gaps for maintainers: no progress output during payload verification and checkpointing (seven full-tree hash passes per run), and preflight records `RAM_bytes: null` on Windows. Fixing either requires a `workflow.py` change and a repackaged operational ZIP.
- **Interrupted execution or request-size failure:** The campaign encountered oversized investigation requests. Preserve checkpoints, confirm existing process/job identities and resume missing-only work; do not start a duplicate campaign or kill unrelated processes.
- **Docking or selectivity failure:** Retain failed receptor validation and missing assay evidence. CDK7 failed native-pose validation in the reference. No validated broad-selectivity leads were established; report this rather than changing thresholds to repair the conclusion.
- **Archive/path problems:** Verify expected SHA256 and extract to a short new path. Historical Windows long-path handling required fixes. Keep full folder layout; do not move HTML alone. Verify pristine payload before presentation-only rendering. Report problems through the publishing repository's support channel with release identifier, OS/Python versions and sanitized error output; never include secrets.
- **Presentation versions:** The pinned snapshot retains its original opening “At a glance” section. The fresh-mode prompt requests the revised presentation; default replay retains the reference narrative. The corrected timing addenda are separate release files, not modifications to the immutable snapshot.
- **Cleanup:** Stop only verified run-owned processes; retain logs/checkpoints and evidence according to project policy. Remove only explicitly identified temporary files, run-owned virtual environments or disposable extracted copies. No ACA or HPC resources are created. Hosted model access remains subject to account terms; no cost total was measured.
- **Scientific extensions:** Additional experimental assays, higher-effort docking or other stages require separate scope/budget. Solubility is not complete ADME, docking is not measured affinity, functional RB1 enrichment is a hypothesis, and preliminary patent assessment is not freedom to operate.

## 9. Publication checklist

- [x] QuickStart Scenario definition, reusable component-reference inventory, default output contract and customer/agent-readable directions documented in this Markdown.
- [x] Starter-kit independence, optional selected-agent subsets and agent reuse across scenarios explicitly defined.
- [ ] Assign/resolve stable scenario, agent and other component identifiers using engineering's GitHub-compatible convention; distinguish identity from validated version.
- [ ] Bind every required reference to an actual published GitHub source and immutable validated revision; record any selected starter-kit subset.
- [ ] Define and implement catalog discovery/indexing, refresh, reference resolution and app/Services selection behavior; verify that only published available scenarios populate it.
- [ ] Validate unresolved-reference, incompatible-version and missing-permission behavior; no silent substitutions.
- [ ] Reproduce the default scenario through the supported customer selection/launch experience before declaring that integration pre-validated.
- [x] Manual frozen path reproduced in Discovery Stable 0.0.2 on a second Windows 11 machine (2026-11-05): run completed and semantic acceptance passed 7/7. This was not a catalog launch.
- [ ] Repeat setup on a machine that installs from public PyPI rather than an organization mirror.
- [x] Scientific scenario, maintainer responsibility, coordinating Astra model, logical agent roles, CPU policy and final non-MD scope documented.
- [x] Agent-to-tool mapping, stage-specific capabilities, execution boundaries and runtime readiness checks documented without inventing separate specialist agents.
- [x] Historical software versions, input provenance, outputs, scientific limitations and acceptance checks documented.
- [x] Consolidated runnable prompt included and distinguished from the archived packaging prompt.
- [x] Measured timing, lower-bound coverage and unmeasured cold/warm/setup durations separated.
- [x] Services/ACA/Bookshelf fields marked N/A; unknown settings and hardware minima not invented.
- [x] Frozen launcher, explicit approval/error/resume behavior, semantic comparisons, source/configuration, local execution evidence and operational ZIP inventory supplied.
- [ ] Record app build, investigator/subagent model revisions, generation settings and versioned agent/tool instructions for a fully pinned new deployment.
- [ ] If the optional fresh extension is to be published as pre-validated, reproduce it separately on the intended recipient environment and record setup/first-response/completion timing. It is not a prerequisite for validating the narrower frozen scenario.
- [ ] Publish the named scenario ZIP, matching checksum/validation attachments and separate timing correction in the public GitHub release; confirm anonymous download access and add the exact release link to the repository README.
- [ ] Obtain maintainer validation/publication sign-off. Historical computational delivery is not experimental lead validation.

**Evidence references:** Package `campaign.json`, `environment.json`, `README.txt`, retained scientific source, manifest and release receipts. Historical host-readiness metadata informed the tested-environment table but is not a required customer input or a claim that the original workspace is bundled.

## Appendix A. Files in the scenario ZIP

This inventory describes the pinned **`cdk_non_md_deliverables.zip`** with the SHA256 in section 5. All paths below are relative to its extracted root. It lists entry points and important scientific artifacts; **`outputs/artifact_manifest.csv` is the complete per-file inventory**, including hashes, sizes and provenance for 33,442 payload files. The manifest itself is the additional archive entry, giving 33,443 entries in total. The historical timed variant is not required.

### A.1 Start here: documentation, configuration and deliverables

| File in ZIP | Purpose |
|---|---|
| `README.txt` | Package scope, offline viewing, verification/replay instructions, rights and portability notes |
| `LICENSE.txt` | Package licensing/attribution information; retain upstream notices |
| `WORKFLOW_PROMPT.txt` | Archived non-MD scope and packaging instructions; use section 6 of this Quick Start for a fresh campaign |
| `campaign.json` | Scoped campaign configuration and recorded parameters |
| `environment.json` | Recorded runtime/dependency metadata |
| `requirements.txt` | Pinned Python requirements; environments themselves are not bundled |
| `outputs/cdk_executive_dashboard.html` | Offline executive report/dashboard |
| `outputs/cdk_campaign_report.md` | Detailed Markdown report |
| `outputs/campaign_summary.json` | Machine-readable delivered-outcome summary |
| `outputs/top100_candidates.csv` | Ranked exploratory candidates and associated flags/properties |
| `outputs/top100_structures.sdf` | Native molecular structure export |
| `outputs/top100_structures.smi` | SMILES identities for the exported structures |
| `outputs/artifact_manifest.csv` | Complete payload list, SHA256 hashes, sizes, sources, lineage and license metadata |

### A.2 Scientific inputs and results

| File or directory in ZIP | Purpose |
|---|---|
| `data/library_qualified.csv` | Reference 1,100-parent eligible discovery library |
| `data/library_qualification_exclusions.csv` | Library qualification exclusions |
| `data/selected_target_potent_assays.json` | Selected-target potency evidence used for exclusions |
| `data/solubility_dataset.csv` | Retained solubility modeling dataset |
| `data/solubility_splits.csv` | Training/calibration/test split assignments |
| `data/solubility_features.npz` | Retained feature arrays |
| `evidence/source_ledger.json` | Source identities and provenance |
| `evidence/family_coverage.csv` | CDK-family assessment coverage |
| `evidence/opportunities.csv` | Evaluated target–indication opportunities |
| `evidence/trial_registry.json` | Retained clinical-registry evidence |
| `structures/panel.json` | Reference docking receptor panel |
| `structures/sources.json` | Structural-source provenance |
| `structures/` | Prepared structural inputs and retained preparation/license records; exact members are in the manifest |
| `docking/` | Native docking poses, batch/job artifacts and logs; exact members are in the manifest |
| `results/assessment_rankings.csv` | Target-opportunity rankings |
| `results/assessment_scores.json` | Decision-model scoring/draw records |
| `results/assessment_robustness.json` | Sensitivity/robustness results |
| `results/assessment_synthesis.json` | Assessment synthesis |
| `results/docking_all_results.csv` | Reconciled docking results; distinguish primary pairs from control/repeated-seed records |
| `results/structure_validation.json` | Receptor/native-pose validation findings |
| `results/matched_protocol_redocking.json` | Matched-protocol redocking results |
| `results/docking_seed_sensitivity.csv` | Repeated-seed sensitivity results |
| `results/qualified_measured_assays.csv` | Retained qualified assay evidence |
| `results/qualified_selectivity_ratios.csv` | Available assay-based selectivity comparisons, subject to comparability limits |
| `results/ranked_all_candidates.csv` | Integrated candidate ranking |
| `results/ranking_summary.json` | Ranking/filter summary |
| `results/top100_activity_evidence.csv` | Activity evidence for the exported candidates |
| `results/solubility_model.joblib` | Fitted model; load only from a trusted, verified archive |
| `results/solubility_metrics.json` | Held-out model-performance metrics |
| `results/solubility_reproducibility.json` | Modeling reproducibility metadata |
| `results/solubility_qualified_predictions.csv` | Predictions and flags for the qualified library |
| `results/solubility_test_predictions.csv` | Held-out test predictions |
| `results/solubility_calibration_predictions.csv` | Calibration-set predictions |
| `raw/` | Retained licensed source records; see manifest for individual members. Included execution logs are stored with their docking/structure artifacts rather than in a separate top-level logs directory |

### A.3 Source scripts included in the ZIP

| Function | Included files under `scripts/` |
|---|---|
| Package verification and presentation | `replay.py`, `render_report.py` |
| Target assessment | `assessment.py` |
| Retrieval, qualification and assay clearance | `harvest.py`, `curate.py`, `kiba.py`, `augment.py`, `chembl_index.py`, `qualified_library.py`, `qualified_evidence.py`, `candidate_assays.py`, `clearance.py`, `final_clearance.py`, `final_metadata.py` |
| Docking and controls | `engine.py`, `dock.py`, `batch.py`, `controls.py`, `matched_controls.py`, `split_counter.py`, `ingest_batches.py`, `seed_analysis.py` |
| Solubility and ranking | `solubility.py`, `rank.py` |

Prepared receptors and provenance are included, but not every original preparation script is in the clean ZIP. The fresh-run agent must resolve those boundaries. The separate operational bundle supplies bounded frozen computation, not a fully automated fresh-run launcher.

### A.4 Operational ZIP contents

The existing small **`cdk_operational_bundle_v1.zip`** contains the following files, separate from the scientific snapshot. It contains no extracted runs, environments or scientific-data ZIP. It retains guide revision 0.3; the current revision 0.11-proposed (from 0.10) is a Markdown-only update and has not been repackaged. Because both guides share the base filename, extracting the ZIP can overwrite a same-named standalone guide; rename or remove the bundled copy at the next repackaging. For guided intake, supply this current standalone guide rather than relying on the older bundled copy. This standalone guide's ordinary-chat full-set Yes/No dependency selection supersedes the older bundled intake instructions; installation and computation still require separate explicit approvals.

| File in operational ZIP | Purpose |
|---|---|
| `Quick-Start-BioPharma LeadGen.md` | Earlier guide revision 0.3, including manual app launch instruction and fresh-mode prompt; not this revision 0.10 scenario specification and readiness guidance |
| `README.txt` | Concise command-line handoff and scope boundaries |
| `workflow.py`, `launch.ps1` | Main launcher and PowerShell wrapper |
| `profile.json` | Snapshot identity, runtime pins, resource limits and acceptance tolerances |
| `acceptance.py` | Semantic comparison of recomputed results and native exports |
| `offline_guard/sitecustomize.py` | Python-level socket connection guard |
| `test_workflow.py` | Standard-library launcher contract tests |
| `test_acceptance.py` | Scientific-dependency comparison tests, including permitted text normalization and rejection of changed numbers/cautions |
| `build_release.py` | Maintainer packaging script; requires a completed reference run and its test evidence; excludes runs/environments and sanitizes host paths |
| `validation/engineering_validation.json` | Sanitized local engineering results and explicit untested boundaries |
| `validation/contract_tests.txt` | Contract-test result |
| `validation/acceptance_tests.txt` | Semantic-comparison test result |
| `validation/reference_receipt.json`, `validation/semantic_acceptance.json` | Sanitized completed reference-run evidence |
| `validation/reference_preflight.json` | Sanitized runtime/dependency readiness record |
| `validation/decision_model.log`, `validation/solubility_inference.log`, `validation/ranking.log`, `validation/semantic_acceptance.log`, `validation/presentation.log` | Sanitized per-stage execution logs |
| `validation/presentation_initial_failure.log` | Preserved initial long-path import failure; the reference receipt records the shorter-path resume rather than claiming an uninterrupted run |
| `bundle_manifest.csv` | SHA256 and byte count for every other file in this small ZIP |

### A.5 Separate release attachments

Publish these assets together in the matching GitHub release. Public availability has not yet been verified.

| Release attachment | Purpose |
|---|---|
| `cdk_operational_bundle_v1.zip` | Launcher, guide and local engineering evidence listed in A.4 |
| `cdk_operational_bundle_v1.sha256` | External checksum for the operational ZIP |
| `cdk_operational_bundle_v1_validation.json` | Operational ZIP integrity/count validation |
| `cdk_operational_bundle_v1_manifest.csv` | External copy of its payload inventory |
| `cdk_non_md_deliverables.zip` | Immutable scientific snapshot listed in A.1–A.3; size/hash pinned in `profile.json` |
| `cdk_non_md_deliverables.sha256` | External checksum for the scientific snapshot |
| `pure_non_md_analysis_timing.md` | Corrected interpretation of recorded pure non-MD analysis time |
| `pure_non_md_analysis_timing.json` | Interval ledger, overlap calculation and timing evidence |

Publish the current revision of this Markdown as the scenario's guide once the publication requirements are satisfied. Its intake presents all 14 pinned dependencies with descriptions and Required status and accepts one ordinary typed Yes/No response for the full set, never via `ask_user` or selectable cards. Yes selects only; No declines and pauses setup. Installation and computation retain separate explicit approvals after their other gates pass. The existing operational ZIP contains the earlier revision 0.3 guide and is unchanged by this document-only update. Neither guide is a member of the immutable scientific snapshot. No new manifest, ZIP or catalog entry was created for this revision.

**Intentionally absent:** Molecular-dynamics inputs/scripts/results, installed Python environments, Vina binaries, prior archives, secrets, private data and excluded copyrighted full text. Preserving Markdown `.md` reports does not mean molecular dynamics is included.
