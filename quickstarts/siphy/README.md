# Silicon and Physics — specification to verified RTL

Generate and verify register-transfer level (RTL) hardware designs from a
specification using the **[v1.1 QuickStart guide](QuickStart-Spec-to-RTL.md)**.
The supplied materials abbreviate Silicon and Physics as **SiPhy**.

**Customer readiness:** Project preparation is automated, but this is not yet a
validated zero-configuration, five-minute customer workflow. Specialist MCP
activation, prebuilt image delivery and a fresh implementation contract remain
release gates. See the [complete step-by-step readiness audit](CUSTOMER-READINESS.md).
The original guide, archive and exact Section 6 prompt are preserved.

## Requirements

- Discovery with the guide's parent model, `gpt-6.1-sol`, and four chip agents.
- Docker or Podman with a working Linux engine and the three reviewed images.
  The archive contains build contexts, not prebuilt images; cold builds need
  separate approval and access to approved dependency sources. Rootless Podman
  must have delegated CPU, memory and process controllers; see the
  [WSL/cgroup diagnostic](CUSTOMER-READINESS.md#container-health-inspect-is-not-execute).
- Python 3.10 or later for report generation; the reference used 3.13.17.
- A working Microchip Catalog connection and the required agent tool grants.

See the full guide for the tested environment and configuration. The reference
run did not capture portable connection configuration. The current public HTTP
MCP endpoint is `https://api.microchip.com/mcp/resources`; the new preparation
path includes an importable configuration and optional diagnostic. Parent
connectivity is **not** specialist activation. On restricted networks, use an
organization-approved dependency source; do not disable TLS validation.

## Prepare a project without hand-copying configuration

Use a checkout or downloaded source ZIP of this repository, not just the two
original scenario files: the bootstrap also needs the authoritative shared
runner under `skills/quickstart-runner`. From the repository root, run:

```console
python quickstarts/siphy/bootstrap.py plan --destination C:\work\siphy-demo
python quickstarts/siphy/bootstrap.py prepare --destination C:\work\siphy-demo
python quickstarts/siphy/bootstrap.py preflight --destination C:\work\siphy-demo
```

Replace the example with a **new short project path whose parent already
exists**; on macOS/Linux use a native path such as `/home/me/work/siphy-demo`.
`plan` is read-only. Running `prepare` authorizes local file preparation only:
it verifies the pinned archive checksum and all member paths before writing,
refuses an existing destination, and records original/effective file hashes.
No administrator rights or extra Python packages are needed by the bootstrap.

The prepared project contains the four agents, the report renderer, the shared
runner, the three container build contexts, a Microchip plugin example,
the complete unchanged guide, its exact prompt in `PROMPT.txt`, and setup
instructions/provenance. Stale machine-specific grants and automatic image-build
instructions are removed from effective agent copies; archive originals are
preserved. The qualified documentation-action selector is explicitly an
**unvalidated activation candidate**, not a proven host binding fix.

`preflight` only inspects local files, Python, disk, the engine and image
identities. It never installs, builds, pulls, runs a container, indexes, signs
in, imports a plugin or edits app-private state. JSON output and exit status
describe the requested mode: exit 0 does **not** mean agents or tools are active
or the engineering workflow passed. Missing native prerequisites return exit 2.
Use `--runtime docker` or `--runtime podman` only to select an already configured
engine; automatic selection prefers a working engine with all required images.

Optional research PDFs are excluded by default. Include them only with
`--include-research` on `plan`/`prepare`; that does not index them or grant
redistribution rights.

## Activate and run

1. Open the prepared project in Discovery. Select the guide's **`gpt-6.1-sol`**
   model if available; record any approved model variant rather than silently
   claiming the reference configuration.
2. Follow the generated setup instructions to import the Microchip plugin
   through Discovery's supported tool/plugin flow and authorize the specialist's
   documentation access. Merely writing an MCP file does not register it.
   Do not copy a source ID from another project or edit internal app state.
3. Start a new/resumed chat, confirm the four agents and `report-gen` are exposed,
   and have **`hardware-spec-dev` itself** call
   `search_microchip_product_documents` with query
   `CoreSPI HB0089 handbook 5.2` and limit 10. Require an application-level
   successful response and official source link. If the action is absent,
   stop: a parent lookup or healthy connection indicator is not an alternative
   acceptance test. See the [app-owned regression](CUSTOMER-READINESS.md#minimal-app-owned-regression).
4. Load the prepared shared runner, attach the full guide, and send:

> Use the quickstart-runner skill to follow the attached SiPhy v1.1 QuickStart
> from the supplied tar package. Treat the full guide as authoritative over
> older archive and skill instructions. Check readiness and obtain the required
> setup and execution decisions before running the four chip specialists.

5. Approve bounded execution separately from setup, then use `PROMPT.txt` or the
   exact prompt in guide Section 6. The sequence is specification, parent-prepared
   contract, RTL design, lint/formatting, independent verification and reporting.
   Pause for consequential contract decisions; no private reference contract
   is included or silently inferred.
6. Require design, DEFAULT lint, canonical formatting and independent simulation
   on the same final RTL hash. Preserve every failed attempt and native log,
   and keep requirement-coverage limitations separate from native PASS.

The v1.1 guide takes precedence over older archive instructions. Bookshelf use
is an optional, separately unvalidated variant, not a requirement of the v1.1
reference run. Reference results reused an authorized contract and prior RTL;
they do not establish a fresh-contract run or physical/timing signoff.

## Diagnose the endpoint without confusing it with agent readiness

```console
python quickstarts/siphy/probe_microchip.py --output microchip-endpoint.json
```

This optional bounded network probe validates MCP initialization, tool discovery,
live input schema and documentation response without installing anything.
It refuses an existing output file and never claims specialist activation.
See [diagnostic interpretation](CUSTOMER-READINESS.md#microchip-endpoint-health-versus-specialist-access).

## Validate the preparation tools

From the repository root:

```console
python -B -m unittest discover -s quickstarts/siphy/tests -v
```

Tests use the supplied archive and local fixtures; they do not call Microchip,
build images, launch engineering containers or activate agents. Platform tests
that require unavailable OS privileges report an explicit skip. Passing these
tests is not the clean-machine or engineering acceptance gate. The dedicated
GitHub Actions workflow runs the same suite on Windows/Linux with Python 3.10
and 3.14; its results must be reviewed independently of local results.

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