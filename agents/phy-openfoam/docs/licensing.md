# Licensing and third-party boundaries

This page explains the intended component boundaries and review requirements.
It is **not legal advice, a blanket compliance approval, or permission to publish
an image**. Source contribution, container redistribution, and use of external
vendor products are different activities with different obligations.

## Independently authored host source

The entry's independently authored host/tool source is distributed under **MIT**,
matching the Microsoft upstream repository's root license. The entry and tool
each carry an MIT license text for standalone distribution:
[LICENSE](../LICENSE) and [tools/openfoam/LICENSE](../tools/openfoam/LICENSE).
The Python package remains `discovery-physics-openfoam`; changing the agent/skill name to
`phy-openfoam` does not relicense dependencies or third-party fixtures.

The implementation is independent of CFD Forge. The
[paper](https://arxiv.org/abs/2610.14104) is a research reference, not a bundled
code/data/container dependency. Reconstructed benchmark inputs must retain
their actual provenance; do not imply endorsement or exact reproduction of the
paper's original artifacts.

## Solver, geometry, and aggregate image

| Material | License boundary |
|---|---|
| Independently authored Python host/tool code | MIT, subject to the supplied license text |
| OpenFOAM Foundation 14 | GPL-3.0-or-later; preserve the Foundation's notices and applicable source obligations |
| Gmsh 4.13 | GPL-2.0-or-later with its upstream special linking exception; preserve the complete release license and review associated components |
| Base OS, Python, NumPy, Pydantic, Matplotlib, and system/transitive packages | Their own licenses and notices; inventory the actual image, not just direct requirements |
| Imported/tutorial-derived Foam dictionaries or fixture content | Preserve existing copyright/license headers and review the specific content's provenance |

See the authoritative upstream resources for
[OpenFOAM](https://openfoam.org/licence/) and
[Gmsh](https://gmsh.info/). The image uses the Foundation distribution, not an
interchangeable OpenCFD release. Review its
[Dockerfile](../tools/openfoam/Dockerfile) and
[package metadata](../tools/openfoam/pyproject.toml) alongside
[THIRD_PARTY_NOTICES.md](../tools/openfoam/THIRD_PARTY_NOTICES.md) and the
[full GPL-3.0-or-later license text](../tools/openfoam/LICENSES/GPL-3.0-or-later.txt)
and [complete Gmsh release license and exception](../tools/openfoam/LICENSES/Gmsh-4.13-LICENSE.txt).

The aggregate image/action metadata uses **`MIT AND GPL-3.0-or-later AND GPL-2.0-or-later`** because
multiple components and obligations coexist. This does **not** mean all source
is dual-licensed, that recipients may choose MIT for OpenFOAM/Gmsh, or that the
independent host code is automatically GPL merely because it invokes a separate
solver. Component separation and any derivative-work question require review
of the actual distribution, not inference from one metadata string.

## Source-only catalog contribution

The public source entry does not include installed OpenFOAM or CLIO binaries,
vendor installers, virtual environments, exported images, credentials, or
signing keys. Build instructions download dependencies from upstream sources;
recipients install external engines and Discovery independently.

Keep all required MIT texts, the tool's third-party notices, the full
GPL-3.0-or-later text, and Gmsh's full license including its exception in the
source contribution. Preserve upstream
copyright/license headers in Foam dictionaries and fixtures even when the
surrounding file is generated. Do not replace every header with Microsoft/MIT
as a packaging cleanup. Source-only scope does not erase obligations for any
third-party material actually copied into the entry.

## Before redistributing an image

1. Inventory the **exact** base, OS packages, Python packages, solver, geometry
   libraries, and transitive dependencies in the built image. Preserve package
   inventories and immutable image identity; a top-level license label is not
   an exhaustive SBOM or notice inventory.
2. Retain the actual corresponding source, applicable patches, build scripts,
   and other required build information for redistributed GPL components, and
   establish a compliant recipient-access/source-delivery mechanism. Do not
   assume a generic link or a checksum alone satisfies those obligations.
3. Supply the applicable license texts and attribution, including notices for
   the OS and non-GPL dependencies. Confirm that notice/license files are
   actually included in the redistributed image or its approved accompanying
   materials, not merely present somewhere in a development checkout.
4. Review the intended image publication and source-distribution plan with the
   responsible compliance/legal maintainers. Confirm registry permissions and
   publisher identity independently of catalog metadata.
5. Complete vulnerability, provenance, isolation, and deployed-route review;
   licensing review alone is not security or production sign-off.

The base digest and Foundation package checksum are pinned, but apt and some
transitive versions float. A later build can contain different dependencies;
regenerate the inventory and review it rather than claiming fully reproducible
or pre-approved redistribution.

## External product terms and trademarks

Podman/Docker, Discovery/CLIO, cloud services, registries, and model access are
installed, licensed, and authenticated independently. This source package does
not redistribute those products or grant their use rights. Product names and
existing publisher fields do not establish endorsement or first-party approval.
For source contribution scope, see [distribution](distribution.md); for sensitive
information, see [SECURITY.md](../SECURITY.md).