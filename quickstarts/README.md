# QuickStart Scenarios

**Draft skeleton for maintainer and scenario-owner review. None of these
packages is currently designated ready for external execution.**

A QuickStart Scenario packages a particular scientific workflow: its fixed
prompt, inputs, capabilities, setup, outputs and evidence-based acceptance.
The goal is a fresh-project customer path, without a contributor's machine,
saved chats, prebuilt indexes or personal skills. This is separate from the
raw E2E scenario handoff used by Engineering's own test harnesses.

Start with [Getting started](GETTING-STARTED.md). Author another scenario using
[the authoring guide](AUTHORING.md) and [the template](templates/SCENARIO.md).

| Scenario | Intended outcome | Current evidence and blockers |
| --- | --- | --- |
| [SiPhy](siphy/README.md) | CoreSPI-inspired specification to verified RTL | Owner prompt/setup supplied; required MCP route previously failed; component publication, corpus rights and clean-project verification unresolved. |
| [BioPharma](biopharma/README.md) | Frozen-input CDK decision scoring, solubility inference and ranking | Historical frozen run passed 7/7; modified runner/customer path untested; public archive locations and owner acceptance unresolved. |
| [CMS](cms/README.md) | Evidence-grounded first round of five moisturizer formulations | Owner prompt and corpus hashes supplied; source PDFs were not usable through the tested ingestion path; distribution, configuration and E2E evidence unresolved. |
| [Bookshelf](bookshelf/README.md) | Grounded evidence comparison over a public SCLC corpus | Fifteen paper records with hashes and publisher URLs; proposed prompt only; indexing recipe and owner-approved answer checks unvalidated. |

## What is included

Each folder has a guide, execution profile, fixed/proposed prompt with digest,
asset inventory and component references. [Source inventory](SOURCE-INVENTORY.md)
accounts for inputs that cannot yet be published. The shared
[runner](../skills/quickstart-runner/SKILL.md) includes an offline helper to
validate text packages, stage a new review folder and verify existing assets.

Shared catalog agents, installation skills and tool implementations stay at
their canonical repository locations. They are referenced at inspected source
revisions, not duplicated into each scenario. Missing publications remain
explicitly missing. A package is self-contained only when all required inputs
are either included with permission or reproducibly obtainable from verified
public locations; a missing URL cannot be fixed by a personal file handoff.

## Evidence and publication

Keep **package integrity**, **environment readiness**, **workflow completion**
and **scientific acceptance** separate. Offline checks are not a new scientific
run. Proposed statements and historical measurements are labelled. No new
catalog UI, automatic deployment, permission grant or universal platform
support is implied.

Repository maintainers must approve this new top-level layout and its future
validation integration. This PR does not edit trusted workflows, policy,
schemas under `docs/schemas`, generated registries or existing agents.
See [the package contract](PACKAGE-CONTRACT.md) for the local JSON format.