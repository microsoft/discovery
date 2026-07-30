# Nexus literature review — task definitions

The three tasks to transcribe into Discovery Studio, in this order. Replace
`{{RESEARCH_QUESTION}}` with one precise sentence — it appears in all three descriptions.

For everything else — prerequisites, session setup, and starting the Engine — see
[`README.md`](README.md).

---

## Task 1 — Gather Literature Evidence

| Field | Value |
| --- | --- |
| **Name** | `Gather Literature Evidence` |
| **Shared Session** | your session |
| **Assigned to** | *(blank — expect `NexusSearch`)* |
| **Priority** | Medium |
| **Dependent tasks** | *(none)* |

**Description**

```
Research question: {{RESEARCH_QUESTION}}

Search Wiley Nexus from multiple distinct angles and build the evidence base that the later stages of this review will work from. Aim for at least 8 unique publications where the literature supports it. Search and evidence gathering only: do not download full texts and do not write the final answer.

Produce two files.

File 1 - evidence_passages.md (markdown). Open with a "## Search coverage" section containing one bullet per search angle, giving the query used, what it supported, and any facet that returned little or nothing. Then a "## Publications" section with one "### [n] Title" entry per unique publication, deduplicated by DOI, each carrying these labeled fields, using exactly these names: DOI, Authors, Journal, Full Text Available, Wiley Online Library. Under each entry, include that publication's passages quoted verbatim as blockquotes.

File 2 - fulltext_shortlist.json (JSON), of the form {"shortlist":[{"doi":"...","title":"...","rationale":"...","full_text_token":"..."}]}, listing the 3 to 5 publications most worth reading in full. Only shortlist papers whose search hit carried a full_text_token, and copy each token verbatim.

In your reply, list every shortlisted paper's DOI and title, one per line. The next stage reads that list from your result text to analyze each paper separately, so it must be present and accurate.
```

**Validation Criteria**

```
1. evidence_passages.md exists and contains at least 8 unique publications, each with a DOI, a title, and at least one verbatim passage.
2. Every publication entry records whether full text was available.
3. evidence_passages.md includes a search coverage section that names each angle searched and flags any facet with little or no evidence.
4. fulltext_shortlist.json exists and contains 3 to 5 entries, each with a doi, a title, a rationale, and a non-empty full_text_token.
5. The task result text lists the DOI and title of every shortlisted paper.
```

---

## Task 2 — Analyze Each Shortlisted Paper (the fan-out)

| Field | Value |
| --- | --- |
| **Name** | `Analyze Each Shortlisted Paper` |
| **Shared Session** | your session |
| **Assigned to** | **BLANK — required.** Assigning an agent here prevents the fan-out. |
| **Priority** | Medium |
| **Dependent tasks** | `Gather Literature Evidence` |

**Description**

```
Research question: {{RESEARCH_QUESTION}}

The upstream search task produced a full-text shortlist. Its result text lists each shortlisted paper's DOI and title, and the matching download tokens are in fulltext_shortlist.json.

Produce a separate full-text analysis for EACH shortlisted paper. Break this work into one subtask per paper, so every paper is read and analyzed independently and in parallel rather than in a single combined pass.

For each paper: read its full text using the download token from its shortlist entry, re-searching by that paper's DOI or title for a fresh token if the supplied one has expired. Then write a file named analysis_<doi>.json for that paper alone, containing doi, title, status, contribution, key_findings, methods, and limitations. Ground every statement in that paper's own downloaded text.

Filename rule for every subtask: in the analysis filename, replace each character of the DOI that is not a letter, digit, dot, or underscore with an underscore. The file-writing tool permits only alphanumerics, dots, and underscores, and rejects hyphens and slashes, so DOI 10.1111/j.1365-2796.2009.02201.x becomes analysis_10.1111_j.1365_2796.2009.02201.x.json. Never require a filename containing a hyphen in a subtask description or validation requirement, because such a file cannot be created and the subtask would fail validation even though its analysis succeeded.

A paper that cannot be retrieved is recorded with status "unavailable" and a one-line reason, and must never block the other papers.
```

**Validation Criteria**

```
1. There is one analysis file for every paper listed in fulltext_shortlist.json, and no shortlisted paper is left without a file.
2. Each file has status "analyzed" with concrete findings such as numbers, effect sizes, conditions, or stated conclusions, or status "unavailable" with a one-line reason.
3. Each analyzed file reports what its own paper found rather than summarizing the topic generally.
4. Each file with status "analyzed" records the methods and the limitations of the paper it covers.
```

---

## Task 3 — Compose the Response

| Field | Value |
| --- | --- |
| **Name** | `Compose the Response` |
| **Shared Session** | your session |
| **Assigned to** | *(blank — expect `NexusWriter`)* |
| **Priority** | Medium |
| **Dependent tasks** | `Gather Literature Evidence` **and** `Analyze Each Shortlisted Paper` |

**Description**

```
Research question: {{RESEARCH_QUESTION}}

The upstream tasks produced evidence_passages.md, containing passage-level evidence and metadata for every publication found, and one analysis file per shortlisted paper, marked unavailable if it could not be retrieved. The number of analysis files varies per run, so list the available resources and read every analysis file present rather than assuming a single one. Do not search or download anything; work only from these files.

Write research_response.md: a structured, chat-style answer to the research question, not a formal report. Lead with the direct answer in the first paragraph or two, then develop detail under headings, using a table where comparing studies or outcomes is clearer than prose. Cite in IEEE style, numbering sources in order of first appearance with bracketed inline markers tied to a "## References" list whose entries are built only from metadata in these files and linked to Wiley Online Library. Give more weight to findings from papers read in full than to passage-only evidence, state plainly what the retrieved literature does not establish, including any paper marked unavailable, and close with a one-line evidence basis.
```

**Validation Criteria**

```
1. research_response.md exists and opens with a direct answer to the research question.
2. Every factual claim carries an IEEE-style numbered inline citation tied to a "## References" list, and only publications present in the upstream files are cited.
3. Reference entries include the DOI and Wiley Online Library link wherever the upstream files carry them.
4. The response states the gaps in the evidence, including any shortlisted paper that could not be read in full.
5. The response closes with a one-line evidence basis stating how many publications it draws on and which were read in full versus cited from passages only.
```
