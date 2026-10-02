# FlowBlind Research Teammate v2

This is the portable catalog-native `flowblind-research-teammate-v2@2.0.0`
package.

This repository publication is additive and source-only. It does not replace
the separately versioned v1 package as the documented future upstream
`microsoft/discovery` candidate, and it does not authorize deployment or live
activation. Any change to that lifecycle relationship requires a separate
owner decision after Round 1 and the four `V2-LIVE-*` gates close.

The `publisher` block in `metadata.yaml` is catalog-staging metadata, not
evidence that Microsoft has accepted first-party ownership or support for this
package. It must be confirmed or revised before any separate upstream
contribution.

It exposes exactly two public tool folders:

- `flowblind-prepare-study-v2` (`prepare-study`, confirmation disabled)
- `flowblind-run-and-verify-study-v2` (`run-and-verify-study`, confirmation
  enabled)

Only regional agreement and vector/time readiness are advertised.

The exact retained hidden-flow closure is present in both tool images because
private preparation and confirmed private execution share this two-action
package. It is not registered or disclosed through public scientist responses
and remains unusable without the exact host-owned conformance activation. This
is a routing boundary, not a claim that the private bytes are absent from the
package.

Public input mounts use exact relative references: preparation reads only
`candidate.csv`; execution reads `candidate.csv` plus the unchanged
`flowblind-preparation-<preparation-sha256>/trusted-sidecar.json` and
`preparation.json`. Private hidden-flow preparation reads only `problem.json`.
The package rejects alternate names and never copies the public candidate
dataset into output. Hidden preparation intentionally preserves the validated
problem document inside the content-addressed preparation bundle required for
restart; it does not retain a separate source-file copy or register a
researcher dataset, but the bundle must still be governed as retained
scientific content.

The catalog host's `confirmation: Enabled` boundary is the human authorization
for the run tool. The process-local token minted by the package verifier proves
only that the attested run facade was used; it is not an independent record of
human approval, and direct container invocation is a conformance interface
rather than a supported live entry point.

The runtime is local-only and requires no repository or Git metadata. Run the
package verifier before importing the bundled runtime. Report resources are
read through the internal `runtime/flowblind-report-resource-v2.mjs` facade,
which is not a public tool. Cold reads require the host-selected retained
output root associated with the committed publication receipt; neither that
path nor resource authority comes from the scientist.

Container execution is intended for `--network none`, `--read-only`,
read-only input mounts, a writable `/output` mount, and a bounded
`/tmp:rw,noexec,nosuid,nodev` tmpfs.

Image construction downloads hash-pinned wheels from the official Python
Package Index by default; runtime execution requires no network.

`runtime/flowblind-scenario-harness-v2.mjs describe` emits the attested
package-local coverage map. Its private `run-hidden` mode is an internal
deterministic driver for the named package scenarios when the caller supplies
the exact host activation, a clean output root, the pinned Python environment,
and an independently reviewed canonical problem fixture. The four V2-LIVE
scenarios remain manual.
