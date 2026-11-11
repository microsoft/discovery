# QuickStart Scenarios — SiPhy

**Draft; source components and corpus are not yet a public-ready package.**
This is Joe's CoreSPI-inspired specification-to-verified-RTL scenario, not the
separate chip-synthesis/timing demonstration in a starter kit.

## 1. Scenario identity

Create a source-grounded reference specification, an implementation contract,
synthesizable RTL, independent self-checking testbench, waveform and report.
Owner source is the supplied hardware-workflow archive and separate
`quickstart-siphy-spec2rtl-1` skill. A completed owner nine-section guide and
publishable reference-run artifacts were not found in that archive. This is a
packaging adaptation for owner review, not a claim that those artifacts exist.

## 2. Configuration matrix

| Component | Owner-defined route |
| --- | --- |
| Agents | `hardware-spec-dev`, `chip-rtl-design`, `chip-rtl-lint`, `chip-functional-verification`, in that order (spec agent used twice). |
| MCP | Microchip documentation endpoint `https://api.microchip.com/mcp/resources`; exact destination connection/source ID must be observed and bound, never copied from the author's machine. |
| Bookshelf | `Design-Best-Practices`, exact owner corpus; required grounding is not optional. |
| Containers | `rtl-design`, `rtl-lint`, `functional-verification` build contexts in the owner package; recorded tags were mutable `latest`, immutable images not supplied. |
| Skills | Shared runner plus owner `report-gen`; archive also supplies `discovery-add-agents`. Check compatibility before replacing it with a canonical installer. |
| Model/App settings | Required model revision and full configuration not captured in inspected materials; owner confirmation needed. |

None of these four exact chip agents is present under `agents/` at the
inspected upstream revision `88a2a1cd1664b7d609659dc86c65f7f632686715`. They
remain unpublished dependencies, not fake repo links and not substitutes for
Yosys/OpenSTA catalog agents. The shared runner does not publish them for Joe.

## 3. System requirements

Owner skill names a Windows 11 x64 Docker Desktop reference; other scenario
platforms are unvalidated. Docker Linux engine or an approved compatible Podman
route, network access to base images/packages and the MCP endpoint, Python
3.10+ for report rendering. Actual hardware, cold-build minimums and tested
backend settings need owner evidence. No automatic container installation.

## 4. Prerequisites

[assets.json](assets.json) inventories the source archive and original skill.
[Corpus inventory](data/corpus.csv) records the exact 40 PDF filenames, sizes
and hashes from the supplied manifest. Their combined size is 35,070,863 bytes.
Public accessibility is **not** blanket permission to redistribute; the source
manifest expressly makes no collection-wide licence claim. No PDFs or archive
are committed here. Public rights and acquisition remain blockers.

The source README warns that one agent instruction contains a machine-specific
MCP source identifier. Replace that assumption with a supported runtime binding,
after explicit configuration approval. Never invent IDs or self-grant tools.

## 5. Setup

Use [the common start guide](../GETTING-STARTED.md). Once publication/owner gates
are resolved: configure the four exact agents, their reviewed build contexts,
Microchip MCP access and the required Bookshelf through supported App flows.
The source archive's `dot-github` is a transport folder; its contents belong in
the destination's supported project-skill/agent locations, not a literal
`dot-github` runtime directory. Copying definitions does not grant tool access.

Obtain separate approvals for acquisition, image setup, capability binding,
corpus indexing and agent execution. Verify the MCP lookup from the intended
agent and actual Bookshelf passages before proceeding. Index success alone is
not proof that papers were parsed. Record source hashes, image IDs/digests and
corpus/index settings; do not silently update a stale mutable image tag.

## 6. Fixed prompt and matching output

[Owner prompt](prompts/hero.txt) is exact text from the source README (including
its original spelling), normalized to LF with a recorded digest. Selecting
“Recommended” inside this prompt is not a blanket grant for installations,
new scope, authentication or tool permissions.

Required owner checks: all four agents execute; the spec agent successfully
uses the Microchip MCP connection; all chip agents consult the Bookshelf;
Verilog design/testbench files exist; lint and verification container tools
actually execute; design checks, default lint, formatting and simulation pass
on the identical final RTL; waveform/logs and final `report-gen` HTML are
produced. Inspect native tool evidence, not prose alone.

Historical owner evidence reported a failed required MCP route and a direct
vendor-download fallback. That is a failed original check, not an all-check
pass. No vendor-equivalence, CDC/RDC, timing or physical signoff is claimed.

## 7. Runtime

Owner-reported approximately 54 minutes with images already built, and about
two minutes for one Bookshelf-index build. These are historical observations,
not fresh verification or cold-machine benchmarks. Image-build duration and
full clean-start elapsed time are unknown.

## 8. Troubleshooting and cleanup

Resolve missing tool grants, corpus rights/readability and image sources before
execution; do not silently fallback or downgrade owner checks. Keep every repair
attempt and bind verification to the exact final RTL hash. Preserve an existing
implementation contract unless an explicit backup/replacement decision is made.
Only approved run-owned files/resources may be cleaned up.

## 9. Publication checklist

- [ ] Exact agents/tools/report skill available from approved public sources.
- [ ] All paper rights and acquisition links confirmed.
- [ ] Owner accepts completed template/profile and model/environment settings.
- [ ] MCP-required path passes; real reference outputs provided.
- [ ] Fresh-project skill activation and bounded E2E run verified.

See [file accounting](FILES.md), [profile](profile.md) and
[manifest](scenario.json). Do not mark this scenario ready from package checks.