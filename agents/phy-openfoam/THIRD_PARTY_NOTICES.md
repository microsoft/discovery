# Third-party notices and licensing scope

## Independently authored contribution

The independently authored source code, agent and skill definitions, scripts,
documentation, and other original material in this entry are licensed under the
MIT License, copyright (c) Microsoft Corporation. See [LICENSE](LICENSE). The
license text follows the [Microsoft Discovery MIT license](https://raw.githubusercontent.com/microsoft/discovery/main/LICENSE).

The independent host tool package is also MIT-licensed; see
[tools/openfoam/LICENSE](tools/openfoam/LICENSE). This is not a declaration that
the independent code is dual-licensed under MIT and the GNU GPL. Third-party
material retains its own copyrights and license terms. In particular, preserve
existing ownership and license notices in OpenFOAM case or template headers;
the MIT license for the wrappers does not relicense upstream material.

This source-only contribution includes no OpenFOAM or Gmsh binaries and no
third-party EULA-governed binary dependencies. Local-only historical evidence
and original artifacts are excluded from the contribution and are outside this
licensing statement.

## Worker dependencies

A worker image built from this entry installs third-party software under
multiple licenses; the aggregate image is not uniformly MIT-licensed. The
component notices, source references, complete GNU GPL version 3 text, and
complete Gmsh release license are maintained with the tool:

- [Worker third-party notices](tools/openfoam/THIRD_PARTY_NOTICES.md).
- [GNU GPL version 3](tools/openfoam/LICENSES/GPL-3.0-or-later.txt), applicable
  to Foundation OpenFOAM 14 under its version 3-or-later grant.
- [Gmsh 4.13.1 release license](tools/openfoam/LICENSES/Gmsh-4.13-LICENSE.txt),
  including GNU GPL version 2-or-later licensing and the complete special
  linking exception. Gmsh 4.13 is not GPL-3.0-only.

The OpenFOAM input is the OpenFOAM Foundation's
[OpenFOAM-14](https://github.com/OpenFOAM/OpenFOAM-14), DEB version **20260724**,
reported build **14-7b05503f98a8**. The worker also installs Gmsh 4.13.*, NumPy
2.4.6, pydantic 2.13.4 and its pydantic-core dependency, Matplotlib 3.10.*, and
Ubuntu operating-system packages. Their individual terms and the additional
licenses of bundled libraries remain applicable.

## Research attribution

This is an independent reconstruction informed by concepts and published scalar
reference targets in **CFD Forge: A Physics-Constrained Agentic Framework for
Autonomous CFD**, by **Aakash Shailesh Oza, Ryan F. Johnson, and Amir Barati
Farimani**, [arXiv:2610.14104](https://arxiv.org/abs/2610.14104), 2026.

No source code, datasets, or images from the paper or its accompanying project
are copied into this contribution. Published scalar targets are attributed
reference values, not a redistribution of the authors' datasets. This citation
does not grant rights to the paper or its associated artifacts, relicense them,
or imply affiliation with or endorsement by its authors.

## External application runtime

Microsoft Discovery and the CLIO application runtime are externally installed,
separately licensed products. They are not vendored in this entry. The MIT
license for this contribution does not grant rights to redistribute those
products or replace their applicable product terms.

## Redistribution and release checks

Publishing this source-only entry is distinct from conveying an image or another
artifact containing third-party binaries. A distributor of such binaries must
retain the applicable licenses and notices, satisfy any corresponding-source
and other redistribution obligations, and verify the exact components actually
shipped. Upstream project links alone do not prove that the corresponding source
for a particular binary distribution is available or that its obligations have
been fulfilled.

**Do not push or publish a worker image until the exact rebuilt-version
inventory, license, corresponding-source, and provenance checks described in
the worker notice have been completed.** These notices are a starting inventory,
not an exhaustive legal certification, source offer, or statement that license
review or approval is complete.