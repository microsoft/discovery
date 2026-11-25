# Deployment readiness — 0.2.1 candidate

**Source packaging is not cloud deployment or production sign-off.** Use
[installation](installation.md) for the local CLI/skill route and
[distribution](distribution.md) for a source-only catalog contribution. No Azure
dispatch or production enforcement has been established by this packaging pass.

## Interfaces and evidence scope

| Interface | Implementation | Historical 0.2.0 coverage | Still unqualified |
|---|---|---|---|
| Host CLI | `discovery-physics` | Paper campaign, held-out workflows, local integrity checks | Revalidation of relocated 0.2.1; multi-user authorization |
| Container `evaluate` | `discovery_physics.service` | Local in-image freeze/solve/assess/finalize path | Actual Discovery/Azure dispatch and enforcement |
| Container `study` | Same service | Study code and local tests | Cloud action integration and durable member lineage |
| Container `lint` | Same service | Deterministic validation and local schema path | Hosted platform request |
| MPI | Frozen ranks and worker decomposition/reconstruction | Serial/two-rank channel path | Scaling and full-field parallel equivalence |
| Geometry | In-image CAD conversion | Local STEP-to-STL conversion | Robust meshing for arbitrary geometry |

See [validation history](../benchmarks/VALIDATION-HISTORY.md) for the retrospective
record. A service label of `platform-enforced (cloud container job)` is a branch
description, **not a cgroup probe or platform receipt**. The `cloud` action of the
[local path-check script](../scripts/live_paths.py) also runs locally.

## Release identities and build limits

- Entry/agent/skill: `phy-openfoam`; candidate version: **0.2.1**.
- Python distribution: `discovery-physics-openfoam`; module: `discovery_physics`;
  CLI: `discovery-physics`.
- Default local image: `localhost/phy-openfoam:0.2.1`.
- Cloud image template: `{name}.azurecr.io/phy-openfoam:0.2.1`, where `{name}` is
  an operator's approved Azure Container Registry name, not a supplied service.
- The [Dockerfile](../tools/openfoam/Dockerfile) pins the base image digest and
  Foundation package version/checksum. Apt repositories, wildcard Python
  dependencies, and transitive resolution still float. The build is **not fully
  reproducible**; retain actual package inventories and immutable image identity.
- The image installs Foundation 14's AMD64 package in an Ubuntu base. It is not
  OpenCFD's similarly named distribution and is not a qualified ARM image.

## Optional cloud configuration

The [agent manifest](../agent.yaml) and [tool manifest](../tools/openfoam/tool.yaml)
describe a deployment interface, not a completed deployment. Before any authorized
deployment, an operator must supply and review these distinct values:

| Placeholder or value | Operator responsibility |
|---|---|
| `{{CHAT-MODEL}}` | Select a supported model in the actual deployment environment |
| `{{phyOpenfoamToolId}}` | Bind the tool resource ID returned by that environment |
| `{name}` in the image template | Select the approved registry and publish a compliance-reviewed image |
| Compute and output-mount settings | Verify real allocation, isolation, output access, retention, and cost policy |

Use the [deployment example](../config/deployment.example.json) as a placeholder
worksheet and the [configuration guide](configuration.md) to keep it apart from
local operator policy. The worksheet is not automatically consumed by the local
config loader or an Azure provisioning command. Never commit substituted
credentials or private deployment state. Follow the current
[Discovery upstream documentation](https://github.com/microsoft/discovery) for
registration and deployment APIs rather than treating a local CLI call as a
hosted request. Catalog acceptance and cloud provisioning are separate approvals.

## Action payloads

The manifest declares these service actions:

| Action | Required input | Encoding |
|---|---|---|
| `evaluate` | `bundle_b64gz`, `confirmations_b64` | Base64 of gzip-compressed CaseBundle JSON; base64 JSON confirmation list |
| `study` | `spec_b64gz` | Base64 of gzip-compressed Study JSON |
| `lint` | `bundle_b64gz` | Base64 of gzip-compressed CaseBundle JSON |

For `evaluate`, `confirmations_b64` is base64 of a JSON confirmation list; `W10=`
encodes an empty list. It must not be used to bypass required user decisions.
Encoded inputs constrain transport; they do not supply user authentication.
The catalog action schema permits at most 65,536 characters per encoded string.
The service also enforces that encoded limit and caps decoded bundle/study JSON
at 16 MiB (16,777,216 UTF-8 bytes), before JSON or model validation. It accepts
exactly one complete gzip member and one JSON object; checksum failures,
truncation, concatenated members and trailing compressed bytes (including zero
padding) are refused. The raw service JSON option has the same decoded-byte cap.
This fixed action-envelope bound is separate from case-file safety limits and
accommodates the curated examples and multi-member studies; it is not a promise
that every maximum-size local bundle fits the action interface.
Larger bundles/studies need a separately designed and qualified transport rather
than increasing the catalog schema's supported limit. The local CLI reads files
and does not share these service action-argument limits.
Result mounts contain scientific reports, evidence, journals, and logs, not
platform job receipts or private signing keys. Review promoted output for
confidential geometry, absolute paths, and native session metadata.

The service runs its worker as an in-container subprocess, with no nested
container engine. Its temporary per-job HMAC key does not supply durable cloud
verification or a public signature. See [architecture](architecture.md) and
[security](../SECURITY.md).

The `study` action has no member-scoped confirmation input. Any member with a
`needs_confirmation` assumption is refused before study/member staging, with
pending parameters identified. Obtain the user's decisions through the local
interactive `study-prepare` and per-member `confirm` workflow; do not relabel an
unconfirmed assumption as user-approved to make a service request execute.
The service's result JSON is an unsigned, editable convenience response, not a
signed verdict record. Consumers must verify retained journals and pinned
artifacts with the appropriate trusted key custody; possessing that result file
or a successful hosted job is not sufficient evidence of scientific acceptance.

## Production qualification checklist — not executed

1. **Authorize publication and licensing.** Confirm publisher metadata with
  maintainers. Complete image compliance review, third-party notices,
  corresponding-source arrangements, SBOM, and vulnerability review before
  pushing an image; see [licensing](licensing.md).
2. **Separate identities.** Keep container sockets, administrator credentials,
  signing-key access, and deployment privileges away from the reasoning agent.
  Use a dedicated VM boundary for hostile workloads.
3. **Authenticate confirmations.** Enforce actual user authorization outside
  bundle-supplied audit labels. Test blocked and denied method substitutions.
4. **Retain trustworthy evidence.** Provide separate durable key custody,
  externally retained chain heads, append-only storage, and a verification
  policy covering all required ancestor/member artifacts. Never publish HMAC keys.
5. **Exercise the actual route.** Dispatch every action through Discovery/Azure.
  Retain request/job outcomes, immutable image identity, and output-mount receipts.
  Test malformed input, missing confirmation, continuation, interruption,
  cancellation, restart, and concurrency through that same route.
6. **Measure enforcement.** Demonstrate CPU, memory, PID, disk, and wall-clock
  behavior and absence of worker network, credential, and socket exposure.
  Neither an unenforced-limit opt-in nor a status label is proof of enforcement.
7. **Qualify scientific scope.** Review assumptions, units, applicability,
  references, thresholds, and required grid/time-step or experimental studies
  before commercial use. Freeze each study before collecting its results.
8. **Operate deliberately.** Establish monitoring, incident response, access
  control, retention, queue/cost policy, rollback, and failure-injection tests.

Passing schema validation, building an image, or merging this source entry does
not satisfy these gates. No publication, first-party endorsement, cloud
availability, or commercial production approval is implied.