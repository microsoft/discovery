# Validation history — retrospective, not new receipts

**Scope:** this is a newly written summary of the original **0.2.0** validation
record dated **2026-11-22**, before the public-entry relocation and candidate
**0.2.1** packaging. It is not a new test execution, solver result, model call,
installer qualification, publicly authenticated HMAC receipt, or cloud request.

Original benchmark outputs, receipts, and transcripts were moved **byte-identically**
into an ignored workstation-only evidence area. They contain absolute paths and
native session metadata and are **excluded from the public bundle**. This page
does not link to them, reproduce private transcripts, or claim that a public
checkout contains complete verifiable original lineage.

## Original environment

- Windows x64 host; Python 3.11+ package requirement; independently installed
  Podman/Docker and Foundation 14 worker.
- Discovery **0.15.21-preview**, native CLIO, with observed response model
  **`claude-sonnet-5`** for the B/C experiment. This is historical observation,
  not a guarantee of current provider selection or support for other models.
- Foundation package `openfoam14_20260724`, build `14-7b05503f98a8`, independently
  obtained from the Foundation distribution; not the OpenCFD distribution.
- The historical rootless runtime required an explicit operator exception for
  unenforced CPU/memory/PID limits. That exception was not proof of enforcement.
  The local queue capped simultaneous solves at two on the test workstation.

Base/solver pins identify selected inputs; they do not make apt/transitive
resolution or the entire environment fully reproducible.

## Findings and interpretation

| Original layer | Recorded result | Correct interpretation |
|---|---|---|
| Automated test suite | **157 passed** on 2026-11-22 | Original 0.2.0 source/tests, not 157 newly passed 0.2.1 tests or 157 new CFD predictions |
| Paper-style nozzle/forward-step campaign | **12/12 reference decisions matched** | Decision agreement, **not all `ACCEPT`**; S5 was `REJECT`, S8 was `INCONCLUSIVE` |
| Held-out native CLIO suite | **16/16 behavioral checks** | Includes clarification, unsupported-request handling, and safe unexecuted stops; not 16 independently validated predictions |
| Supplemental S8 three-grid study | **`REJECT`** | Member runs were live accepted/healthy, but pressure/temperature refinement changes grew; member health did not establish grid independence |
| B: full evidence packets | **38/40 correct**, **1 raw false accept** | Ungated advisory judgments with gate outputs visible; raw false acceptance did not override the live deterministic gate |
| C: blinded packets | **31/40 correct**, **8 raw false accepts** | Advisory judgments without outcomes, thresholds, or objective coverage; reduced visibility was not additional deterministic authority |
| A/G deterministic controls | **0 false accepts** in the finite comparison | Fixed-rule and forced-`ACCEPT` gate controls, not a universal zero-risk guarantee |
| Selected local paths | In-image `evaluate`, serial/two-rank MPI, and CAD conversion exercised | Local path evidence only, not Azure dispatch, general CAD robustness, scaling, or production enforcement |

The paper-style campaign used a **fixed-rule proposer**, not a model-driven
campaign. Inputs and diagnostics were independently reconstructed from published
specifications. Agreement does not claim bit-reproduction of the paper's runs,
provider/prompts, original fields, or every scientific quantity.

## H14: successful boundary behavior, unexecuted substitute

H14 retained a prepared run with a pending `method_substitution` confirmation.
The proposed substitute **was not executed** and had **no final scientific
verdict**. Native prose about the proposed method is not measured solver
evidence. Its behavioral score reflects the safe confirmation boundary, not a
completed or accepted substitute simulation.

Do not infer that the user approved resumption, or that completing H14 requires
executing the substitute. No document, scoring fix, generated DNS-style bundle,
or runtime exception may supply that missing consent.

## B/C protocol and audit qualifications

The original experiment used **four fresh native CLIO sessions** with paired,
shuffled aliases and 40 snapshots per arm. B included gate/check outputs; C
withheld outcomes, thresholds, and objective coverage. Input-only working
directories and a native tool-event audit reduced leakage but were not
OS-enforced blinding. One observed model and one pass do not establish
cross-model statistical performance or reproduce the paper's exact setup.

The H14 behavior-scoring revision and B02 temporary-output audit correction were
**post-run evaluation/audit fixes**. The latter recognized only exact earlier
successful same-session output-creation provenance, not arbitrary temporary
files. Original failures and responses were retained; these fixes did not relax
scientific contracts, rewrite run evidence, or tune judgments against the answer
key. Do not present re-collection as a fresh model attempt.

## Local service, MPI, and geometry scope

The in-image service exercised its own worker subprocess without nested
Podman/Docker. A branch label of `platform-enforced` is not a measurement that
Azure or a cgroup controller enforced limits.

The selected serial/two-rank channel check agreed on maximum pressure to an
approximately $3.2\times10^{-11}$ relative difference. This is not full-field
parallel verification or a scaling study. Local STEP-to-STL conversion is not
proof of arbitrary-CAD meshing robustness.

## Explicitly not established

- Fresh validation of the relocated **0.2.1** source, installers, package/image
  identities, documentation links, or public export.
- Actual Discovery/Azure action dispatch for `evaluate`, `study`, and `lint`;
  cloud-study integration and actual cloud resource/isolation enforcement.
- Production multi-user authorization, authenticated confirmations, separate
  durable key custody, externally retained chain heads, or append-only cloud audit.
- Commercial production sign-off, first-party approval, upstream publication,
  license/compliance clearance for a redistributed image, or security certification.
- Publicly authenticated HMAC signatures or complete externally verifiable
  original run/study/code/field lineage from the source bundle alone.

Local HMAC verification is symmetric and depends on private-key custody. A valid
prefix cannot prove absence of truncation. Export archives and hashes do not
automatically supply omitted fields, ancestors, study members, code, or external
retention evidence. Do not publish keys to create an appearance of public trust.

Use [new-run instructions](README.md) for independent validation. Preserve local
originals immutably; any sanitized derivative must be explicitly new, with source
hashes and transformation provenance. See [distribution](../docs/distribution.md)
and [security](../SECURITY.md) for publication and retention boundaries.