# Microsoft Discovery partner ecosystem

<!--
Maintainers: update this page when a partner agent is added, merged, or removed.
Logos are each partner's official GitHub organization avatar.
-->

Scientific progress depends on bringing the right knowledge, models, and computing together at the right moment. Microsoft Discovery partners contribute specialized scientific content, predictive models, and simulation services as catalog agents, so research teams can combine them with Discovery's agentic orchestration, reasoning, knowledge foundation, and high-performance computing in a single workflow.

This page lists every partner agent, what it does, and its setup requirements.

**Contents**

- [How partner agents work](#how-partner-agents-work)
- [Partner agents](#partner-agents)
- [Built on partner and open-science platforms](#built-on-partner-and-open-science-platforms)
- [Pending review](#pending-review)
- [Become a partner](#become-a-partner)

## How partner agents work

- **One catalog.** Partner agents are published through the same PR-reviewed, schema-validated [Discovery Catalog](../agents/) as Microsoft's own agents.
- **What every agent needs.** A Microsoft Discovery project with a chat model deployment. The Setup requirements column lists anything else an agent needs.
- **Your credentials stay in your project.** Agents that call a partner's hosted service use a connection that you configure in your own project. API keys and sign-in grants are never stored in the catalog.
- **Partner terms apply.** Each partner's service is governed by that partner's own terms. Each agent's `README.md` covers setup and known limitations.

| Setup requirements | What it means |
| --- | --- |
| 🔑 API key | Get a key or token from the partner, then add it to your project as the agent's `README.md` describes. |
| 👤 Sign-in | Each user signs in with their own account (OAuth) the first time the agent calls the partner's service. |
| 🐳 Container image | Build the agent's tool image and publish it to your container registry, as the agent's `README.md` describes. |
| 🔓 None | No account or key is needed. |

| Status | What it means |
| --- | --- |
| ✅ Available | In the catalog today. |
| ⚠️ Limited | In the catalog, with a platform limitation described in the agent's `README.md`. |
| 🕓 Pending review | Submitted by the partner and under review; not yet in the catalog. |

## Partner agents

Agents contributed and maintained by partners.

| Agent | What it does | Setup requirements | Status |
| --- | --- | --- | --- |
| <a href="../agents/wiley-nexus/"><img src="https://avatars.githubusercontent.com/u/37445193?s=96" width="48" height="48" alt="Wiley logo"></a><br>**[Wiley Nexus](../agents/wiley-nexus/)**<br>Wiley | Answers scientific and technical questions from Wiley's peer-reviewed scholarly corpus. It surveys the published evidence, reads key publications in full, and returns a citation-backed synthesis linked to Wiley Online Library. | 🔑 Wiley Nexus API key | ✅ Available |
| <a href="../agents/synthesize-bio/"><img src="https://avatars.githubusercontent.com/u/145417789?s=96" width="48" height="48" alt="Synthesize Bio logo"></a><br>**[Synthesize Bio](../agents/synthesize-bio/)**<br>Synthesize Bio | Generates realistic human gene-expression profiles from a plain-language experiment description, such as "tumor vs. normal lung tissue", using its Gene Expression Model (GEM), then runs differential expression analysis. Supports bulk and single-cell RNA-seq. | 🔑 Synthesize Bio account and API key | ✅ Available |
| <a href="../agents/scigantic-catalog/"><img src="https://avatars.githubusercontent.com/u/301751622?s=96" width="48" height="48" alt="Scigantic logo"></a><br>**[Scigantic Catalog](../agents/scigantic-catalog/)**<br>Scigantic | Finds public scientific datasets across several thousand curated open archives and explains their structure, including format, columns, and sample rows, before you download anything. Returns a ready-to-use loader and links arXiv papers to their datasets. | 🔓 None | ✅ Available |
| 🧑‍🔬<br>**[Flow Cytometry Referee](../agents/flow-cytometry-referee/)**<br>Aziz Muminov, independent contributor | Reviews flow-cytometry (FCS) data and proposed gating plans for technical quality, compensation evidence, control coverage, and reproducibility, and produces an evidence-backed QC report. | 🐳 Container image | ✅ Available |
| <a href="../agents/aqcat/"><img src="https://avatars.githubusercontent.com/u/96544495?s=96" width="48" height="48" alt="SandboxAQ logo"></a><br>**[AQCat](../agents/aqcat/)**<br>SandboxAQ | Computational catalysis: calculates adsorption and binding energies and surface reactivity, and ranks adsorbate binding across candidate surfaces. | 👤 SandboxAQ AI Simulation Platform account | ⚠️ Limited: awaiting Discovery support for per-user sign-in ([details](../agents/aqcat/README.md#prerequisites)) |
| <a href="../agents/aqpotency/"><img src="https://avatars.githubusercontent.com/u/96544495?s=96" width="48" height="48" alt="SandboxAQ logo"></a><br>**[AQPotency](../agents/aqpotency/)**<br>SandboxAQ | Predicts small-molecule binding potency with uncertainty, scans molecules against predefined safety, kinome, and proteome panels, and checks selectivity against named off-targets. | 👤 SandboxAQ AI Simulation Platform account | ⚠️ Limited: awaiting Discovery support for per-user sign-in ([details](../agents/aqpotency/README.md#prerequisites)) |

## Built on partner and open-science platforms

Agents published and supported by Microsoft that bring partner and open-science platforms into Discovery.

| Agent | What it does | Setup requirements | Status |
| --- | --- | --- | --- |
| <a href="../agents/nvidia-alchemi/"><img src="https://avatars.githubusercontent.com/u/1728152?s=96" width="48" height="48" alt="NVIDIA logo"></a><br>**[NVIDIA ALCHEMI](../agents/nvidia-alchemi/)**<br>Built on the NVIDIA ALCHEMI Toolkit | GPU-accelerated, batched atomistic simulation, including structure relaxation and molecular dynamics, with machine-learned interatomic potentials such as MACE. Validated for single-GPU, nonperiodic MACE inference, relaxation, and molecular dynamics; other modes are experimental. | 🐳 Container image and a GPU node pool | ✅ Available |
| <a href="../agents/openalex-research-landscape/"><img src="https://avatars.githubusercontent.com/u/1500527?s=96" width="48" height="48" alt="OpenAlex logo"></a><br>**[OpenAlex Research Landscape](../agents/openalex-research-landscape/)**<br>Built on OpenAlex | Maps the research landscape for a scientific topic, including key works, authors, institutions, venues, and publication trends, and verifies citations. Returns evidence tables with OpenAlex and DOI links and the exact query that ran. | 👤 Free OpenAlex account for each user | ✅ Available |
| <a href="../agents/open-targets-evidence/"><img src="https://avatars.githubusercontent.com/u/8728108?s=96" width="48" height="48" alt="Open Targets logo"></a><br>**[Open Targets Evidence](../agents/open-targets-evidence/)**<br>Built on Open Targets | Finds and compares disease-associated targets using Open Targets associations and individual evidence, with identifiers, provenance, and uncertainty. | 🔓 None | ✅ Available (the Open Targets MCP server is experimental) |

## Pending review

Partner agents that have been submitted and are under review. They will appear in the catalog once they're approved and merged.

| Agent | What it does | Setup requirements | Status |
| --- | --- | --- | --- |
| <a href="https://github.com/microsoft/discovery/pull/150"><img src="https://avatars.githubusercontent.com/u/44258241?s=96" width="48" height="48" alt="Causaly logo"></a><br>**[Causaly Agentic Research](https://github.com/microsoft/discovery/pull/150)**<br>Causaly | Biomedical research agent that sends questions to the Causaly Agentic Research platform, which cross-checks evidence across a curated knowledge graph and the primary literature and returns answers with per-claim citations. | 👤 Causaly account with Agentic Research | 🕓 Pending review ([#150](https://github.com/microsoft/discovery/pull/150)) |
| <a href="https://github.com/microsoft/discovery/pull/267"><img src="https://avatars.githubusercontent.com/u/1728152?s=96" width="48" height="48" alt="NVIDIA logo"></a><br>**[NVIDIA RFD4-Proteina](https://github.com/microsoft/discovery/pull/267)**<br>NVIDIA | Joint protein structure and sequence design, including binder design, motif scaffolding, enzyme and antibody CDR design, and inverse folding, with the NVIDIA RFD4-Proteina NIM. | 🔑 NVIDIA API key for the hosted service, or a self-hosted NIM; 🐳 container image | 🕓 Pending review ([#267](https://github.com/microsoft/discovery/pull/267)) |
| <a href="https://github.com/microsoft/discovery/pull/316"><img src="https://avatars.githubusercontent.com/u/66438232?s=96" width="48" height="48" alt="expert.ai logo"></a><br>**[Protocol Design Intelligence (PDI)](https://github.com/microsoft/discovery/pull/316)**<br>expert.ai | Benchmarks clinical-study protocol designs against historical trials and scientific publications to guide evidence-based study design. The current dataset covers breast cancer. | 🔑 Access token from expert.ai | 🕓 Pending review ([#316](https://github.com/microsoft/discovery/pull/316)) |

## Become a partner

Partners contribute agents through the same pull-request workflow as every contributor: fork the repository, add a folder under `agents/<agent-name>/`, and set `publisher.party: 3p` in its `metadata.yaml`. Start with the [agent authoring guide](authoring-guides/agent-authoring-guide.md) and [`CONTRIBUTING.md`](../CONTRIBUTING.md).

---

Third-party agent entries in the catalog are governed solely by each partner's own terms; see each agent's `README.md` for details. Product names and logos are trademarks of their respective owners.

_Statuses last reviewed: November 2026._ Back to the [repository home](../README.md).
