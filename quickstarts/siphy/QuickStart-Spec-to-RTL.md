# Quick Start — CoreSPI specification-to-verified-RTL with Discovery chip agents

**Proposed standard:** A Quick Start is a small, reproducible, versioned recipe linking a concrete outcome, selected model, bounded agents/tools/containers, sample data, fixed prompt, and verifiable output on a stated environment.

Keep the same core across verticals. Replace `[Fill in]` placeholders; use **N/A** for non-applicable items, not unknowns. Conditional App/Services fields apply only to the selected path. Publish one minimal tested reference path before adding separately identified variants.

## 1. Recipe identity — required

| Field | Value |
|---|---|
| Scenario and observable outcome | Use `hardware-spec-dev` to create an evidence-grounded CoreSPI Markdown reference specification from official Microchip documentation (HB0089, CoreSPI v5.2, revision 6.0), prepare `knowledge/CORESPI_HB.md`, then run `chip-rtl-design` → `chip-rtl-lint` → `chip-functional-verification`. Observable outcome: a `results/<unique-run-id>/` folder containing the authored reference specification, source handbook and provenance, synthesizable RTL (`corespi.v`), an independent self-checking testbench, a VCD waveform, logs, a short `results.md` summary and an offline HTML report from `report-gen`. Requested native-gate PASS requires design checks, DEFAULT lint, canonical formatting and simulation to pass on the same final RTL hash; requirement coverage limitations remain explicit. |
| Audience / vertical | Chip design and verification |
| Delivery mode | App |
| Tested configuration / profile identifier | `corespi-app-win11-x64-dockerdesktop-v1.1`; current reference run `results/corespi-hb-20261105T172838-f045862f`. Catalog retrieval and native gates were exercised with an existing authorized implementation contract; fresh-project contract creation is not yet validated. Historical v1.0 run: `results/corespi-20261105T013140181Z-9f62c8ad`. |
| Owner / recipe version / last validated date | Scenario maintainers; 1.1; 2026-11-05 (bounded current-run validation; publication gaps below). |

## 2. Configuration matrix

Values below distinguish current-run evidence from historical environment measurements. Repeat component rows as needed.

| Component | Applicability | Configuration to record |
|---|---|---|
| Model | Core | Parent chat model `gpt-6.1-sol`; specialist model overrides were not supplied. Effective per-agent model selections were not independently recorded for this run; do not infer them from the parent model. Pinned revision, context/output limits, temperature/top-p and seed were not recorded. Historical Bookshelf answer model: `gpt-4.1` (graphrag-zero provider metadata); no Bookshelf answer was used in the current engineering run. |
| Agents | Core | Four project specialists in `.github/agents/`: `hardware-spec-dev` (live tool discovery, official documentation retrieval, revision reconciliation, measurable requirements, explicit gaps and Markdown/link validation; current SHA-256 prefix `4957E6A43AC0E8BA`), `chip-rtl-design` (RTL authoring + Yosys hygiene/format; `B5D4B36E4DA91FF4`), `chip-rtl-lint` (DEFAULT Verible lint + canonical format; `952535047E42A95C`), `chip-functional-verification` (independent testbench + Icarus simulation; `E35B7FD48CD50D60`). Current project and bundled `hardware-spec-dev` definitions have matching hashes, checked 2026-11-05; this is file consistency, not proof of active-chat loading. Skill: `report-gen`, explicitly loaded for parent-owned final HTML reporting. |
| Orchestration | Core | Parent-orchestrated: `hardware-spec-dev` → parent prepares implementation contract → `chip-rtl-design` → `chip-rtl-lint` → `chip-functional-verification` → parent runs `report-gen`. Engineering stages are sequential. Current run: four successful specialist invocations, one per stage; a later FV follow-up message was rejected and did not execute another verification stage. Internal design repairs and simulation attempts `sim-01`–`sim-09` were preserved; final gates used unchanged RTL. Any adopted RTL revision requires fresh design, DEFAULT lint/format and simulation gates. Dispatch history also records a bounded read-only auxiliary ambiguity investigation; it was not an engineering gate. No recipe-wide retry/timeout budget was recorded. |
| Tools / APIs | Core | Microchip Catalog MCP documentation action exposed as `microchip-catalog-search_microchip_product_documents`; `hardware-spec-dev` recorded two successful calls. Its current definition grants `discovery-app.discovery-app/toolCatalog` and includes a machine-specific catalog source; select actual tool names, schemas and routing from the live inventory. Direct MCP `tools/list` was not exposed. Catalog endpoint, transport and authentication configuration were not captured in this run; do not reuse the historical `microchip-lab` / `microchip-lib` MPLAB-DOCS configuration as if verified for Catalog. The handbook was downloaded separately through official HTTPS. Scoped Bookshelf tools were unavailable to the engineering agents, which recorded that limitation rather than claiming consultation. Local runtime: Docker 29.9.2, context `desktop-linux`; images `rtl-design:latest` `6c337ec554e7` (Yosys 0.36+42; Verible), `rtl-lint:latest` `9a674c1cd20f` (Verible v0.0-4141-g09a245fe), and `functional-verification:latest` (Icarus Verilog 11.0; use native operation evidence for its image identity). Containers run `--pull=never --read-only --network=none --cpus=2 --memory=4g --pids-limit=256`. Python 3.13.17 for `report-gen`. |
| Azure Container Apps (ACA) | If used | N/A — App path uses local Docker Desktop only. |
| Sample inputs | Core | Public `CoreSPI_HB.pdf` (HB0089, CoreSPI v5.2, rev 6.0, April 2018), fetched from `https://ww1.microchip.com/downloads/aemDocuments/documents/FPGA/ProductDocuments/UserGuides/ip_cores/directcores/CoreSPI_HB.pdf`; current copy 502,147 bytes, 34 pages, SHA-256 `3089A5405F8847589A37D18E6817269FAA9A9828539A3F2B2DE0D77B376F4CC5`. Existing authorized `knowledge/CORESPI_HB.md` supplied original controller requirements; current run appended provenance and froze the contract. `CORESPI_HB` identifies the project specification, not a separate vendor device. Historical optional Bookshelf corpus: `knowledge/bs-data` / bundled `knowledge/bs_data` (section 3). Parameters: top `corespi`; DEFAULT lint, indentation 2, no waivers; simulation top `tb`, generation 2012, VCD. |

## 3. System requirements

Record units. Claim a minimum only after validation; otherwise keep **Not validated**. Recommendations are guidance, not proven minima. Host measurements below were recorded for the historical v1.0 run and were not remeasured for v1.1. They are not fresh compatibility evidence. Windows/macOS are OS choices; x64/ARM64 are CPU architectures.

| Applies to | Requirement | Minimum | Recommended | Actually tested |
|---|---|---|---|---|
| App | OS and version | Not validated | Windows 11 with Docker Desktop (Linux engine) | Windows 11 Enterprise 10.0.26200, 64-bit; Discovery app 1.0.0+ce8944066a68 |
| App | CPU architecture (e.g., x64 / ARM64) | Not validated | x64 (images are linux/amd64) | x64 (AMD64); Docker engine linux/amd64 |
| App | CPU family / cores | Not validated | ≥ 4 logical CPUs (containers request 2 CPUs each) | AMD EPYC 9V45 VM; 2 cores / 4 logical processors; Docker engine reports 4 CPUs |
| App | RAM | Not validated | ≥ 16 GB host (containers request 4 GB each) | 16.0 GB host; 7.75 GiB available to Docker engine |
| App | GPU / VRAM, if needed | Not validated | N/A — not required | None (Hyper-V virtual display adapter only) |
| App | Free storage | Not validated | ≥ 10 GB for images (historically ~3.5 GB) plus versioned run outputs | Historical: 59.2 GB free on C: after v1.0. Current final VCD: 5,938,499 bytes; current free storage not remeasured. |
| Services | General node pool: node count; SKU/size | N/A | N/A | N/A |
| Services | General pool: vCPU/RAM/GPU per node; scale limits | N/A | N/A | N/A |
| Services | SuperComputer Nodepool: node count; SKU/size | N/A | N/A | N/A |
| Services | SuperComputer: vCPU/RAM/GPU per node; scale limits | N/A | N/A | N/A |

**Bookshelf — Services, if used:** N/A for Services. The following local Bookshelf measurements belong to historical v1.0. Scoped shelves were unavailable to the current chip agents; no consultation is claimed. Bookshelf-enabled behavior remains a separately unvalidated variant of v1.1.

| Field | Tested profile value |
|---|---|
| Source corpus | `Design-Best-Practices` from `knowledge/bs_data` (source project `knowledge/bs-data`): 42 files (40 PDF, 1 Markdown README, 1 JSON manifest), 35,226,096 bytes (~33.6 MiB) of top-level source files; no separate corpus version number. |
| Index | Local graphrag-zero index; 42 documents, 3,486 indexed chunks; last indexed 2026-11-04T14:09:34Z. Indexed size on disk and index version not recorded. |
| Indexing recipe | Discovery app default graphrag-zero settings; embedding model, chunk size and overlap are not exposed and were not recorded. |
| Index-ready condition | Ingestion status `completed`; 42 documents / 3,486 chunks; shelf appears in `discovery.bookshelf.listShelves` and a search returns supporting passages. |

## 4. Prerequisites

- **Access:** Discovery app access to the hosted chat model (parent: `gpt-6.1-sol`), a trusted project folder, a registered Microchip Catalog connection callable by `hardware-spec-dev`, and network access to that connection's verified host and `ww1.microchip.com` for handbook download. Catalog connection settings must be obtained from the actual registered integration, not guessed from the old MPLAB-DOCS endpoint. No Azure subscription, quota or region is required for this local App recipe.
- **Environment:** Docker Desktop with the Linux engine running (`docker context show` → `desktop-linux`) or a working Podman runtime; the three chip images built from the bundled `discovery_catalog` build contexts (first build needs access to base images and package sources); Python ≥ 3.10 for `report-gen` (tested 3.13.17 — use a full Python installation, not the Windows Store `python.exe` alias).
- **Authentication:** Discovery app sign-in for model access. Catalog authentication requirements were not recorded; inspect the registered connection and supply any required authentication through Discovery's supported configuration. Do not transfer the old connection's credential-free assumption. Never include secrets in agent files or this recipe.
- **Data:** Public Microchip CoreSPI handbook, downloaded at run time; do not redistribute beyond Microchip's terms. The handbook does not by itself grant rights to retarget CoreSPI to ASIC or other-vendor FPGAs; the generated RTL is an original implementation, not vendor IP. Bookshelf PDFs are research papers bundled in `ship/knowledge/bs_data`; confirm usage rights before sharing outside your organization.

## 5. Setup — current reference path and publication prerequisites

Replace each scaffold with exact commands/configuration references and an observable completion check. Keep only applicable App/Services branches; mark unused steps N/A.

1. **Select profile:** App path, `corespi-app-win11-x64-dockerdesktop-v1.1`. Pin the four agent definitions, `report-gen`, `discovery_catalog` build contexts and the actual Catalog integration. The bundled and project `hardware-spec-dev` files match the current fingerprint, but that does not validate bundle connection setup. This template's prompt and connection guidance supersede older instructions in `ship/README.md`; bundle-wide documentation synchronization remains open.
2. **Install/provision:** Install Discovery and Docker Desktop; start the Linux engine. Copy `ship/dot-github/skills` → `<project>/.github/skills`, `ship/dot-github/agents/*` → `<project>/.github/agents`, and `ship/discovery_catalog` → `<project>/discovery_catalog`, reconciling rather than overwriting local changes. Check `docker version` for a responsive Linux server and inspect each exact image tag with `docker image inspect <tag>`. Existing images are reused; missing-image dependency builds require authorization. Services — N/A.
3. **Deploy/configure:** Use the actual Microchip Catalog integration registered in Discovery. If missing, add it through its supported MCP or tool/plugin import configuration using verified settings. Grant its callable documentation tools to `hardware-spec-dev`; for catalog-bridge routing, resolve the current source identifier rather than copying the machine-specific identifier in the bundled definition. Inspect live tool names, descriptions and schemas. Use direct MCP `tools/list` only if actually exposed; otherwise use the supported runtime catalog. ACA — N/A.
4. **Load data:** The prompt retrieves the public handbook. Inspect any existing `knowledge/CORESPI_HB.md` before creating/replacing it and obtain permission before replacement. The reference run reused an authorized original contract; a fresh project must resolve consequential behavior gaps explicitly, not silently adopt suggested defaults. Optional Bookshelf variant: copy `ship/knowledge/bs_data` → `<project>/knowledge/bs_data`, then use **AI Capabilities** > **Bookshelves** > **New Bookshelf** to create and index the shelf. Resolve each chip agent's actually scoped shelves and verify access before claiming consultation; this variant was not exercised in v1.1.
5. **Verify readiness:** Start a new chat and confirm the four agents and `report-gen` are exposed; file presence alone is insufficient. Ask `hardware-spec-dev` to perform a Catalog documentation lookup for `CoreSPI HB0089 handbook 5.2`, using its live schema (tested limit 10). Expect a successful application-level response with an official source link; record the tool, query and outcome. Confirm `docker info` responds. Then run the unchanged user prompt below, check outputs and record current-run timing.

## 6. Fixed prompt + matching output

**Binding:** Profile `corespi-app-win11-x64-dockerdesktop-v1.1`; prompt version 1.1 is the user's prior execution prompt reproduced verbatim below, including the spelling "veirlog". No replacement prompt or automatic "Recommended" instruction is added. Sample input: HB0089 CoreSPI v5.2 rev 6.0 fetched at run time. The word "device" in the preserved prompt refers here to the project controller specification. The current run already had a user-authorized full-feature original contract; any new project must obtain decisions for consequential gaps before implementation. No vendor-equivalence claim is implied.

**Exact predefined prompt**

```text
First, use hardware-spec-dev agent to create the CoreSPI specification document.
Next, create a specification markdown document in knowledge directory for the CORESPI_HB device.
Then use these three agents in order to implement and verify the design described in knowledge/CORESPI_HB.md:

chip-rtl-design: Read the specification, create synthesizable veirlog, and run the design checks.
chip-rtl-lint: Check the RTL with the default lint rules and canonical formatting check. Fix any issues before continuing.
chip-functional-verification: Create an independent, self-checking testbench from the specification, run simulation, and produce a VCD waveform.
If the RTL changes, repeat all checks on the final version. Report PASS only when design checks, lint, formatting, and simulation all pass. Otherwise, report the actual failure.

Save the RTL, testbench, waveform, and a short results summary, and provide links to them. Save all generated files—including RTL, testbench, logs, waveform, and results summaries—under results/<unique-run-id>/ in this project, rather than under sessions/.
```

**Matching output** — Illustrative, abridged from current run `corespi-hb-20261105T172838-f045862f` (2026-11-05). Counts, paths and wording can differ between runs; never substitute historical totals for current evidence.

```text
PASS for requested native gates: final-version design checks, DEFAULT lint,
canonical formatting and independent simulation passed on identical RTL.
Final simulation: 39,753 comparisons, zero mismatches, 21 configurations
each tested in master and slave roles. Requirement review: pass_with_caveats.
Compatibility note: corespi.v uses a minimal synthesizable SystemVerilog
subset (always_comb); enable SystemVerilog language mode.

Reference specification results/<unique-run-id>/spec/CoreSPI.md
Source handbook         results/<unique-run-id>/sources/CoreSPI_HB.pdf
Retrieval provenance    results/<unique-run-id>/retrieval/RETRIEVAL.md
Implementation contract knowledge/CORESPI_HB.md
RTL                     results/<unique-run-id>/run/rtl/corespi.v
Testbench               results/<unique-run-id>/sim-09/input/tb_corespi.v
VCD                     results/<unique-run-id>/sim-09/output/results/corespi.vcd
Results                 results/<unique-run-id>/results.md
                        results/<unique-run-id>/report-full.html
```

| Acceptance | Fill in the check |
|---|---|
| Required format / artifacts | Under one new `results/<unique-run-id>/`: authored CoreSPI reference Markdown, source handbook PDF, retrieval provenance, frozen implementation contract, Verilog/SystemVerilog RTL, independent self-checking testbench, nonempty VCD, native simulation/lint/design logs, per-stage CDEs and invocation/exit/timestamp/hash evidence, preserved attempts, `results.md`, and HTML from `report-gen`. Explicitly requested `knowledge/CORESPI_HB.md` is the exception outside the run directory. Provide separate workspace links to the specifications, PDF, RTL, testbench, waveform and reports. Nothing generated under `sessions/`. |
| Exact checks | Each named specialist executes in the requested order. Reference Markdown is nonempty, cites the governing revision and labels vendor-defined, user-required and original/proposed behavior, measurable acceptance criteria and unresolved gaps; local links resolve. Catalog documentation lookup succeeds at the application level; direct HTTPS source retrieval is separately recorded. Final design CDE: completed/pass, native/container exits 0, synthesizable true, zero latches/check/reset/synchronizer gating findings, no undriven/multidriven nets and no missing metrics. Every declared legal elaboration case passes; illegal-parameter rejection tests are separately expected failures, not legal-case failures. DEFAULT lint: zero violations, native/container exits 0, no waivers or overrides. Canonical format: zero unformatted files, exit 0. Simulation: completed/pass, sim_passed true, exactly one positive `COMPARISONS` summary with `MISMATCHES=0`, exact standalone `TEST PASSED`, no failure/error markers, native/container exits 0 and nonempty VCD. Final stages record the same measured RTL hash. Record actual matrices, omissions and whether invocation records were captured contemporaneously or derived from a preserved launcher. |
| Approximate / domain checks | `hardware-spec-dev` uses live Catalog documentation search, follows returned official HTTPS links and reads HB0089 to confirm version/revision/content; a PDF URL alone is not sufficient. Governing-document gaps remain explicit. Agents record actual Bookshelf consultation or precise unavailability, never inferred consultation. RTL exposes documented APB3/SPI ports and parameters; independently tested matrices sample Motorola modes 0–3, TI/NSC and both roles. Original deviations are explicit, not vendor-equivalence claims. Preserved repair/recheck attempts are acceptable; sampled counts do not establish exhaustive coverage. |
| Pass condition | Report requested native-gate PASS only when all required final engineering gates pass on identical RTL; keep requirement-level caveats separate. Specification-only checks never imply engineering correctness. HTML renderer exit 0 completes reporting; exit 2 is a report with disclosed evidence/visualization issues, not clean reporting or an engineering failure by itself. The current final report rendered with exit 0 after an explicit waveform-limit increase. Browser visual inspection remains unverified. Review linked native evidence and attribution rather than treating the agent diagram as an activation audit. |

Judge generated wording by the stated criteria, not identical phrasing. Separate exact requirements from approximate expectations.

**Current reference-run status:** Catalog documentation search was exposed and used twice successfully by `hardware-spec-dev`; the handbook was then downloaded through direct HTTPS and inspected locally. [Retrieval provenance](../results/corespi-hb-20261105T172838-f045862f/retrieval/RETRIEVAL.md) contains normalized call records, not raw response exports. Design checks passed, including 61 legal elaboration cases and six intended illegal-parameter rejections. DEFAULT lint/format passed; final simulation passed with 39,753 comparisons and zero mismatches. [Results](../results/corespi-hb-20261105T172838-f045862f/results.md), [dispatch history](../results/corespi-hb-20261105T172838-f045862f/dispatch.json) and [final report](../results/corespi-hb-20261105T172838-f045862f/report-full.html) preserve evidence and limitations.

**Boundaries:** Existing authorized specification/prior original RTL were reused and repaired; fresh-project specification creation is not validated. [Requirements matrix](../results/corespi-hb-20261105T172838-f045862f/sim-09/evidence/REQUIREMENTS_MATRIX.md) retains untested full-TX dequeue/enqueue collision, some partial-access reset/abort cases, active configuration changes, detailed slave OE timing and NSC post-final extra clocks. Scoped Bookshelves were unavailable. Simulation invocation arguments were derived during reporting from the preserved launcher, not captured contemporaneously. Historical v1.0 had unavailable Microchip MCP actions and used official HTTPS alone; that old access failure is not the current status.

## 7. Expected runtime

Tie timings to the **exact profile, model/settings, prompt, input/version, corpus/index size, participating agent count and parallelism**. Record test date, run count, load, network and cache/start state. Label each value **Measured** or **Estimated**; estimates need a basis, not benchmark claims.

| Stage | Measured / Estimated | First response (optional) | Completion duration / range, with units | Conditions / observations / runs |
|---|---|---|---|---|
| One-time install/provision/setup | Not measured | N/A | Not recorded | Current run reused existing images/interpreter; no dependency build was performed. Historical images were prebuilt on 2026-11-03; build time not captured. |
| One-time data loading/indexing (historical v1.0 only) | Measured | N/A | ≈ 2 min 13 s | `Design-Best-Practices`, 42 documents / 3,486 chunks; 2026-11-04T14:07:22Z → 14:09:35Z; 1 run. No current-run indexing/consultation claimed. |
| Cold-start prompt run | Not measured | N/A | Not recorded | Cold state (no images, no index) was not tested. |
| Warm prompt run (current v1.1) | Not measured end-to-end | Not recorded | Not recorded | 2026-11-05; one recorded run, existing images and authorized contract, four successful sequential specialist invocations, internal repairs/bench retries, then reporting. Do not infer end-to-end duration from native process runtimes. Record a fresh timed run before publishing a v1.1 benchmark. |
| Final native workers (current v1.1) | Measured | N/A | Design 0.58 s; lint/format 0.62 s; simulation 4.67 s | CDE `provenance.runtime.elapsed_seconds` for final operations only. Excludes source authoring, documentation retrieval, container startup overhead outside worker measurement, parameter campaign, previous attempts and reporting. These are not prompt-run or circuit timing. |
| Warm prompt run (historical v1.0 only) | Measured | Not recorded | ≈ 54 min (01:31:27Z → 02:25:20Z) | Older prompt/connection, prebuilt images and indexed Bookshelf; four participating agents, ten dispatches including lint repairs and FV gap closure. Includes clarification/reporting, excludes setup/indexing. This is not a benchmark for the revised Catalog-backed recipe. |

For prompt runs, completion means **end-to-end time to a validated response**, including agent/tool work and output checks—not first-token time. Avoid double-counting setup/indexing; state whether either is included in a run.

## 8. Troubleshooting, cleanup and extensions

- **Troubleshooting:**
  - `hardware-spec-dev` cannot call Catalog tools → inspect the live inventory, permissions and actual registered source identifier; distinguish a globally connected tool from one callable by this agent. If not exposed, report **tool unavailable; no connection attempted**. If a call fails, preserve its actual error and application-level response. Reconfigure through supported Discovery integration, start a new chat and retest a small Catalog lookup. Official HTTPS fallback may supply evidence but does not pass a required Catalog-use check.
  - Direct product-page HTTP403 or an advisory returning only an HTML shell → retain the HTTP/error evidence and identify successful Catalog content separately. HTTP200 alone does not establish readable technical content or a complete specification.
  - Chip agent reports engine unavailable → `docker info`, `docker context show` → start Docker Desktop's Linux engine and select `desktop-linux`.
  - DEFAULT lint fails (for example, `always-comb`, `line-length`) → `lint/attempt-*/output/logs/verible_lint.log` → expected repair loop: route diagnostics to `chip-rtl-design`, then rerun all design and lint checks. `always_comb` makes the RTL a SystemVerilog subset; tools must use SV mode.
  - Follow-up message to a finished agent is rejected → preserve the rejection and report that no follow-up executed. Do not imply coverage gaps were closed. A new authorized narrow engineering stage, if needed, must be explicitly recorded; any adopted RTL change requires all final gates again.
  - Host Python exits 9009 → Windows Store `python.exe` alias → use a full Python installation path.
  - `report-gen` exits 2 with "VCD exceeds 1000000 value records" → inspect console JSON, preserve the first report and rerender to a new file with an explicit justified limit. Current run used `--max-changes 3000000`, producing `report-full.html` with exit 0 and no evidence issues; optional `--signals` requires exact scoped names (at most 12). Do not discard transitions or suppress evidence errors.
  - Escalation contact: scenario maintainers.
- **Cleanup:** Stop Docker Desktop when finished; agents run containers with `--rm`, so no containers persist. Remove old image tags if storage is needed (`docker image rm <tag>`). Retain or delete `results/<unique-run-id>/` per your data policy. Delete the Bookshelf from **AI Capabilities** > **Bookshelves** if no longer needed. The App path creates no cloud resources; model usage is billed per your Discovery/model access terms (costs not recorded).
- **Optional vertical addendum:** Chip design and verification. PASS is bounded zero-delay functional verification against an original specification. It is not exhaustive parameter proof, vendor CoreSPI equivalence, CDC/RDC signoff, timing closure, FPGA qualification or physical signoff. Asynchronous `PRESETN` release is not synchronized internally; handle it during integration. The `report-gen` agent invocation diagram is parent-recorded attribution, not an activation audit.

## 9. Publication checklist

- [x] Current Catalog retrieval and native-gate path recorded; original user prompt reproduced verbatim and reference evidence linked.
- [x] Output validated; exact/approximate acceptance criteria and domain checks explicit.
- [ ] Fresh-project contract creation and applicable requirement coverage validated. *(Open: reference reused authorized requirements/prior original RTL; coverage omissions remain explicit.)*
- [ ] Portable Catalog setup, active-definition loading and bundle-wide instructions validated on a fresh installation. *(Catalog calls succeeded in this run; endpoint/transport/authentication settings were not captured. Matching definition files alone do not close deployment validation.)*
- [ ] Applicable configuration/specs complete; compatibility checked; no unverified minima claimed. *(Host measurements are historical; effective per-agent model settings were not recorded; Bookshelf variant was not exercised.)*
- [x] Historical timing and final native-worker durations labeled separately; no revised end-to-end benchmark invented.
- [ ] Current-profile end-to-end runtime measured with stated start/cache conditions; final HTML visually inspected in an available browser.
- [x] No secrets; samples permitted; cleanup documented; owner, version and validation date complete.
