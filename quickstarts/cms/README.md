# QuickStart Scenarios — CMS

**Draft; corpus, execution binding and owner-reference validation unresolved.**
This package preserves Andre's moisturizer-formulation scenario. It does not
replace it with a different dataset or with an unrelated public Bookshelf.

## 1. Scenario identity

Plan round 1 of a lightweight daily face lotion campaign: five formulations,
one-sentence rationales, approach/trade-off discussion, then a terminal batch
JSON object. The overall lab budget is four rounds / twenty experiments, but
only the first batch is in scope. No previous measurements exist for this
chassis; proposed hydration, barrier, sensory, stability or cost outcomes are
not measured results.

## 2. Configuration matrix

| Component | Source and status |
| --- | --- |
| Literature agent | [bookshelf-researcher](https://github.com/microsoft/discovery/blob/88a2a1cd1664b7d609659dc86c65f7f632686715/agents/bookshelf-researcher/agent.yaml) |
| Experiment agent | [bo-doe](https://github.com/microsoft/discovery/blob/88a2a1cd1664b7d609659dc86c65f7f632686715/agents/bo-doe/agent.yaml) |
| Tool source | [bodoe](https://github.com/microsoft/discovery/blob/88a2a1cd1664b7d609659dc86c65f7f632686715/agents/bo-doe/tools/bodoe/tool.yaml), CPU tool; image/runtime identity must be bound in the chosen environment. |
| Installation reference | [add-example-agents](https://github.com/microsoft/discovery/blob/88a2a1cd1664b7d609659dc86c65f7f632686715/skills/add-example-agents/SKILL.md); selecting an installation route is not permission to deploy. |
| Skills | Shared runner, plus a reviewed compatible installation route. No requirement to duplicate agent implementations. |
| Model | Exact selected model/revision/settings need owner confirmation; never inherit BioPharma's model pin. |
| Bookshelf | Required skincare corpus, with validated content and retrieval; each user's runtime ID is separate from corpus identity. |

The upstream `bo-doe` documentation describes a Services-managed tool. A usable
local App binding must be established and tested; the existence of canonical
source does not prove a local route. Services provisioning is a separate,
explicitly authorized profile, not a fallback silently started by this guide.

## 3. System requirements

App 0.15.21 and Services were owner-reported surfaces; this package has not
reproduced either. OS/CPU/RAM/runtime minima, model configuration and cold-start
cost need reference evidence for the selected route. Inspect native tool
requirements rather than borrow another scenario's Python or hardware pin.

The supplied corpus has 14 PDFs (numbering 01–03 and 05–15), 26,138,594 source
bytes. The missing number 04 is not authority to invent a paper or waive corpus
completeness. [assets.json](assets.json) preserves each identity and hash.

## 4. Prerequisites

Approved machine-readable source papers and their distribution rights are
required. Prior local ingestion reported completion, but its extracted text
was the same protection notice for all fourteen inputs and the readiness query
returned no results. A compatible authorized viewer may still show the papers;
this is an ingestion-path failure, not proof the user's access is unauthorized.
Do not remove protection, print-to-PDF to strip labels or bypass access controls.

No public approved corpus location is available in this package. The internal
storage location is not a customer dependency. Resolve it through the data owner,
not by redistributing the existing protected ZIP or substituting SCLC papers.

## 5. Setup

Use [Getting started](../GETTING-STARTED.md). First resolve public inputs,
readability, model, intended surface and approved runtime bindings. Reference
the canonical two agents and tool, not copied author definitions.

After explicit setup/indexing approval, create a new scenario-owned Bookshelf
from the agreed corpus, record its document/index settings, and inspect actual
extracted content. Verify the query “niacinamide hydration barrier” returns
meaningful supporting passages with document identities. That is a diagnostic
probe, not a complete scientific acceptance check; the owner must establish
the final index configuration and expected sources.

After capabilities and data are ready, obtain bounded agent-computation
approval. Agent invocation and index building can consume resources. The
shared runner must not perform either just to populate a readiness table.

## 6. Fixed prompt and matching output

[The exact owner prompt](prompts/hero.txt) is preserved with LF line endings and
a digest. Do not silently add model names, change bounds or alter the lab
budget. The required work is evidence gathering by `bookshelf-researcher` and
initial experiment design by `bo-doe`, with actual execution evidence.

Owner checks: every ingredient-effect claim names support from the skincare
papers or is explicitly labelled judgement; no invented data/citations;
uncertainty for weak/conflicting evidence; exactly five one-sentence rationales;
all nine variables within their bounds and water above $50\%$; terminal numeric
JSON with `batch` equal to 1; and a rationale for what round 1 learns given
three rounds/fifteen experiments remain. pH is not a mass fraction and must
not be included in the addition sum. The eight maxima sum to $47.8\%$ under
the prompt's instruction to ignore fixed preservative/buffer.

Reference answers and completed task/tool traces have not been supplied for
this package. A final JSON structure can be checked deterministically, but
citation support, scientific judgement and one-sentence rationale quality still
need actual evidence and owner review. A fabricated task list is not proof
that the two agents ran.

## 7. Runtime

The owner slide reported 5–10 minutes without a verified phase/cache breakdown.
Do not turn this into a ten-minute timeout, a repeat count or a reliability
threshold. No clean-project install/index/run benchmark exists here.

## 8. Troubleshooting and cleanup

On empty or protection-only extraction, stop before the agents and request an
authorized readable route. A green provider state is insufficient. Preserve
failed ingestion evidence and hash/version any approved replacement corpus.
Do not infer success from the merged `bo-doe` source alone. Do not delete shared
Bookshelves, cloud resources or earlier experiment results automatically.

## 9. Publication checklist

- [ ] Corpus completeness, readable source, licences and public access confirmed.
- [ ] Model, surface-specific binding and index configuration accepted by owner.
- [ ] Exact prompt and approved bounds preserved.
- [ ] Real two-agent execution and all seven owner criteria verified.
- [ ] Fresh-project customer route and cleanup tested independently per surface.

See [file accounting](FILES.md), [profile](profile.md) and
[manifest](scenario.json). All new execution is Not run.