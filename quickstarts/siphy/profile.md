# SiPhy runner profile

Guide [README.md](README.md); exact [prompt](prompts/hero.txt). Draft scope is
the owner CoreSPI-inspired workflow. No automatic fallback to another chip
scenario. Missing publication, permissions, model configuration and corpus
rights are blocking requirements, not details for a customer to invent.

## Prepare before execution approval

1. Verify source archive/skill hashes and exact component versions. Do not copy
   the entire working project, cache folders or unreviewed agent implementations.
2. Detect OS/architecture and Docker/Podman readiness; inspect images only.
   Build/pull only approved sources after separate setup approval; record digests.
3. Verify runtime discovery/activation and tool access for all four agents,
   report-gen, Microchip MCP and Design-Best-Practices. No self-granted tools.
   The spec agent's probe is an agent invocation and needs disclosed approval.
4. Obtain approved corpus access/indexing; verify document text and source-bound
   retrieved passages. Do not proceed without required grounding.
5. If `knowledge/CORESPI_HB.md` exists, record its hash and ask keep-and-append
   versus backed-up replacement. Resolve contract scope with the owner/user.
6. Ask mode and bounded execution approval, with the scientific and repair scope.

## Fixed agent sequence

1. `hardware-spec-dev`: retrieve the official handbook through the required
   MCP route; create the source-grounded CoreSPI reference specification and
   retrieval record. Verify handbook revision and source hash. A direct download
   fallback must retain a failed MCP check and cannot yield overall PASS.
2. `hardware-spec-dev`: produce/freeze the CORESPI_HB implementation contract,
   preserving any protected preexisting requirements. Resolve consequential
   ambiguities before design, never by silently inventing vendor behavior.
3. `chip-rtl-design`: implement the agreed contract and execute native design
   checks. Capture final RTL SHA-256 and actual tool artifacts.
4. `chip-rtl-lint`: default lint and canonical formatting on immutable RTL;
   zero violations/unformatted files, no waivers. Preserve proposed fixes.
5. `chip-functional-verification`: independent self-checking testbench from the
   contract; run simulation and capture VCD, logs and comparison counts.

The owner skill permits at most one retry outside its repair cycle and at most
three design/lint/verification cycles. Only a DUT-attributed failure restarts
steps 3–5; testbench-only defects stay within step 5. Re-run all affected checks
on the identical final RTL hash. Record each attempt; never hide a failed check.
No parallel agent dispatch, substitute agents or extra scientific stages.

## Final evidence

All owner-required checks in the guide must pass, including tool connection and
Bookshelf use. Keep separate contract, RTL, independent testbench, waveform,
design/lint/simulation evidence and report-gen output under `results/<id>/`;
the declared protected knowledge contract is the exception. Do not make fake
tool receipts or use file existence alone as proof. Retain all limitations and
unresolved gaps. Stop on exhausted repair bounds or user cancellation.