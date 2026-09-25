# FlowBlind Research Teammate v2

## Overview

FlowBlind Research Teammate v2 is a catalog-native, deterministic research
agent for preparing and verifying one reviewed study from exact
host-selected data. It publicly supports two method families:

- regional agreement for paired reference and candidate planar CSV data; and
- vector/time readiness for structured planar vector CSV data or time series.

The package exposes exactly two public tools and actions. Preparation is
result-free and does not require confirmation. Scientific execution happens
only in a later invocation of the confirmed run tool.

This contribution is source-only. It does not deploy or activate the agent,
publish its images, establish live-service acceptance, or supersede another
version. The `publisher.party: 1p` value and Microsoft support contacts in
`metadata.yaml` are proposed catalog metadata and remain subject to explicit
catalog review before merge.

## Usage

1. Configure the model deployment and the two tool resource IDs described in
   [Configuration](#configuration).
2. Select one immutable input resource named `candidate.csv`.
3. Ask the agent to prepare either a regional-agreement study or a vector/time
   readiness study. The agent calls `prepare-study`, which has confirmation
   disabled, validates the selected input, and publishes a result-free,
   content-addressed preparation asset.
4. Review the declaration preview. Preparation must stop without running the
   study in the same model turn.
5. In a later explicit request, select the original `candidate.csv` and the
   unchanged promoted preparation directory. The agent calls
   `run-and-verify-study`, for which confirmation is enabled.
6. If the confirmation is approved, the tool revalidates the exact bindings,
   runs only the prepared method, verifies deterministic replay, and publishes
   marker-last JSON, Markdown, HTML, and receipt evidence. If confirmation is
   cancelled, execution stops.

Example preparation requests:

- "Prepare a regional agreement study comparing the reference and candidate
  values in this file."
- "Prepare a vector/time readiness audit for this planar velocity time
  series."

Example later run request:

- "Run and verify the study I prepared from the selected candidate file."

## Prerequisites

- A Microsoft Discovery environment with an Azure AI Foundry chat-model
  deployment.
- The two container images built from the package Dockerfiles and published to
  the deployment's Azure Container Registry using the versioned image names in
  each `tool.yaml`.
- A Linux AMD64 container runtime that can enforce a read-only root filesystem,
  read-only input mounts, a writable invocation-scoped `/output` mount, no
  runtime network, and a bounded `/tmp:rw,noexec,nosuid,nodev` tmpfs.
- For image construction only, access to the official Python Package Index.
  Python wheels are hash-pinned; runtime execution requires no network.
- An immutable `candidate.csv` whose columns and scientific metadata match one
  of the two public method families.
- A host implementation that binds confirmation to the exact invocation,
  attachment identities, and promoted preparation asset.

The runtime requires no Git repository or repository metadata.

## Architecture

The public lifecycle is deliberately split across two host-owned boundaries:

```text
scientist intent + candidate.csv
            |
            v
prepare-study (confirmation Disabled)
            |
            v
result-free content-addressed preparation
            |
     later explicit request
            |
            v
run-and-verify-study (confirmation Enabled)
            |
            v
verified marker-last report and publication receipt
```

Preparation reads only `candidate.csv` from the input mount. Execution reads
that same file plus the unchanged
`flowblind-preparation-<preparation-sha256>/trusted-sidecar.json` and
`preparation.json`. Alternate relative paths are rejected. The public
candidate dataset is never copied into the output.

Both tool images contain the same attested runtime tree. The package verifier
checks the retained manifests, source allowlist, release policy, package lock,
and exact runtime bytes before issuing process-local authority. That authority
shows that the reviewed facade was selected; it is not evidence of the human
confirmation decision. Direct container or command-line invocation is a
conformance interface, not a supported live authorization path.

### Private hidden-flow boundary

The retained finite-basis hidden-flow method is supported as a private method,
and its exact bytes are intentionally bundled in both public tool images
because private preparation and private confirmed execution share this
two-action package. No hidden action, tool, or mapping is advertised by
`metadata.yaml`, `agent.yaml`, or either public `tool.yaml`.

This is a routing and access boundary, not secrecy: possession or inspection of
the image can reveal the private bytes. Activation requires the exact,
separately approved and allowlisted private overlay plus successful completion
of `V2-LIVE-004`. Public demonstrations keep this route disabled. The internal
scenario harness and hidden declaration facade are conformance surfaces, not
public Discovery actions.

## Tools

| Tool folder | Public action | Confirmation | Purpose |
| --- | --- | --- | --- |
| `flowblind-prepare-study-v2` | `prepare-study` | Disabled | Selects one advertised method, validates the exact host-selected `candidate.csv`, and publishes a deterministic result-free preparation asset. |
| `flowblind-run-and-verify-study-v2` | `run-and-verify-study` | Enabled | Revalidates the selected candidate and preparation, runs only the routed method after host confirmation, verifies replay, and publishes marker-last evidence. |

There are no other public tools or actions. The internal report-resource facade
is not registered as a Discovery tool.

## Configuration

### Deployment parameters

| Parameter | Required | Description |
| --- | --- | --- |
| `{{CHAT-MODEL}}` | Yes | Azure AI Foundry chat-model deployment used by the prompt agent. |
| `{{flowblindPrepareStudyV2ToolId}}` | Yes | Resource ID for `flowblind-prepare-study-v2`; wired with confirmation disabled. |
| `{{flowblindRunAndVerifyStudyV2ToolId}}` | Yes | Resource ID for `flowblind-run-and-verify-study-v2`; wired with confirmation enabled. |

Keep the schema-standard image tags in the tool definitions:

- `{name}.azurecr.io/flowblind-prepare-study-v2:2.0.0`
- `{name}.azurecr.io/flowblind-run-and-verify-study-v2:2.0.0`

### Scientific parameters

`researchGoal` is the only field required for every preparation. The selected
method then requires the matching scientific declarations:

| Method or scope | Parameters |
| --- | --- |
| Shared optional context | `decisionQuestion`, `nextEvidenceIntent` |
| Regional agreement | `quantity`, `referenceMeaning`, `candidateMeaning`, `coordinateUnit`, `valueUnit`, optional provenance and license |
| Vector/time readiness | `quantity`, `vectorMeaning`, `vectorSourceKind`, `coordinateUnit`, `valueUnit`, `samplingKind`, optional time/exposure/cycle declarations, provenance, and license |

The preparation schema is a flat catalog projection of the authoritative
method-specific union. The runtime rejects missing declarations, mixed-family
fields, incompatible units, alternate file names, and technical controls
supplied as scientist input.

The run action accepts only the scientist-authored context recovered from the
preparation asset. Paths, hashes, byte lengths, package IDs, method IDs,
approval values, confirmation flags, mount URIs, and receipts remain
host-owned controls.

## Known Limitations

- Only regional agreement and vector/time readiness are publicly advertised.
- Results are descriptive scientific evidence, not acceptance, robustness,
  clinical, uncertainty, solver-verification, or globally-best-region
  verdicts.
- Vector/time readiness does not infer point-time meaning for frame averages,
  claim derivatives on unstructured data, or report wall shear without
  explicit wall evidence.
- Report URIs require the approved host resolver and the retained output root;
  URI possession alone is not resource authority.
- Package-local and container tests do not establish deployment or live-service
  acceptance. `V2-LIVE-001` through `V2-LIVE-004` remain separate manual gates.
- The local Windows 11 demonstration, `V2-LIVE-001` through `V2-LIVE-003`
  evidence, and demonstration video are separate artifacts and are not implied
  by this catalog contribution.
- The private hidden-flow route remains disabled for public demos and cannot be
  activated without the exact separately approved and allowlisted overlay and
  `V2-LIVE-004`.

## Contributing

Follow the repository's
[Contributing guidelines](../../CONTRIBUTING.md) for catalog changes. Use the
public [Microsoft Discovery issue tracker](https://github.com/microsoft/discovery/issues)
for support and catalog feedback. Security issues must follow the repository's
coordinated-disclosure process instead of being filed publicly.
