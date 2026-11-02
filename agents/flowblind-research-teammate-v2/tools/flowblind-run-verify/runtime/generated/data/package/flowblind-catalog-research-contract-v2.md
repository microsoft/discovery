# FlowBlind catalog-native research contract v2

Package: `flowblind-research-teammate-v2@2.0.0`

## Public lifecycle

The package exposes exactly two public actions:

1. `prepare-study`, without confirmation and without scientific execution.
2. `run-and-verify-study`, inside a host-owned confirmation callback.

The catalog host's `confirmation: Enabled` policy is the sole human approval
boundary. The verifier-minted process token proves correct facade selection
inside the package; it does not replace or independently attest the host UI
decision. Direct command-line or container invocation is for conformance
validation only and is not a live authorization path.

A host confirmation implementation must report `cancelled` or `busy` only
before callback entry. Once the execution callback starts, interruption or
settlement uncertainty must be reported as `prior-outcome-unknown` and
reconciled from the durable marker before retry.

The host must bind that confirmation to the exact immutable invocation and
mounted attachment identities used to start the run container. Output mounts
must be invocation-scoped, and automatic promotion must occur only for a
zero-exit response carrying a marker-committed receipt. Nonzero exits must
retain any uncertain mount for reconciliation without promoting pre-marker
files.

Only `regional-agreement-v1@1.0.0` and
`vector-time-readiness-audit-v1@1.0.0` are advertised.

## Private and inactive state

`finite-basis-hidden-flow-v1@1.1.0` remains outside the public registry and is
available only through the exact host-private activation boundary.
Sensor-placement and external-validation routes remain default-off. Home QC is
unregistered.

Unadvertised is a registry and scientist-response boundary, not a distribution
boundary. Both two-action images intentionally contain the exact retained
hidden closure because private preparation and confirmed private execution use
the same package surface. Without exact host activation, public responses omit
private method, package, route, authority, and grant identities.

Release state, attachment shape, package availability, and method versions
never choose or break an intent tie.

## Authority and resources

Every executable method requires process-local authority minted by the exact
same verifier module that validates its retained package. Serialized evidence
does not authorize execution.

Preparation binds immutable attachment identities and installs its commit
marker last. Run revalidates those exact bindings, enters science only at the
confirmed callback boundary, and installs the report verification marker last.
No distributed exactly-once claim is made.

Public preparation accepts exactly `candidate.csv` at the root of the
read-only input mount. Public execution accepts that same `candidate.csv` plus
the unchanged `flowblind-preparation-<preparation-sha256>/` directory containing
exactly `trusted-sidecar.json` and `preparation.json`. Privately activated
hidden-flow preparation accepts exactly `problem.json` at the mount root.
Attachments at other relative paths are rejected rather than renamed, copied,
or staged under the output root.

The Discovery prepare schema is a flat superset because it cannot express the
authoritative three-branch union. Only `researchGoal` is universally required
at that host projection; the attested runtime selects the method from intent
and then requires exactly that family's scientific metadata, rejecting wrong
units, mixed-family fields, and missing declarations before attachment access.

Report resources require exact reacquired package authority and the
host-selected retained output root associated with the committed publication
receipt; that root is never scientist input. The reader revalidates the full
marker binding, retained semantic response, and receipt-bound bytes. URI
possession alone is not authority, and the package does not claim to make a
host output store writable by an attacker trustworthy.

## Retained closures

The package contains byte-preserved retained closures only at:

- `runtime/generated/retained/catalog-v1/runtime`
- `runtime/generated/retained/hidden-flow-v1/runtime`

Their manifests bind every path, byte length, SHA-256, and canonical tree hash.
No Git repository or historical object is required at runtime.

The accepted hidden bridge source remains byte-identical. A separate,
versioned package-owned bridge source is mechanically derived from that exact
accepted file with one reviewed extension: it accepts both compact stable JSON
and indented stable JSON without re-encoding either representation. The
accepted-source digest, extension-source digest, byte length, and extension
policy are attested. Selected problems and retained native
preparation/report bytes therefore pass unchanged. Package-local activation
remains conformance-only and is not live-ready without independent image
allowlists.

## Reporting boundaries

Declaration previews distinguish unverified scientist assertions from
validated source projections and never turn review into approval. Generic
reports are descriptive and neutral; they are not acceptance, robustness,
clinical, solver-verification, uncertainty, or globally-best-region verdicts.
Vector/time readiness does not infer point-time meaning for frame averages,
claim unstructured derivatives, or report wall shear without explicit wall
evidence. A preparation asset is not a retained copy of the selected source,
and custom report URIs are not replaced with `file://` or described as
clickable without an approved host resolver.

## Validation fixtures

Deterministic validation fixtures are generated only in temporary workspaces.
No novel fixture byte file is committed in the package. Fixture identities
must remain distinct from authoritative data and retained package examples.

## Live boundary

Package-local and container tests do not establish live-service acceptance.
The four `V2-LIVE-*` scenarios remain manual post-PR gates.
