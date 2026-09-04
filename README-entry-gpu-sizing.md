## GPU sizing card — Life Sciences / Chemistry / Materials Science agents

**Purpose.** Right-sized GPU recommendations for each agent: the cheapest GPU class and memory size that does not bottleneck a general-purpose run. Intended as a practical replacement for the registry's `recommended_sku` field, which is defined in `tool-definition-schema.json` as an *ordered preference ladder* rather than a hardware requirement, and is frequently read as the latter by customers and partners.

**Scope.** 41 of the 46 agents in `agent-registry.json` — the life sciences and chemistry / materials science set. The silicon (Yosys, OpenSTA, Icarus Verilog, Xyce) and CFD (OpenFOAM) agents are excluded; all five are CPU-only and none has a GPU SKU. Of the 41: 6 require a GPU, 8 benefit from one, 24 are CPU-only, and 3 are LLM-only with no tool container.

**Assumptions.**

- Sizing targets single-job, general-purpose inference — not model training, and not campaign-scale batch throughput, both of which justify larger cards.
- fp16 or bf16 precision where the tool supports it. Note that Turing (T4) has fp16 tensor cores but no bf16.
- CPU and host-RAM floors are taken from each tool's existing `min_resources` and were not independently re-derived.

**Limitations.**

- Not benchmarked in-house across every GPU class. Recommendations rest on published benchmarks where they exist and on model architecture where they do not. Corrections from hands-on experience are welcome and expected.
- Three sizings — BoltzGen, RetroChimera, TamGen — are reasoned from architecture rather than measured, and are marked *(est.)* in the card.
- Snapshot of registry commit `d2ff532` (generated 2026-06-01). Compute blocks are hand-authored per agent and change independently, so re-check against `main` before circulating.
- Two hard floors are not negotiable by price: six agents set `min_resources.gpu = 1` and will not start without a GPU, and Boltz-2 and BoltzGen require Ampere or newer (the trifast kernels do not run on V100-class hardware).
- `recommended_sku` is advisory metadata — the supercomputer CLI does not read it and nothing validates it against the workload. Changing it is a pre-deployment edit to the tool's `tool.yaml`, not a platform setting.

**Sources.**

- `.auto-registry/agent-registry.json` — agent list, associated tools
- `agents/*/tools/*/tool.yaml` — `compute.min_resources`, `max_resources`, `recommended_sku`, `pool_type`
- `docs/schemas/tool-definition-schema.json` — definition of `recommended_sku` as an ordered list
- Primary literature, cited per row in the card. Benchmarks with explicit GPU hardware include Passaro et al. (bioRxiv 2025, Boltz-2, H100), Zeni et al. (*Nature* 2025, MatterGen, 8× A100 training), Carnimeo et al. (*JCTC* 2023, Quantum ESPRESSO, A100 80 GB), Páll et al. (*JCP* 2020, GROMACS, V100 PCIe), and Solis-Vasquez et al. (*Parallel Computing* 2021, AutoDock-GPU, A100/V100/RTX2070).
