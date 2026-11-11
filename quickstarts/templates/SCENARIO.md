# QuickStart Scenario — authoring template

Template status: proposed common structure for **QuickStart Scenarios**.
Complete applicable fields from owner evidence; do not invent missing values.
This is not a claim that the original internal template attachment was parsed.

## 1. Scenario identity

Observable outcome, audience, scientific scope and exclusions; owner, version,
source revision, reference date, delivery host and execution destination.

## 2. Configuration matrix

Model/revision/settings; agents and roles; **skills** and activation; tool/MCP
bindings; canonical repository revisions; image digests; orchestration/retry
limits; input versions/hashes. Mark unavailable backend settings Not recorded.

## 3. System requirements

Minimum, recommended and actually tested are different. Record OS, hardware
architecture, interpreter, RAM/storage and network. For Bookshelves include
corpus source/rights, document sizes/counts, indexing/embedding settings and an
index-ready query with expected supporting passages. Services is separate.

## 4. Prerequisites

Supported App/host, required access, approved licences, published asset
locations and integrity, exact dependency pins, external-browser authentication
under user control. No secrets or personal machine paths.

## 5. Setup

One documented fresh-project path with runner activation and asset preparation;
explicit separate permissions/approvals; environment and corpus readiness
checks; known failure recovery. Do not ask the customer to design missing wiring.

## 6. Fixed prompt and matching output

Preserve the exact owner prompt and its digest, required execution steps,
output artifacts and original criteria. Distinguish a supplied reference from
an illustrative example. Define comparison tolerances and required SME review
only from accepted evidence. Fail required fallback/tool-route checks honestly.

## 7. Runtime

Separate download/setup, indexing, execution and validation, with measured versus
estimated labels and cache/hardware conditions. Include quiet phases and actual
timeout boundaries. Never invent a benchmark distribution from a single run.

## 8. Troubleshooting and cleanup

Actionable errors; no unauthorized pin/source changes, TLS disabling, access
bypass or data substitution. Preserve failed attempts. Cleanup only the exact
run-owned resources with permission; do not delete shared projects or indexes.

## 9. Publication checklist

- [ ] Required files/components have approved public delivery and integrity.
- [ ] Paper/code/data rights and attribution have been reviewed.
- [ ] Guide/profile/prompt/manifest agree and offline checks passed.
- [ ] Fresh-project runner activation and setup were actually tested.
- [ ] Native workflow evidence satisfies all original owner checks.
- [ ] Scientific review and remaining limitations are recorded.
- [ ] Maintainer/owner approval and public release location are recorded.

Unmet items remain blockers. This checklist is not itself executed evidence.