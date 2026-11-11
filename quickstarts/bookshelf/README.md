# QuickStart Scenarios — Bookshelf

**Draft public SCLC variant.** Corpus acquisition metadata exists; the scenario
prompt, index recipe, reference answer and scientific checks need owner review
and actual validation. This is separate from CMS, SiPhy and the fixed internal
leukemia regression corpus. It inherits none of their results.

## 1. Scenario identity

Demonstrate building a new Bookshelf over a small, publicly sourced set of
small-cell lung cancer (SCLC) papers and answering a fixed research question
with traceable citations and uncertainty. The proposed outcome is an evidence
comparison, not medical advice or a treatment recommendation for a patient.

The inspected corpus work supplies fifteen PDFs and metadata, not a finished
owner QuickStart. The earlier proposal file is empty. The prompt shipped here
is **newly proposed**, not recovered from a nonexistent completed guide.

## 2. Configuration matrix

| Component | Status |
| --- | --- |
| Host | Discovery App with local Bookshelf capability; exact tested App profile not yet selected. |
| Agent | [bookshelf-researcher](https://github.com/microsoft/discovery/blob/88a2a1cd1664b7d609659dc86c65f7f632686715/agents/bookshelf-researcher/agent.yaml), canonical evidence-grounded agent; host invocation/binding still to test. |
| Skills | Shared runner, and a compatible approved installation route if needed. |
| Model | Owner to agree model/revision/settings; do not silently select BioPharma's model. |
| Data | Fifteen paper records in [assets.json](assets.json), 19,134,519 PDF bytes total, retained source version 1. |
| Index | Provider/embedding revision/chunk settings/document and chunk counts must be recorded from the new approved run. No existing index is bundled. |

## 3. System requirements

Use a supported Discovery App platform, with enough local space for papers and
the index. Source PDF size is not index memory/disk size. Scenario RAM, hardware,
index time and platform matrix have not been established. App download
availability alone does not validate this workflow on a platform.

## 4. Prerequisites and corpus acquisition

The asset manifest records original article titles, PMC IDs, DOIs, versioned
publisher-hosted PDF URLs, lengths, SHA-256 and CC BY 4.0 metadata. Verify terms,
attribution and third-party exclusions at release time; keep all document
notices. The repository code licence does not replace the article licences.

This skeleton commits metadata, not PDF binaries or extracted paper text. After
explicit acquisition approval, obtain exactly the listed PDF versions from the
public URLs under their expected filenames, then use the shared `verify-assets`
helper to check them. Existing download receipts are not a promise the URLs
still respond. An automated approved download integration is still a release
blocker; customers should not have to discover missing paper URLs themselves.

The human-readable filename copies used during preparation are not a second
corpus. The manifest's PMC filenames are the reproducible identity. Do not mix
in unrelated papers or the author's extraction/index caches.

## 5. Setup

Follow [Getting started](../GETTING-STARTED.md). Once the owner-approved prompt,
model and index recipe are recorded, obtain explicit permission to create/index
the scenario-owned shelf from the verified fifteen PDFs. Record the runtime
shelf ID separately from its portable corpus identity.

Inspect actual extracted text and retrieval with document provenance, not
only a health dot or document count. Suggested **diagnostic probes for owner
review** are “Canadian Consensus Recommendations” and “CASPIAN molecular
classification”. Returned text should correspond to the appropriate manifest
papers, not a protection notice, empty page or metadata-only record. Source
text passage checks performed during corpus preparation did not run Discovery
indexing and do not satisfy this gate.

After readiness, separately approve the research-agent invocation. No live web
search is part of the proposed scientific question; the approved fixed corpus
is its evidence boundary. Missing evidence should be reported as missing.

## 6. Proposed fixed prompt and expected output

[prompts/hero.txt](prompts/hero.txt) asks for three supported research findings,
their populations/study designs and limitations, with an evidence table and
source identifiers. It is explicitly proposed and cannot be promoted to an
owner baseline by an automated package check.

Proposed acceptance for owner agreement: all material statements trace to
actual retrieved passages; citations match the fifteen-paper manifest; primary,
review, subgroup and observational evidence are distinguished; no invented
values/sources; uncertainties and absent evidence are explicit; no new clinical
or causal claim from an uncontrolled cross-study comparison. A final answer
must be checked against its retrieved evidence, not merely count citations.

No reference answer, successful App run or scored scientific rubric is supplied.
Do not fabricate one or copy a response from the internal regression scenario.

## 7. Runtime

Download, setup, indexing, agent execution and validation timings are Not
measured for this package. Record cold/warm conditions when the approved run is
performed. Fifteen PDFs or the prior local text check do not imply a runtime.

## 8. Troubleshooting and cleanup

Stop on changed hashes, unreadable content, licence ambiguity or unsupported
runtime bindings. Do not replace input versions or disable TLS to get a pass.
On empty search, inspect extraction/index settings and preserve evidence before
retrying. Never delete or overwrite another scenario's shelf or baseline.
Cleanup is scoped to the explicitly owned project/index, with permission.

## 9. Publication checklist

- [ ] Source licences/notices, exact acquisition and URL reachability reviewed.
- [ ] Owner accepts prompt, model/index profile and expected-answer checks.
- [ ] Automatic approved acquisition/setup path completed and tested.
- [ ] Fresh-project skill discovery, ingestion, retrieval and agent run verified.
- [ ] Scientific/citation review and reference output retained.

See [file accounting](FILES.md), [profile](profile.md), and
[manifest](scenario.json). Metadata verification is not a scientific result.