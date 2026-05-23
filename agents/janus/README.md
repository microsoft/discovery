# De Novo Molecule Generator (powered by JANUS)

A Discovery agent that wraps the JANUS algorithm (Aspuru-Guzik group, Nigam et al.,
Digital Discovery 2022) for SELFIES-based de novo molecule generation under
user-supplied fitness functions. Designed for inverse molecular design in materials
chemistry: refrigerants, lubricants, electrolytes, dyes, monomers, ligands.

## Overview

When you need to invent novel molecules with a target property profile — and you do
NOT have a labelled training set large enough for a graph neural network — a
gradient-free SELFIES-based genetic algorithm is the state of the art. JANUS combines:

- A **SELFIES** representation that guarantees every generated string corresponds to a
  valid molecule (no wasted compute on invalid SMILES).
- **Parallel tempering** between an exploration branch (random mutation + crossover)
  and an exploitation branch (a small DNN classifier trained on past fitness values).
- A user-supplied fitness function that scores any candidate SMILES.
- An optional custom filter. The agent's recommended template wires in a
  PFAS-rejection filter via `make_pfas_filter()` and applies it as a hard
  post-filter on the final results; the underlying `run_janus(custom_filter=None)`
  default is to accept all molecules.

This agent runs entirely on CPU, ships no model weights, and requires no internet at
runtime.

## Architecture

```
seed SMILES + fitness_fn + filter
              │
              ▼
        janus_utils.run_janus
              │
              ▼
     JANUS GA (SELFIES space)
       │                 │
       ▼                 ▼
   exploration       exploitation
  (random mutate +  (DNN-guided
   crossover)        mutate + cross)
       │                 │
       └────── filter ───┘  ◄── PFAS rejection in agent template (post-filtered as hard constraint)
              │
              ▼
   per-generation populations
              │
              ▼
   ranked unique molecules + CSV + final_results.json
```

## Prerequisites

- A Discovery workspace with a CPU nodepool (D4s_v6 or larger).
- A model deployment whose name will be substituted for `{{CHAT-MODEL}}` at publish time.

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Chat model deployment used for plan/script generation | `gpt-5-deployment` |

## Tools

| Tool | Description |
|---|---|
| `janus` | Container that wraps `janus-ga 1.0.3` plus `janus_utils.py` for clean Discovery integration. CPU-only. ~1.5 GB image (PyTorch CPU is the bulk). |

The container exposes one Python code environment. Scripts call `janus_utils.run_janus(...)`
which returns a dict including `scored` (list of `{smiles, score}` sorted descending), `best`,
`elapsed_seconds`, `n_unique_generated`, and the JANUS work directory path for inspection.

## Usage

### Sample prompt 1 — PFAS-free heat-transfer-fluid generation
Seed with Novec 649 and HFE-7100. Optimise a composite fitness that rewards
boiling-point proxy near 78 C and penalises PFAS substructures. Run 20 generations of
population 100 on a D8s_v6 node.

### Sample prompt 2 — multi-objective via weighted sum
Given a 5-objective design problem (e.g. minimise viscosity + |Tb − 78| + GWP, maximise
flash margin + score), define `fitness = sum(w_i * score_i)` inside the callable.
For a true Pareto-front output, hand the resulting population to the `nsga-moo` agent.

### Sample prompt 3 — scaffold-hopping search
Seed with a single anchor molecule. Use a wide tolerance in the property-target score
to let the GA roam. Inspect `out['scored'][:50]` to see the diverse population JANUS
discovered around the seed.

## Support

Issues: https://github.com/microsoft/discovery-catalog/issues

## Known Limitations

- CPU-only by design. Even on a 48-vCPU node, runs of `generations × generation_size > 50000`
  may take an hour or more. Scale generation_size before scaling generations.
- The DNN classifier (use_classifier=True) trains a small torch model per generation;
  set to False for smoke tests and shorter runs to avoid the overhead.
- SELFIES 1.0.3 is hard-pinned by janus-ga 1.0.3. Newer SELFIES alphabets are not
  compatible with this version.
- Output molecules can be unusual (cyclic ethers, exotic heteroatom arrangements). The
  PFAS filter rejects fluorinated chains but is otherwise permissive — downstream
  hazard screening (`molecular-groups` agent) is recommended.

## License

This agent is governed by the repository's top-level [`LICENSE`](../../../LICENSE) (MIT).

## Third-Party Components

| Component | Version | License | Source |
|---|---|---|---|
| janus-ga (JANUS algorithm) | 1.0.3 | Apache-2.0 | https://github.com/aspuru-guzik-group/JANUS |
| SELFIES | 1.0.3 | Apache-2.0 | https://github.com/aspuru-guzik-group/selfies |
| RDKit | 2024.3.5 | BSD-3-Clause | https://github.com/rdkit/rdkit |
| PyTorch (CPU) | 2.2.2 | BSD-3-Clause | https://github.com/pytorch/pytorch |

Full attribution and citation guidance is in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
The container preserves the upstream `janus-ga` LICENSE inside the Python wheel at
`/usr/lib/python3.12/site-packages/janus_ga-1.0.3.dist-info/LICENSE`.

## Contributing

See the repository CONTRIBUTING guidelines.
