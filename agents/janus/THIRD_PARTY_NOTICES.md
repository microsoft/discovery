# Third-Party Notices — janus agent

The `janus` Discovery agent embeds the following open-source components inside its
container image. The wrapper code under `/app/` is MIT-licensed (see the repository
top-level `LICENSE`). The components below carry their own licenses, reproduced in
their installed locations under `/usr/lib/python3.12/site-packages/<pkg>/`.

| Component | Version | License | Source |
|---|---|---|---|
| janus-ga (JANUS algorithm) | 1.0.3 | Apache-2.0 | https://github.com/aspuru-guzik-group/JANUS |
| SELFIES | 1.0.3 | Apache-2.0 | https://github.com/aspuru-guzik-group/selfies |
| RDKit | 2024.3.5 | BSD-3-Clause | https://github.com/rdkit/rdkit |
| PyTorch (CPU build) | 2.2.2 | BSD-3-Clause | https://github.com/pytorch/pytorch |
| NumPy | 1.26.4 | BSD-3-Clause | https://github.com/numpy/numpy |
| pandas | 2.1.4 | BSD-3-Clause | https://github.com/pandas-dev/pandas |
| SciPy | 1.11.4 | BSD-3-Clause | https://github.com/scipy/scipy |
| matplotlib | 3.8.2 | matplotlib (BSD-style) | https://github.com/matplotlib/matplotlib |
| seaborn | 0.13.2 | BSD-3-Clause | https://github.com/mwaskom/seaborn |
| PyYAML | 6.0.1 | MIT | https://github.com/yaml/pyyaml |
| requests | 2.32.3 | Apache-2.0 | https://github.com/psf/requests |

## Citation

When publishing results obtained with this agent, cite the JANUS paper:

> AkshatKumar Nigam, Robert Pollice, Gary Tom, Alán Aspuru-Guzik. *JANUS: Parallel
> Tempered Genetic Algorithm Guided by Deep Neural Networks for Inverse Molecular
> Design.* Digital Discovery, 2022, 1, 390-404.
> https://doi.org/10.1039/D2DD00003B

And the SELFIES paper:

> Mario Krenn, Florian Häse, AkshatKumar Nigam, Pascal Friederich, Alán Aspuru-Guzik.
> *Self-referencing embedded strings (SELFIES): A 100% robust molecular string
> representation.* Machine Learning: Science and Technology 1 (2020) 045024.
> https://doi.org/10.1088/2632-2153/aba947

## Apache-2.0 NOTICE preservation

Both `janus-ga` and `selfies` are Apache-2.0. Their LICENSE files travel inside the
container at the standard pip site-packages locations:

- `/usr/lib/python3.12/site-packages/janus_ga-1.0.3.dist-info/LICENSE`
- `/usr/lib/python3.12/site-packages/selfies-1.0.3.dist-info/LICENSE`

These files are NOT removed by the Dockerfile cleanup steps.
