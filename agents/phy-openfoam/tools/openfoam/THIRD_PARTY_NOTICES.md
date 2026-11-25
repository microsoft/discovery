# OpenFOAM worker: third-party notices

## Host package and scope

The independently authored `discovery-physics-openfoam` host package, wrappers,
and documentation are licensed under the [MIT License](LICENSE), copyright (c)
Microsoft Corporation. This does not dual-license the independent code under
MIT and the GNU GPL, or relicense upstream components. Preserve all existing
third-party copyrights and license notices, including ownership in OpenFOAM
case/template headers. The entry-level scope and research attribution are in
[the entry's third-party notices](../../THIRD_PARTY_NOTICES.md).

This is a source-only contribution. No OpenFOAM or Gmsh binaries, proprietary
application runtime, or third-party EULA-governed binary dependencies are bundled
in the repository contribution. Local-only historical evidence is excluded and
is outside this licensing statement. A separately built worker image installs
dependencies governed by multiple licenses; the aggregate image is not uniformly
MIT-licensed. These notices do not replace any component's actual terms.

## Principal dependency inventory

Versions below identify the image specification, not a complete inventory of an
image rebuilt later. Wildcard patch versions, transitive Python dependencies,
wheel-bundled libraries, and Ubuntu package revisions must be resolved and
recorded from the exact artifact to be redistributed.

| Component | Specified version or identity | License and upstream license reference |
| --- | --- | --- |
| OpenFOAM Foundation OpenFOAM 14 | DEB **20260724**; reported build **14-7b05503f98a8** | **GPL-3.0-or-later**; [OpenFOAM-14](https://github.com/OpenFOAM/OpenFOAM-14), upstream [COPYING](https://raw.githubusercontent.com/OpenFOAM/OpenFOAM-14/master/COPYING) and individual source headers. |
| Gmsh | **4.13.***; the included reference license is from release **4.13.1** | **GPL version 2 or later, with the upstream special linking exception**; complete [release LICENSE.txt](https://raw.githubusercontent.com/live-clones/gmsh/gmsh_4_13_1/LICENSE.txt), reproduced in [Gmsh-4.13-LICENSE.txt](LICENSES/Gmsh-4.13-LICENSE.txt). Not GPL-3.0-only. |
| NumPy | **2.4.6** | **BSD-3-Clause**, copyright (c) 2005-2025, NumPy Developers; upstream [LICENSE.txt](https://raw.githubusercontent.com/numpy/numpy/v2.4.6/LICENSE.txt). Binary wheels can contain additional libraries with separate notices and licenses. |
| pydantic | **2.13.4** | **MIT**, copyright (c) 2017 to present Pydantic Services Inc. and individual contributors; upstream [LICENSE](https://raw.githubusercontent.com/pydantic/pydantic/v2.13.4/LICENSE). |
| pydantic-core | Exact version resolved with pydantic; record it from the rebuilt artifact | **MIT**, copyright (c) 2022 Samuel Colvin; upstream [LICENSE](https://raw.githubusercontent.com/pydantic/pydantic-core/main/LICENSE). Preserve the license and any bundled-component notices for the resolved release. |
| Matplotlib | **3.10.***; record the exact resolved patch release | **Matplotlib license, based on the PSF license**, with historical Matplotlib Development Team and John D. Hunter terms and separate bundled-software/font licenses; [official licensing documentation](https://matplotlib.org/3.10.0/project/license.html), reference [LICENSE/LICENSE](https://raw.githubusercontent.com/matplotlib/matplotlib/v3.10.0/LICENSE/LICENSE), and upstream [LICENSE directory](https://github.com/matplotlib/matplotlib/tree/v3.10.0/LICENSE). Not a blanket MIT grant. |
| Ubuntu base and operating-system dependencies | Ubuntu **24.04** base; exact installed Debian package revisions must be inventoried | **Individual package licenses and copyrights**, not one license for the whole OS; see installed `/usr/share/doc/*/copyright`, package source metadata, and the [Ubuntu package archive](https://packages.ubuntu.com/noble/). |

The pydantic-core main-branch link and Matplotlib 3.10.0 links are reference
locations, not immutable provenance for a resolved later build. Match the exact
release or source revision and license content to every distributed artifact.

### Foundation OpenFOAM 14

This worker uses the **OpenFOAM Foundation** distribution, not the similarly
named OpenCFD distribution. Its pinned package input is
[openfoam14_20260724_amd64.deb](https://dl.openfoam.org/ubuntu/dists/noble/main/binary-amd64/openfoam14_20260724_amd64.deb).
The specified SHA-256 is
`1dfa8d381011342ca5c2496c07402fb85a1bacd9b8600b2cc701afab42e23f59`.
The reported build identifier is **14-7b05503f98a8**. These identifiers do not,
by themselves, establish that a complete matching source distribution has been
retained or made available.

The Foundation's upstream license grant permits GNU GPL version 3 or, at the
recipient's option, any later version. The complete GNU GPL version 3 text is
included in [LICENSES/GPL-3.0-or-later.txt](LICENSES/GPL-3.0-or-later.txt), from
the [SPDX license-list text](https://raw.githubusercontent.com/spdx/license-list-data/main/text/GPL-3.0-or-later.txt).
Retain the upstream copyright notices in source files and cases as well as
the package's installed copyright/license material, including the upstream
`/opt/openfoam14/COPYING` when present. The generic GPL text does not replace
those copyright notices.

### Gmsh 4.13 and its exception

The complete, unabridged Gmsh 4.13.1 release license is included in
[LICENSES/Gmsh-4.13-LICENSE.txt](LICENSES/Gmsh-4.13-LICENSE.txt). It contains
both the **GNU GPL version 2 text** and the **version 2-or-later grant with the
special linking exception**. The 4.13.* installation constraint does not pin
the selected patch release; check the license shipped with that exact release.

The exception permits combining Gmsh with code in the standard releases of
**Netgen, METIS, OpenCASCADE, and ParaView** under the conditions in the original
text. In particular, the terms of the GNU GPL for Gmsh and the other code's own
licenses still apply, and the exception requires inclusion of that other code's
source when and as the GNU GPL requires source distribution. Authors of modified
Gmsh versions are not obliged to carry the exception forward. The full included
text, not this description, governs. Do not omit the exception, treat it as a
general proprietary-linking permission, or assume it replaces the separate
licenses of components actually bundled in a Gmsh wheel.

### Python wheels, bundled libraries, and operating-system packages

For the actual installed environment, inspect each distribution's metadata and
license files under `/opt/physics-venv/lib/python3.*/site-packages/`. Depending
on the distribution and packaging version, these can be in a `.dist-info/licenses/`
directory, older `.dist-info/LICENSE*` files, or package-specific data paths.
Record the actual paths and preserve the complete texts; the examples here
are not a claim that one metadata layout covers every installed wheel.

- **NumPy:** retain its BSD-3-Clause license and the additional notices included
  in the selected wheel, including any bundled numerical libraries and compiler
  runtimes. NumPy's source license alone is not a complete wheel-license inventory.
- **pydantic and pydantic-core:** retain both projects' MIT copyright and
  permission notices. Record the exact pydantic-core version and inspect its
  distributed notices and transitive dependencies rather than assuming that the
  top-level pydantic license covers everything installed with it.
- **Matplotlib:** retain its complete Matplotlib/PSF-derived and historical
  licenses, plus bundled font and other third-party notices. Inventory its
  transitive Python dependencies separately.
- **Gmsh:** retain the wheel's own license and any bundled native-library notices
  in addition to the complete reference release license included here.
- **Ubuntu:** retain the relevant `/usr/share/doc/*/copyright` material and
  inventory the source-package identities, versions, patches, and required
  source-delivery arrangements for the exact installed binaries. The copyright
  directory is not itself proof that corresponding-source requirements are met.

## Source distribution versus binary/image redistribution

Publishing this source-only entry or a host-package wheel that contains only the
independent wrapper does not, by itself, distribute the OpenFOAM or Gmsh binaries
installed separately by an image build. Preserve applicable upstream notices for
any third-party source material actually included. If dependencies are later
vendored or bundled into a wheel or source archive, reassess that artifact's
contents and obligations rather than assuming this source-only inventory applies.

Conveying a built image or other artifact containing OpenFOAM, Gmsh, or other
third-party binaries is different. The **distributor** is responsible for
meeting each applicable license's conditions, including any requirement to
provide complete matching corresponding source by a permitted method. For the
GPL-covered components, consult GNU GPL version 3 section 6 and GNU GPL version 2
section 3, as applicable. Account for downstream changes, required build and
installation scripts, and other required source or installation information.
Observe the Gmsh exception's own conditions for other code in a combined system.

An upstream repository URL, binary package URL, version string, package manifest,
or copy of a license is **not complete proof** of corresponding-source availability
or fulfillment of redistribution obligations. Verify that recipients can obtain
the exact required source and that availability, access directions, any permitted
written offer, and retention commitments meet the selected distribution method.
These notices do not themselves constitute a written source offer or certify
license compliance.

## Required checks before publishing an image

**Do not push or publish an image until legal/license and provenance checks for
the exact rebuilt artifact have been completed.** At minimum:

1. Record the immutable image/base digests, exact Debian and Python package
   versions, wheel identities and hashes, bundled native libraries, and their
   source provenance. In particular resolve Gmsh 4.13.*, Matplotlib 3.10.*,
   pydantic-core, and all transitive dependencies. The Python and Debian package
   inventories produced by the build are inputs, not an exhaustive SBOM or a
   license certification.
2. Verify and preserve every applicable copyright, license, exception, and
   redistribution notice from the actual packages and bundled components. Add
   any missing material before publication; this principal-component list is
   not exhaustive.
3. Verify and document the complete, exact corresponding-source delivery method
   and any required offers, notices, build scripts, downstream patches, and
   installation information. Do not rely solely on moving upstream URLs.
4. Verify that the host package's [LICENSE](LICENSE), this
   [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and the complete
   [GPL version 3](LICENSES/GPL-3.0-or-later.txt) and
   [Gmsh release license](LICENSES/Gmsh-4.13-LICENSE.txt) are retained in source
   archives and wheels and copied into `/opt/physics-src/` in the image, with the
   two upstream texts in its `LICENSES/` subdirectory. Verify the resulting
   artifacts, not just the packaging configuration. Retain the dependencies'
   own installed licenses too.
5. Confirm that externally installed Microsoft Discovery and CLIO application
   products have not been vendored. Their separate product licenses are not
   replaced by this package's MIT license.

This document records scope, attribution, and outstanding distributor checks.
It is **not** an exhaustive legal certification or a statement that license
review or approval is complete.