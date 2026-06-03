# Third-Party Notices — gromacs agent

The `gromacs` Discovery agent embeds the following open-source components inside
its container image. The wrapper code under `/app/` and the helper library at
`/opt/gromacs_utils/gromacs_utils.py` are MIT-licensed (see the repository
top-level `LICENSE`). The components below carry their own licenses; reproduced
copies travel inside the container at the standard install locations.

## Core simulation stack

| Component | Version | License | Source |
|---|---|---|---|
| GROMACS | 2024.4 | LGPL-2.1 | https://ftp.gromacs.org/pub/gromacs/ |
| NVIDIA CUDA base image (`nvidia/cuda:12.6.3-devel-ubuntu22.04`) | 12.6.3 | NVIDIA Deep Learning Container License | https://docs.nvidia.com/cuda/eula/ |
| Open Babel | distro (Ubuntu 22.04) | GPL-2.0-or-later | https://github.com/openbabel/openbabel |

## Force fields

| Force field | Source | License / Terms |
|---|---|---|
| AMBER14SB + parmbsc1 (`amber14sb.ff`, `amber14sb_parmbsc1.ff`) | https://github.com/intbio/gromacs_ff (academic port; underlying ff14SB and parmbsc1 parameters are publicly published) | Public / academic use. Maintained by the INT.BIO group as a community port. |
| CHARMM36m for GROMACS, February 2026 release, CGenFF v5.0 (`charmm36m.ff`) | http://mackerell.umaryland.edu/charmm_ff.shtml | Free for academic use. **Commercial use of the CGenFF parameters may require a separate license**, obtained either via the MacKerell lab (not-for-profit) or SilcsBio, LLC (for-profit). See http://mackerell.umaryland.edu/warning.shtml. |
| GROMACS-bundled force fields (`charmm27`, `oplsaa`, `gromos54a7`, `amber99sb-ildn`, etc.) | Ships with GROMACS 2024.4 | LGPL-2.1 (same as GROMACS) |

## Python scientific stack

| Component | License | Source |
|---|---|---|
| NumPy | BSD-3-Clause | https://github.com/numpy/numpy |
| SciPy | BSD-3-Clause | https://github.com/scipy/scipy |
| pandas | BSD-3-Clause | https://github.com/pandas-dev/pandas |
| matplotlib | matplotlib license (BSD-style) | https://github.com/matplotlib/matplotlib |
| Pillow | MIT-CMU | https://github.com/python-pillow/Pillow |

Exact pinned versions resolve at build time from PyPI; consult `pip freeze` on
the running container for the as-shipped versions.

## Citations

When publishing results obtained with this agent, please cite GROMACS:

> M. J. Abraham, T. Murtola, R. Schulz, S. Páll, J. C. Smith, B. Hess, E. Lindahl.
> *GROMACS: High performance molecular simulations through multi-level
> parallelism from laptops to supercomputers.* SoftwareX 1–2 (2015) 19–25.
> https://doi.org/10.1016/j.softx.2015.06.001

If you use the CHARMM36m protein force field, also cite:

> J. Huang, S. Rauscher, G. Nawrocki, T. Ran, M. Feig, B. L. de Groot,
> H. Grubmüller, A. D. MacKerell, Jr. *CHARMM36m: an improved force field for
> folded and intrinsically disordered proteins.* Nature Methods 14 (2017) 71–73.
> https://doi.org/10.1038/nmeth.4067

If you use the AMBER14SB + parmbsc1 force field, cite the original AMBER ff14SB
and parmbsc1 papers:

> J. A. Maier, C. Martinez, K. Kasavajhala, L. Wickstrom, K. E. Hauser, C. Simmerling.
> *ff14SB: Improving the Accuracy of Protein Side Chain and Backbone Parameters
> from ff99SB.* J. Chem. Theory Comput. 11 (2015) 3696–3713.
> https://doi.org/10.1021/acs.jctc.5b00255

> I. Ivani, P. D. Dans, A. Noy, A. Pérez, et al. *Parmbsc1: a refined force field
> for DNA simulations.* Nature Methods 13 (2016) 55–58.
> https://doi.org/10.1038/nmeth.3658

## License-file preservation

Per the respective license terms, copies of the upstream license files travel
inside the container image at:

- GROMACS: `${GMX_PREFIX}/share/gromacs/COPYING`
- CHARMM36m force field: `${GMX_PREFIX}/share/gromacs/top/charmm36m.ff/` — see the
  `forcefield.doc` and the embedded references therein.
- AMBER14SB + parmbsc1 force field: `${GMX_PREFIX}/share/gromacs/top/amber14sb.ff/`
  and `${GMX_PREFIX}/share/gromacs/top/amber14sb_parmbsc1.ff/`.
- Python packages: each package's `<pkg>-<ver>.dist-info/` directory under
  `/usr/lib/python3/dist-packages/` (or the equivalent `site-packages` path).
- Open Babel: `/usr/share/doc/openbabel/copyright` (Debian copyright file).

These files are not removed by any Dockerfile cleanup step.
