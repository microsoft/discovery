# Hardware Specification Development

Retrieve official product and design information and turn it into an
evidence-grounded Markdown specification for hardware design planning.

## Overview

This agent supports component specifications, FPGA/SoC and digital-IP functional
specifications, and application-level specifications using Microchip products.
It distinguishes vendor-defined behavior, user requirements and proposed design
decisions. It does not implement RTL, firmware or hardware unless separately
requested.

## Architecture

The prompt uses a deployer-supplied language-model deployment and the tools
actually exposed by its host. It discovers supported product-search,
documentation, compliance and file-handling capabilities at runtime rather than
assuming fixed MCP tool names.

Inputs are a product or design interest, selected part/core and revision when
known, relevant local evidence, constraints and the desired destination. Outputs
are source-grounded requirements, citations, acceptance criteria and explicit
open issues in a local Markdown specification.

This package has no custom container tool. `associated_tools` is empty;
Discovery-injected tools are permitted, but this definition does not by itself
connect an MCP server, grant filesystem access or provide product retrieval.
The original local-only tool-catalog grant and machine-specific source identifier
are intentionally not part of this portable catalog definition.

## Prerequisites

Provide a compatible model deployment and a host with authorized tools for
official product/document retrieval and local file reading/writing. For
Microchip-related work, connect a suitable product/documentation MCP server or
equivalent supported tools. The runtime must expose the relevant tool inventory.

Select the exact part/core and document revision before treating a
device-specific specification as definitive. Provide any confidential evidence
through approved local or host-managed access; the agent must not upload it
without authorization.

## Configuration

| Input | Configuration |
|---|---|
| `{{CHAT-MODEL}}` | Name of the deployer's model deployment. |
| Product/document tools | Connect and authorize appropriate tools in the target host; no endpoint or credentials are embedded here. |
| Local files | Grant only the read/write access necessary for the requested evidence and output directory. |
| User confirmation | `humanInTheLoop` is enabled for consequential missing-input and overwrite decisions. |
| Output location | Defaults to `knowledge/<target>-spec.md` relative to the project root unless the user supplies another destination. |

The instructions require selection against live tool descriptions and schemas.
Do not substitute a remembered tool name, local catalog source ID or undocumented
REST path when a capability is unavailable.

## Usage

Load the agent in a compatible Discovery environment, supply its model
deployment, and connect the required retrieval and file tools.

Example requests:

- "Find Microchip components suitable for my interface requirements, then let
  me select a part before writing its specification."
- "Create an IP functional specification for this selected core and handbook
  revision, with cited ports, registers, reset behavior and unresolved issues."
- "Use these local datasheets to write a component specification in
  `knowledge/selected-component-spec.md` without overwriting existing files."

The agent establishes scope, retrieves governing official documents and errata,
reconciles revisions, writes the specification, then checks that the file is
nonempty and its local source links resolve. It returns a workspace-relative
link and identifies whether the result is complete or partial.

## Output Contract

Applicable sections include identity and scope, evidence and provenance,
functional requirements, interfaces and configuration, operating behavior,
registers, limits and implementation constraints, integration guidance,
acceptance checklist, open issues and sources.

Requirements have stable identifiers and measurable acceptance criteria.
Vendor capabilities, user requirements, recommendations and unexecuted acceptance
tests remain distinct. Procurement observations are dated rather than treated
as permanent design requirements.

## Known Limitations

This is a portable prompt definition, not a bundled product-data service.
Retrieval and persistence depend on the target host's authorized capabilities.
No connection or deployment smoke test is implied by catalog format validation.

If governing documents cannot be read, the agent must identify available
evidence and consequential gaps. It must not invent register maps, budgets,
licensing rights, tool failures or vendor equivalence. A partial specification
is explicitly labeled; creating a file does not establish engineering correctness.

The agent does not run simulation, implementation or additional reports merely
to author a specification. It must not overwrite existing documents, install
software or transmit confidential requirements without authorization.

## Contributing

See [CONTRIBUTING.md](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md)
and the
[agent authoring guide](https://github.com/microsoft/discovery/blob/main/docs/authoring-guides/agent-authoring-guide.md).
