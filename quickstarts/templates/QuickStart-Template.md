# Quick Start — [Fill in: title]

**Proposed standard:** A Quick Start is a small, reproducible, versioned recipe linking a concrete outcome, selected model, bounded agents/tools/containers, sample data, fixed prompt, and verifiable output on a stated environment.

Keep the same core across verticals. Replace `[Fill in]` placeholders; use **N/A** for non-applicable items, not unknowns. Conditional App/Services fields apply only to the selected path. Publish one minimal tested reference path before adding separately identified variants.

> **How this QuickStart runs:** The user opens a new Discovery project, gives you this guide's GitHub link and asks you to run it. Read this entire guide first, then follow section 5. Download every file listed under **Required files** below into the open project folder, after asking the user's permission, and verify each size and SHA-256 before setup. The user does not need to download, attach or unzip anything. If you cannot open the link or download files, say exactly what failed and point the user to the fallback steps in this scenario's README. Reading or downloading this guide is not permission to install or compute.
>
> **Required files:** [Fill in one row per file: original filename; direct download URL (repository raw link, or release asset for files over 100 MiB); size in bytes; SHA-256].

## 1. Recipe identity — required

| Field | Value |
|---|---|
| Scenario and observable outcome | [Fill in] |
| Audience / vertical | [Fill in] |
| Delivery mode | [Fill in: App / Services / both] |
| Tested configuration / profile identifier | [Fill in] |
| Owner / recipe version / last validated date | [Fill in: owner; version; YYYY-MM-DD] |

## 2. Configuration matrix

All values describe the tested profile; repeat component rows as needed.

| Component | Applicability | Configuration to record |
|---|---|---|
| Model | Core | [Fill in: provider; model; pinned version/revision; local or hosted; relevant context/output limits, temperature/top-p, seed if supported] |
| Agents | Core | [Fill in: names, roles, versions, instruction/prompt versions; configured count; participating count] |
| Orchestration | Core | [Fill in: order/dependencies; sequential/parallel stages; concurrency, steps, retry and timeout limits] |
| Tools / APIs | Core; N/A if none | [Fill in: dependencies; versions; endpoint/configuration references; permissions and relevant limits] |
| Azure Container Apps (ACA) | If used | [Fill in: images with pinned tags/digests; CPU/RAM and GPU if applicable; replicas/min-max scale/rules; region; secure configuration and secret-store references] |
| Sample inputs | Core | [Fill in: permitted sample location; version/hash; size; input parameters] |

## 3. System requirements

Record units. Claim a minimum only after validation; otherwise keep **Not validated**. Recommendations are guidance, not proven minima. Complete the actually tested column. Validate compatibility across OS, architecture, model, runtime, drivers and images—never assume support. Windows/macOS are OS choices; x64/ARM64 are CPU architectures.

| Applies to | Requirement | Minimum | Recommended | Actually tested |
|---|---|---|---|---|
| App | OS and version | Not validated | [Fill in] | [Fill in] |
| App | CPU architecture (e.g., x64 / ARM64) | Not validated | [Fill in] | [Fill in] |
| App | CPU family / cores | Not validated | [Fill in] | [Fill in] |
| App | RAM | Not validated | [Fill in] | [Fill in] |
| App | GPU / VRAM, if needed | Not validated | [Fill in] | [Fill in] |
| App | Free storage | Not validated | [Fill in] | [Fill in] |
| Services | General node pool: node count; SKU/size | Not validated | [Fill in] | [Fill in] |
| Services | General pool: vCPU/RAM/GPU per node; scale limits | Not validated | [Fill in] | [Fill in] |
| Services | SuperComputer Nodepool: node count; SKU/size | Not validated | [Fill in] | [Fill in] |
| Services | SuperComputer: vCPU/RAM/GPU per node; scale limits | Not validated | [Fill in] | [Fill in] |

**Bookshelf — Services, if used:** Record the tested workload separately from hardware capacity; source size and indexed size are not interchangeable.

| Field | Tested profile value |
|---|---|
| Source corpus | [Fill in: document count; total source size with units; corpus version] |
| Index | [Fill in: indexed size with units; chunk count; index version] |
| Indexing recipe | [Fill in: embedding model/provider/version; chunk size/unit; overlap; relevant settings] |
| Index-ready condition | [Fill in: ingestion status; expected document/chunk counts; successful test-query check] |

## 4. Prerequisites

- **Access:** [Fill in: accounts, roles, subscriptions, licenses, region, quotas and model access].
- **Environment:** [Fill in: required tools/runtimes and versions; network/endpoints; container registry/image access].
- **Authentication:** [Fill in: authentication method and credential/secret-storage references]. Never include secrets.
- **Data:** [Fill in: permitted sample data, usage rights and handling restrictions].

## 5. Setup — one reproducible reference path

Replace each scaffold with exact commands/configuration references and an observable completion check. Keep only applicable App/Services branches; mark unused steps N/A.

1. **Select profile:** [Fill in: reference path, pinned configuration and required downloads/access].
2. **Install/provision:** App—[Fill in: app and dependencies]; Services—[Fill in: applicable pools, infrastructure and container dependencies].
3. **Deploy/configure:** [Fill in: model, agents, orchestration, tools and ACA containers; secure configuration references].
4. **Load data:** [Fill in: sample input loading; Bookshelf ingestion/indexing if applicable; wait for index-ready condition].
5. **Verify readiness:** [Fill in: model/tool/container health and access checks; expected results]. Then run the prompt below, validate output and record timing.

## 6. Fixed prompt + matching output

**Binding:** [Fill in: tested profile; prompt version; exact sample input/version and parameter values]. Include required system/agent instructions in the versioned configuration. Resolve placeholders before execution; the published prompt must be copy-paste ready.

**Exact predefined prompt**

```text
[Fill in: complete prompt with fixed input references, explicit parameters and requested output format.]
```

**Matching output** — [Fill in: verified expected / illustrative; illustrative output alone is not validation].

```text
[Fill in: matching expected or illustrative response, including required fields and artifact names.]
```

| Acceptance | Fill in the check |
|---|---|
| Required format / artifacts | [Fill in: schema/structure, units, artifact names and locations] |
| Exact checks | [Fill in: deterministic fields, constraints or reference values that must match] |
| Approximate / domain checks | [Fill in: semantic criteria, acceptable variance, numeric tolerances with units, domain validation method] |
| Pass condition | [Fill in: required checks and automated test or reviewer] |

Judge generated wording by the stated criteria, not identical phrasing. Separate exact requirements from approximate expectations.

## 7. Expected runtime

Tie timings to the **exact profile, model/settings, prompt, input/version, corpus/index size, participating agent count and parallelism**. Record test date, run count, load, network and cache/start state. Label each value **Measured** or **Estimated**; estimates need a basis, not benchmark claims.

| Stage | Measured / Estimated | First response (optional) | Completion duration / range, with units | Conditions / observations / runs |
|---|---|---|---|---|
| One-time install/provision/setup | [Fill in] | N/A | [Fill in] | [Fill in] |
| One-time data loading/indexing | [Fill in or N/A] | N/A | [Fill in or N/A] | [Fill in] |
| Cold-start prompt run | [Fill in] | [Fill in or N/A] | [Fill in] | [Fill in: define cold state] |
| Warm prompt run | [Fill in] | [Fill in or N/A] | [Fill in] | [Fill in: define warm state] |

For prompt runs, completion means **end-to-end time to a validated response**, including agent/tool work and output checks—not first-token time. Avoid double-counting setup/indexing; state whether either is included in a run.

## 8. Troubleshooting, cleanup and extensions

- **Troubleshooting:** [Fill in: symptom → nonsecret diagnostics/log reference → verified fix; escalation contact].
- **Cleanup:** [Fill in: stop/remove recipe-owned resources; release compute; retain/delete sample data and indexes per policy; identify ongoing resource charges without inventing costs].
- **Optional vertical addendum:** [Fill in or N/A: terminology, evaluation data, provenance, scientific or regulatory checks where relevant]. Append without changing the core structure.

## 9. Publication checklist

- [ ] One reference path reproduced; versions, sample inputs and prompt fixed to the tested profile.
- [ ] Output validated; exact/approximate acceptance criteria and domain checks explicit.
- [ ] Applicable configuration/specs complete; unused fields N/A; compatibility checked; no unverified minima claimed.
- [ ] Timings labeled with conditions; setup/indexing distinct from cold/warm runs.
- [ ] No secrets; samples permitted; cleanup documented; owner, version and validation date complete.
