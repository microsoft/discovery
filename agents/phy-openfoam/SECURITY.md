# Security policy

## Report privately

Report suspected vulnerabilities through the official
[Microsoft Security Response Center reporting portal](https://msrc.microsoft.com/create-report).
Do **not** open public issues, publish exploit details, or attach secrets to a
pull request. The upstream catalog has issues disabled; this entry does not
establish a separate public security tracker or support SLA.

Include the affected source revision/version, component and execution route,
impact, and a minimal safe reproduction. Share sensitive diagnostics only through
the authorized private reporting channel. Do not publish HMAC keys, provider or
registry credentials, capability URLs, native sessions, or private case geometry.

## Security boundaries

| Boundary | Implemented intent | Not guaranteed |
|---|---|---|
| Bundle ingestion | Strict schemas, safe paths, executable/dynamic-code refusal, contract lint | Correct scientific modeling or benign arbitrary native code |
| Worker container | No network, non-root, read-only root/input, dropped capabilities, allowlisted commands | Certified hostile multi-tenant isolation or isolation of the agent's host shell |
| Resource limits | CPU/memory/PID limits with fail-closed default and frozen budgets | Enforcement on an incapable runtime, or production enforcement inferred from a label |
| Confirmation | Pending `needs_confirmation` assumptions block execution | Authenticated human identity from a bundle-supplied `confirmed_by` field |
| Journal integrity | Hash chain and local HMAC; pinned-artifact verification and recomputed decisions | Key isolation from the same user, a public signature, or proof no journal suffix was removed |

Use a dedicated VM and separately privileged trusted executor for hostile or
multi-user workloads. Keep container sockets, administrator credentials, and
signing-key custody outside the reasoning agent's authority. The model's host
shell and external CLIO runtime are not sandboxed merely because CFD executes
inside a worker container.

## Operator-only decisions

Only an operator may install/initialize/authenticate external runtimes, select
trusted images/executables, adjust concurrency, or authorize an explicitly
disclosed unenforced-limit exception. An agent must report infrastructure
refusals, not reconfigure Podman/Docker, reset storage, modify the tool, or enable
exception flags to get past them. Unsafe choices are never implicitly authorized
by a benchmark prompt, installer default, or suggested troubleshooting step.

User confirmation of scientific assumptions is separate from operator policy.
Do not let a reasoning agent approve its own method/fidelity substitution. The
local prototype does not supply production multi-user authentication or a durable
cloud authorization/key-management service.

## Secrets and private artifacts

The deterministic physics tool does not call an LLM or need provider keys.
Discovery/CLIO, cloud services, and registry login are external and independently
authenticated. No vendor binaries, virtual environments, keys, or login files
should be copied from an existing machine into this source distribution.

Never publish local Discovery state, including apparently innocuous routing
files. Capability URLs may themselves carry authority. Excluded material includes:

```text
.discovery/
operator config with private values
HMAC key files
native CLIO sessions and raw RPC transcripts
cloud/registry/provider credentials
solver run stores, confidential geometry, and generated output archives
```

Original benchmark outputs and native receipts/transcripts were moved
byte-identically into an ignored workstation-only evidence area. Keep those
originals immutable and out of the public bundle; they contain absolute paths
and native session metadata. Do not link active public docs to them or silently
rewrite them to remove sensitive fields.

Any sanitized public derivative must be a **new**, explicitly labeled artifact
with source hashes, documented transformations, and reviewed redactions. Preserve
source provenance without exporting private mappings or keys. A derivative is
not the original signed evidence, and a hash is not public authentication of
unavailable material.

## Verification and retention

Stop further scientific decisions on a lineage when `verify` fails. Retain the
failure, check the selected original store/key privately, and investigate without
editing journals, evidence, thresholds, or state. Do not create a replacement key
or distribute a secret key merely to make another machine report success.

HMAC authentication is symmetric and local; it is not an externally verifiable
public signature. A retained valid prefix cannot prove absence of truncation.
Production requires separate key custody, externally retained chain heads, and
append-only audit storage. An export archive, even with fields, does not
automatically contain all code, ancestors, member runs, or external retention
records needed for complete lineage verification.

Keep historical originals immutable. Review `compact` in dry-run mode before
any operator-authorized retention action on other finalized runs; field removal
is irreversible without a backup and compacted runs cannot be continued.

## Dependency and deployment review

The image recipe pins its base digest and Foundation package checksum, but apt
and some transitive dependencies float. Builds are not fully reproducible and
pins do not establish vulnerability clearance. Inventory and scan each actual
candidate image and complete [license/compliance review](docs/licensing.md)
before publication.

The original local evidence does not establish Azure dispatch, actual cloud
resource enforcement, cloud-study integration, or production security sign-off.
The candidate 0.2.1 relocation/docs are not fresh security or solver validation.
See [deployment readiness](docs/deployment.md) for the unexecuted qualification
gates and [validation history](benchmarks/VALIDATION-HISTORY.md) for historical scope.