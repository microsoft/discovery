# SiPhy — start here

Generate and verify RTL from a hardware specification using the
**[SiPhy v1.1 QuickStart guide](QuickStart-Spec-to-RTL.md)**.

## Requirements

- Discovery with the guide's parent model, `gpt-6.1-sol`, and four chip agents.
- Docker with a working Linux engine and access to the required image and
  package sources. The archive contains build contexts, not prebuilt images.
- Python 3.10 or later for report generation; the reference used 3.13.17.
- A working Microchip Catalog connection and the required agent tool grants.

See the full guide for the tested environment and configuration. The reference
run did not capture a portable Catalog endpoint/authentication configuration;
verify the connection in your project rather than relying on the older archive
settings. On restricted networks, use an organization-approved dependency source.

## Start

1. Download the full guide and [ship.tar](files/ship.tar) into a new short local
  folder. Verify the archive checksum under [Supporting files](#supporting-files).
2. Open/create a Discovery project there and start a new session.
3. [Load the shared runner](../../skills/quickstart-runner/README.md), attach
  the full guide, and send:

> Use the quickstart-runner skill to follow the attached SiPhy v1.1 QuickStart
> from the supplied tar package. Treat the full guide as authoritative over
> older archive and skill instructions. Check readiness and obtain the required
> setup and execution decisions before running the four chip specialists.

4. Approve extraction and setup separately from execution. Follow the guide's
  destination layout: the archive's `dot-github` contents belong in the new
  project's `.github` folder. Confirm agents, skills, tool grants, and images
  are active before running.
5. After setup, approve execution and use the exact prompt in guide section 6.
  The sequence is specification, parent-prepared contract, RTL design,
  lint/formatting, independent verification, and reporting.
6. Check the native design, lint, and simulation results against the same final
  RTL, together with the report and the guide's acceptance criteria.

The v1.1 guide takes precedence over older archive instructions. Bookshelf use
is an optional, separately unvalidated variant, not a requirement of the v1.1
reference run. Reference results reused an authorized contract and prior RTL;
they do not establish a fresh-contract run or physical/timing signoff.

## Supporting files

Download **[ship.tar](files/ship.tar)**, unchanged: **40,992,256 bytes**,
SHA-256 `f06834009e5e28b0c2cb18f3b7ff5227d1cb8ee2ecbd84f41eda157f8907159c`.
Select **Download raw file** on the file page, or obtain it in a repository
checkout. Preserve the archive and its original source notices.

### Archive contents

- Setup README with the original setup procedure.
- Four agent definitions in `ship/dot-github/agents/`.
- Supplied report-gen and installation skills in `ship/dot-github/skills/`.
- Three chip-tool build contexts in `ship/discovery_catalog/`.
- Forty research PDFs and their README/manifest in `ship/knowledge/bs_data/`.

Bundled papers retain their original terms and attribution. The archive does
not include a configured connection, an indexed Bookshelf, or prebuilt images.

### Optional original runner

The [original scenario skill](skill%201.md) is preserved for reference or
explicit testing of that version. It is **not required** when using the shared
runner. Do not run both runners in sequence. Its older CoreSPI profile differs
from v1.1 on Bookshelf use, prompt wording, and orchestration; resolve conflicts
before using that variant.

### Reference evidence

Five guide links point to reference-run artifacts not included in the package:
the retrieval record, results summary, dispatch history, final HTML report,
and requirements matrix. The native logs, final RTL/testbench/waveform, and
reused contract are also not supplied as reference outputs. Evaluate new runs
using their own artifacts and the guide's acceptance criteria.