# Microsoft Discovery — GPU sizing card

**Life sciences and chemistry / materials science agents — 41 of the 46 in the registry.**

Right-sized GPU class per agent, replacing the registry's `recommended_sku` field. That field is an *ordered preference ladder*, not a requirement — only 6 of these 41 agents set `min_resources.gpu = 1`, yet all 14 GPU-capable tools list an H100 SKU and 12 list it first. Recommendations below are the cheapest class that does not bottleneck a general-purpose run.

| 6 | 8 | 24 | 3 | 2 |
|---|---|---|---|---|
| require a GPU | benefit from one | CPU only | LLM only, no tool | still justify 80 GB |

## Colour key — recommended GPU class

| Tier | Class | Azure equivalent |
|---|---|---|
| ⬜ | None / CPU | D- or E-series |
| 🟩 | T4 16 GB | `Standard_NC4as_T4_v3` |
| 🟦 | A10 24 GB | `Standard_NV36ads_A10_v5` |
| 🟧 | A100 40 GB | `Standard_ND96asr_v4` |
| 🟥 | A100 80 GB | `Standard_NC24ads_A100_v4` |
| — | *(H100 94 GB, for reference)* | `Standard_NC40ads_H100_v5` |

> **Note:** Turing (T4) has fp16 tensor cores but no bf16. Use A10 or newer if your fine-tuning scripts assume bf16.

---

## Requires a GPU

`min_resources.gpu = 1` — these will not start without one.

| Agent | Tool | GPU status | Right-sized GPU + memory | Reference |
|---|---|---|---|---|
| **alphafold** | alphafold | Required | 🟦 **A10 24 GB** monomers ≤1200 aa · 🟧 **A100 40 GB** multimers / >1500 aa. Host RAM is the real constraint: ≥64 GB for MMseqs2 MSA | Mirdita et al., *Nat Methods* 2022, 19:679 (ColabFold); Jumper et al., *Nature* 2021, 596:583 |
| **boltzgen** | boltzGen | Required | 🟥 **A100 80 GB** — diffusion sampling + Boltz-2 folding and scoring in one pass *(est.; no published memory figures)* | BoltzGen preprint, 2025 |
| **boltztwo** | boltztwo | Required | 🟥 **A100 80 GB** — Ampere or newer is a hard floor (trifast kernels). H100 buys ~1.5–1.7× throughput; justified only at campaign scale | Passaro et al., bioRxiv 2025.06.14.659707 — ~140–200 complexes/H100-hr vs ~80–120/A100-hr |
| **mattergen** | mattergen | Required | 🟩 **T4 16 GB** — ~45 M params, unit cells capped at 20 atoms. 🟦 **A10 24 GB** only if fine-tuning on your own property labels | Zeni et al., *Nature* 2025, 639:624 — the 8× A100 figure is *training*, not inference |
| **retrochimera** | retrochimera | Required | 🟦 **A10 24 GB** single-step · 🟧 **A100 40 GB** wide-beam multi-step route search *(est. from architecture)* | Maziarz et al., 2025 (RetroChimera; Pistachio checkpoint) |
| **rfdiffusion** | rfDiffusion | Required | 🟦 **A10 24 GB** typical binder design (~300–400 residues) · 🟧 **A100 40 GB** large scaffolds, symmetric oligomers | Watson et al., *Nature* 2023, 620:1089 |

## Benefits from a GPU

`gpu 0–1` — runs on CPU, faster with a card. The biggest savings live here.

| Agent | Tool | GPU status | Right-sized GPU + memory | Reference |
|---|---|---|---|---|
| **chemberta** | chemberta | Benefits | 🟩 **T4 16 GB** — RoBERTa-base scale; fp16 weights sub-GB | Ahmad et al., arXiv:2209.01712 (ChemBERTa-2) |
| **chemprop** | chemProp | Benefits | 🟩 **T4 16 GB** — D-MPNN is ~1–3 M params; CPU is adequate below ~100k molecules | Heid et al., *JCIM* 2024, 64:9 (Chemprop v2) |
| **esm-embed** | esm-embed | Benefits | 🟩 **T4 16 GB** through ESM-2 650M (fp16 weights ~1.3 GB) · 🟦 **A10 24 GB** for batch throughput or contact maps at 1022 aa | Lin et al., *Science* 2023, 379:1123 |
| **gromacs** | gromacs | Benefits | 🟦 **A10 24 GB** — VRAM is never the limit (1M atoms is a few GB); bandwidth and clock are. A100 wasted while capped at 1 GPU | Páll et al., *JCP* 2020, 153:134110 — benchmarked on V100 PCIe + Xeon Gold 6148 |
| **nucleotide-tf** | nucleotide-tf | Benefits | 🟦 **A10 24 GB** for the 500 M model · 🟧 **A100 40 GB** for 2.5 B on multi-kb sequences | Dalla-Torre et al., *Nat Methods* 2025, 22:287 |
| **openmm** | openMM | Benefits | 🟦 **A10 24 GB** — latency- and bandwidth-bound at typical system sizes; an H100 NVL runs a 30k-atom system at low occupancy | Eastman et al., *JPCB* 2024, 128:109 (OpenMM 8) |
| **quantum-espresso** | quantum-espresso | Benefits | 🟥 **A100 80 GB** — the one case where the big card earns it; wavefunction arrays bind. Single-GPU cap limits the payoff | Carnimeo et al., *JCTC* 2023, 19:6992 — 80 GB removes the V100 memory ceiling; ~10× vs CPU on 96 A100s |
| **tamgen** | tamgen | Benefits | 🟩 **T4 16 GB** — pocket-conditioned chemical language model; sub-8 GB in practice *(est.)* | Wu et al., *Nat Commun* 2024, 15:9360 |

## CPU only

`gpu 0/0` — no GPU is provisioned. Where an upstream GPU build exists, it is noted.

| Agent | Tool | GPU status | Right-sized GPU + memory | Reference |
|---|---|---|---|---|
| **aizynthfinder** | aizynthFinder | Not needed | ⬜ **None** — CPU, 8–16 vCPU | Genheden et al., *J Cheminform* 2020, 12:70 |
| **ambertools** | amberTools | Not needed | ⬜ **None** — CPU | Salomon-Ferrer et al., *JCTC* 2013 (pmemd.cuda ships with Amber, not AmberTools) |
| **autodock** | autoDock | Not needed | ⬜ **None** as shipped — a GPU build would want 🟦 **A10 24 GB** (VRAM-light, throughput-bound) | Solis-Vasquez et al., *Parallel Computing* 2021 (A100/V100/RTX2070); Yu et al., *JCTC* 2023 (Uni-Dock, A100) |
| **bindingdb** | bindingDB | Not needed | ⬜ **None** — CPU | Gilson et al., *NAR* 2016 |
| **chembl** | chembl | Not needed | ⬜ **None** — CPU | Zdrazil et al., *NAR* 2024 |
| **clinical-trials** | clinicalTrials | Not needed | ⬜ **None** — CPU | — |
| **coconut** | coconut | Not needed | ⬜ **None** — CPU | Sorokina et al., *J Cheminform* 2021 |
| **core-python-agent** | corepython | Not needed | ⬜ **None** — CPU | RDKit |
| **cp2k** | cp2k | Not needed | ⬜ **None** as shipped — a DBCSR/CUDA build would want 🟧 **A100 40 GB** | Kühne et al., *JCP* 2020, 152:194103 |
| **crest** | crest | Not needed | ⬜ **None** — CPU, high core count | Pracht et al., *JCP* 2024, 160:114110 |
| **gwp-predictor** | gwpPredictor | Not needed | ⬜ **None** — CPU | Agent README (QSAR reference implementation; not externally validated) |
| **janus** | janus | Not needed | ⬜ **None** — CPU, 32–96 vCPU (parallel tempering scales with cores) | Nigam et al., *Digital Discovery* 2022, 1:390 |
| **lammps** | lammpsCpu | Not needed | ⬜ **None** as shipped — a Kokkos build would want 🟧 **A100 40 GB** | Thompson et al., *Comput Phys Commun* 2022, 271:108171 |
| **mol-toolkit** | mol-toolkit | Not needed | ⬜ **None** — CPU | — |
| **molecular-groups** | molecular-groups | Not needed | ⬜ **None** — CPU | — |
| **pdb-insights** | pdbInsights | Not needed | ⬜ **None** — CPU | Burley et al., *NAR* (RCSB PDB) |
| **pdb-search** | pdbSearch | Not needed | ⬜ **None** — CPU | Burley et al., *NAR* (RCSB PDB) |
| **psi4** | psiFour | Not needed | ⬜ **None** — CPU, high RAM (E-series sizing is correct as-is) | Smith et al., *JCTC* 2020, 16:3406 |
| **pubchem** | pubChem | Not needed | ⬜ **None** — CPU | Kim et al., *NAR* 2023 |
| **pubmed** | pubMed | Not needed | ⬜ **None** — CPU | — |
| **rnaseq** | rnaseq | Not needed | ⬜ **None** — CPU | — |
| **stat-agent** | stat-agent | Not needed | ⬜ **None** — CPU | — |
| **toxpred** | toxpred | Not needed | ⬜ **None** — CPU (🟩 **T4 16 GB** if a GPU path is added; same D-MPNN as Chemprop) | Heid et al., *JCIM* 2024, 64:9 |
| **zinc** | zinc | Not needed | ⬜ **None** — CPU | Irwin et al., *JCIM* 2020, 60:6065 |

## LLM only — no tool container

| Agent | Tool | GPU status | Right-sized GPU + memory | Reference |
|---|---|---|---|---|
| **bookshelf-researcher** | *(none — LLM only)* | N/A | ⬜ **None** — no tool container | — |
| **online-researcher** | *(none — LLM only)* | N/A | ⬜ **None** — no tool container | — |
| **patent-prior-art** | *(none — LLM only)* | N/A | ⬜ **None** — no tool container | — |

---

## Three worst mismatches, and how to change them

**MatterGen.** Specified `gpu 1/1` with H100 first, but it is a 45 M-parameter diffusion model generating unit cells of at most 20 atoms. Inference fits a T4 with room to spare. The 8× A100 figure in the Nature paper is the training run, which you are not repeating.

**TamGen.** Declared `gpu 0/1` yet lists *only* the H100 SKU, so a workload that fits in 8 GB has no path to anything smaller. The only tool where the optional-GPU flag and the SKU list directly contradict each other.

**OpenMM & GROMACS.** The largest recurring waste in node-hours, because MD is what people leave running. Neither is VRAM-limited — a million-atom system is a few GB — and both are capped at one GPU, so a big card buys clock speed an A10 already supplies. If you change only two entries, change these.

**How to change it.** Edit `compute.recommended_sku` in the tool's `tool.yaml` before deployment. It is advisory metadata — the supercomputer CLI never reads it and nothing validates it against the workload. Also check `pool_type`: every GPU tool is `static/1`, meaning a held node rather than a per-job burst.

---

*Source: github.com/microsoft/discovery — `.auto-registry/agent-registry.json` + per-tool `tool.yaml`, registry commit `d2ff532` (generated 2026-06-01). Silicon (Yosys, OpenSTA, Icarus Verilog, Xyce) and CFD (OpenFOAM) agents excluded. Three sizings marked (est.) are reasoned from model architecture rather than measured.*
