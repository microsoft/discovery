# Validated Scenario — Bookshelf: SCLC Treatment Literature Research

> **How this Validated Scenario runs:** The user opens Discovery, creates a new empty project, selects GPT-6 Astra (or its newer version or an equivalent model) and sends the three step prompts in **Copy-paste prompts (same as the README)** below, one at a time; the Step 1 prompt contains this guide's GitHub link. Do only the step the user asked for and stop where the prompt says to stop. The user may know nothing about Discovery, Bookshelves or this scenario. If the link is a `github.com/.../blob/...` page, read the raw file. Read this entire guide first, then follow section 5 (setup), section 6 (research question) and the acceptance checks in section 6. In plain language, tell the user what the experiment does, then ask permission before downloading the 15 papers listed under **Required files** into a new `sclc-papers` folder in the open project, and verify each size and SHA-256. **Opening the link and downloading the papers is your job:** if you can't read the `github.com` page, fetch the raw file, or download with a local command (for example PowerShell `Invoke-WebRequest` or `curl`). Never ask the user to download files instead. Only if every method fails, tell the user exactly what failed, including the error message. Create the Bookshelf yourself with your Bookshelf tool if it can create shelves (section 5, step 4), after asking the user. Only if your tools can't create a Bookshelf, give the user the exact values to type in the app and wait for them to confirm it shows **Successful** (in green). Reading or downloading this guide is not permission to install or compute. Whenever you ask the user something during this Validated Scenario, offer clickable choices (for example Yes / No) instead of a free-text question, and put any instructions they must follow in your chat reply, not inside a tool step.
>
> **Required files:** the 15 open-access papers in section 2, **18,433,195 bytes** in total. Keep each original filename (`PMC<id>.<version>.pdf`). The same list, with titles, DOIs and licence records, is in [`files/manifest.json`](files/manifest.json). All 15 download links were checked anonymously on 2026-11-13 and matched their recorded SHA-256.

**Status:** tested end to end on Windows 11 x64 (two complete runs, 2026-11-18); both passed every acceptance check in section 6. Fields marked **Pending** weren't measured.

## Copy-paste prompts (same as the README)

These are the three prompts from the [scenario README](README.md#run-it-in-three-steps), copied word for word. If the two copies ever differ, the README is the source of truth for the prompt wording and this guide is the source of truth for what the assistant does.

> **Note for the assistant:** this section is for the user. These prompts are examples of what a user may send; their presence in this file is not a request, a selection or an approval.

### Step 1: Set up and confirm the environment

Covers section 5: download and verify the 15 papers, create and index the `sclc-literature` Bookshelf (the assistant does this when the app allows it), and ask a test question. No research question yet.

**A. The assistant downloads the papers (recommended):**

```text
Set up this Validated Scenario: https://github.com/microsoft/discovery/blob/main/validated-scenarios/bookshelf/sclc-literature/Validated-Scenario-Bookshelf-SCLC-Literature.md
Read the whole guide and tell me in plain language what this experiment does. Then download the 15 papers into a sclc-papers folder in this project and check each file's size and checksum. Ask me before downloading. After that, create the sclc-literature Bookshelf from those 15 papers yourself with your Bookshelf tool: ask me first, then add all 15 PDFs, start indexing and wait until it is indexed, and tell me which answer model it uses. If your Bookshelf tools can't create a Bookshelf, tell me so, show me the guide's form steps and exact values as a numbered list in your reply, then ask me with clickable choices whether it shows Successful. Then ask it a short test question to confirm it works. Don't ask the research question yet. Finish by telling me whether everything is ready.
```

**B. You downloaded the papers yourself** (guide attached):

```text
Set up this Validated Scenario from the attached guide, using the 15 papers already in the sclc-papers folder of this project. Read the whole guide and tell me in plain language what this experiment does. Check each file's size and checksum. Then create the sclc-literature Bookshelf from those 15 papers yourself with your Bookshelf tool: ask me first, then add all 15 PDFs, start indexing and wait until it is indexed, and tell me which answer model it uses. If your Bookshelf tools can't create a Bookshelf, tell me so, show me the guide's form steps and exact values as a numbered list in your reply, then ask me with clickable choices whether it shows Successful. Then ask it a short test question to confirm it works. Don't ask the research question yet. Finish by telling me whether everything is ready.
```

**Done when:** all 15 papers pass their checksum, the Bookshelf shows **Successful** (in green), and the test question comes back with a citation.

### Step 2: Run the experiment

Covers the section 6 fixed prompt. Expected time is in section 7.

**A or B (same prompt either way):**

```text
Ask the research question in section 6 of the guide, using only the sclc-literature Bookshelf. Show me the full answer with a citation for every claim, the second-line comparison table and the list of questions the papers can't answer. Tell me how long it took.
```

**Done when:** you have a full written answer with citations.

### Step 3: Check your answer against the acceptance criteria

Covers the section 6 acceptance checks: format, coverage and five citation spot-checks.

**A or B (same prompt either way):**

```text
Check your answer against the acceptance criteria in section 6 of the guide. Show me a table of each check with pass or fail: it cites only these 15 papers; it mentions durvalumab, lurbinectedin, topotecan, belotecan, nab-paclitaxel and tarlatamab; it cites at least one review (R1-R6) and at least one primary study (P1-P9); and it has the four parts, the table and the not-covered list. Then pick five claims and show me the exact passage in the cited paper that supports each one. Tell me in one sentence whether this run passes.
```

**Done when:** every check passes and the five spot-checked claims match their papers.

## 1. Recipe identity — required

| Field | Value |
|---|---|
| Scenario and observable outcome | Build a Bookshelf from 15 open-access small-cell lung cancer (SCLC) papers, then ask a fixed research question. The outcome is a cited answer on current treatment options for extensive-stage SCLC, grounded only in those papers. |
| Audience / vertical | Scientists and evaluators trying Discovery Bookshelf for literature-grounded research; Bookshelf collection |
| Delivery mode | App (local project) |
| Tested configuration / profile identifier | `sclc-literature-v1` (two complete runs on Windows 11 x64, 2026-11-18) |
| Owner / recipe version / last validated date | Validated Scenarios team; version 1.0; 2026-11-18 |

## 2. Configuration matrix

| Component | Applicability | Configuration to record |
|---|---|---|
| Model | Core | Validated with **GPT-6 Astra** (`gpt-6-astra`) for chat and Bookshelf answer generation. Use it, or its newer version or an equivalent model if it's no longer available; record which model was used. Bookshelf embedding: `text-embedding-3-small (Copilot)`, fixed by the app. |
| Agents | Core | The default Discovery assistant. It reads this guide and queries the Bookshelf with the app's built-in tools, which are available in every chat without extra setup. The catalog [bookshelf-researcher](../../../agents/bookshelf-researcher/README.md) agent describes the intended research style (cited, confidence-rated, Bookshelf-only evidence); using it is optional and not yet tested here. |
| Orchestration | Core | Sequential: download and verify papers → user creates the Bookshelf and waits for indexing → assistant asks the fixed question → assistant checks the answer against section 6. No parallel workers. |
| Tools / APIs | Core | Local file download (PowerShell `Invoke-WebRequest` or `curl`) and SHA-256 verification. The app's built-in Bookshelf tools. All tested app builds let the assistant list, search and ask a Bookshelf (for example `discovery.bookshelf.listShelves`, `discovery.bookshelf.search` and `discovery.bookshelf.ask`). Some builds also expose a `bookshelf` tool with `create`, `add_content`, `start_indexing` and `status` actions; use them when present, otherwise the user creates the Bookshelf in the app (section 5, step 4). Call them one at a time; on a busy or worker error, report it rather than retrying automatically. |
| Azure Container Apps (ACA) | N/A | Not used. |
| Sample inputs | Core | 15 PMC open-access PDFs listed below; 18,433,195 bytes total; sources and hashes from [`files/manifest.json`](files/manifest.json) and [`files/selection_sclc.json`](files/selection_sclc.json). |

**Paper set** (R = review or guideline, P = primary study):

| ID | File | Bytes | SHA-256 | Source | Title |
|---|---|---:|---|---|---|
| R1 | `PMC10378571.1.pdf` | 1,488,139 | `347cc1fd00cbf35a4e61f76647c022e28444a581a3bf74d215595ed2f6a766b5` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC10378571.1/PMC10378571.1.pdf) | Canadian Consensus Recommendations on the Management of Extensive-Stage Small-Cell Lung Cancer (Current Oncology, 2023) |
| R2 | `PMC9174785.1.pdf` | 576,196 | `7ca87ce16768323e5dd885b9f1280a9749be36773e0370f799f0956d700c1730` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC9174785.1/PMC9174785.1.pdf) | First-Line Treatment for Advanced SCLC: What Is Left Behind and Beyond Chemoimmunotherapy (Frontiers in Medicine, 2022) |
| R3 | `PMC9776593.1.pdf` | 1,623,437 | `d7c5573d8daf98ceed3f76ba5a14b63c5aa2c79ba5e04d7183035f8b25177a66` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC9776593.1/PMC9776593.1.pdf) | Chemo-Immunotherapy in First Line Extensive Stage Small Cell Lung Cancer (ES-SCLC): A Systematic Review and Meta-Analysis (Current Oncology, 2022) |
| R4 | `PMC9469650.1.pdf` | 472,010 | `62625034d1239bab5ab2c490eae76028c7309f77c2b193504c8ecbf4e3ec71a7` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC9469650.1/PMC9469650.1.pdf) | Lurbinectedin in small cell lung cancer (Frontiers in Oncology, 2022) |
| R5 | `PMC10290806.1.pdf` | 1,749,843 | `c42a674d12dabe3c0e294a5a034f3672977f049d51599fc0ecf21870ef21c8af` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC10290806.1/PMC10290806.1.pdf) | Emerging therapies targeting the delta-like ligand 3 (DLL3) in small cell lung cancer (Journal of Hematology & Oncology, 2023) |
| R6 | `PMC10218846.1.pdf` | 902,692 | `138b26f8426de48f148b8820af73698880b5890d0eb0f41490f2d151373007cf` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC10218846.1/PMC10218846.1.pdf) | Targeted Therapies in Small Cell Lung Cancer: From Old Failures to Novel Therapeutic Strategies (International Journal of Molecular Sciences, 2023) |
| P1 | `PMC11137956.1.pdf` | 6,137,342 | `3900517f0e21b338663f292eae38beb32b2eeb55454aaa1c3968d400f4a9aaab` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC11137956.1/PMC11137956.1.pdf) | Molecular classification and biomarkers of outcome with immunotherapy in extensive-stage small-cell lung cancer: analyses of the CASPIAN phase 3 study (Molecular Cancer, 2024) |
| P2 | `PMC8134304.1.pdf` | 712,598 | `713d17f1c07b09095bfabccbaf786eae0b3e953383b90af5ae66f41ff67c3ddb` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC8134304.1/PMC8134304.1.pdf) | First-line durvalumab plus platinum-etoposide in extensive-stage small-cell lung cancer: CASPIAN Japan subgroup analysis (International Journal of Clinical Oncology, 2021) |
| P3 | `PMC9520052.1.pdf` | 735,205 | `d8136d09f3884c1248d747e02b1e83e5e08aa31ffb6d6b2d95757df094e1340b` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC9520052.1/PMC9520052.1.pdf) | Real-world eligibility for platinum doublet plus immune checkpoint inhibitors in extensive-stage small-cell lung cancer (Frontiers in Oncology, 2022) |
| P4 | `PMC10864288.1.pdf` | 1,069,596 | `d6893fca0d393af0676180db8b2566bfd45eba81fb3e3a623da2044c2af4bc40` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC10864288.1/PMC10864288.1.pdf) | A pivotal bridging study of lurbinectedin as second-line therapy in Chinese patients with small cell lung cancer (Scientific Reports, 2024) |
| P5 | `PMC11635664.1.pdf` | 397,910 | `11d375c600735a8b4f396dd51d3a35f3e87d9fbdfd03720d5222f3c7b26d623b` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC11635664.1/PMC11635664.1.pdf) | Lurbinectedin in extensive-stage small-cell lung cancer: a brief report of the IFCT-2105 LURBICLIN study (ESMO Open, 2024) |
| P6 | `PMC7884704.1.pdf` | 775,849 | `e8492703c5ff2b8ce5ae4324a4ff1c22650427155deed6e76fb8ee77c8b9735c` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC7884704.1/PMC7884704.1.pdf) | A randomised phase 2b study comparing the efficacy and safety of belotecan vs. topotecan as monotherapy for sensitive-relapsed small-cell lung cancer (British Journal of Cancer, 2020) |
| P7 | `PMC7341887.1.pdf` | 507,077 | `a9108985878d1ea5cf1b19cc0323b33abb84e9267791f4112df8f22b89056bdf` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC7341887.1/PMC7341887.1.pdf) | Phase 2 study of NAB-paclitaxel in SensiTivE and refractory relapsed small cell lung cancer (SCLC) (NABSTER TRIAL) (British Journal of Cancer, 2020) |
| P8 | `PMC13710598.1.pdf` | 594,589 | `6415898f323b692949da04def2265f4aafe7c40182ddc0299325f65454faf55d` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC13710598.1/PMC13710598.1.pdf) | Tarlatamab in small cell lung cancer following platinum-based chemotherapy: subgroup analysis of Japanese patients from the DeLLphi-304 study (International Journal of Clinical Oncology, 2026) |
| P9 | `PMC13255975.1.pdf` | 690,712 | `3585f026d74138398e972f6c8dbc553f1d8d6a322a930305629c28854cd6f6b3` | [Download](https://pmc-oa-opendata.s3.amazonaws.com/PMC13255975.1/PMC13255975.1.pdf) | Tarlatamab in Previously Treated Small Cell Lung Cancer: A Real-World Experience in a Predominantly Hispanic Population with CNS Metastases (Cancers, 2026) |

## 3. System requirements

| Applies to | Requirement | Minimum | Recommended | Actually tested |
|---|---|---|---|---|
| App | OS and version | Not validated | Windows 11 | Windows 11 (two runs, 2026-11-18) |
| App | CPU architecture | Not validated | x64 | x64 |
| App | CPU family / cores | Not validated | Not specified | **Pending** |
| App | RAM | Not validated | Not specified | **Pending** |
| App | GPU / VRAM | N/A | N/A | N/A |
| App | Free storage | Not validated | 1 GB (papers about 18 MB, plus the local index) | **Pending** |
| Services | Node pools | N/A | N/A | N/A |

**Bookshelf — local, tested profile values:**

| Field | Tested profile value |
|---|---|
| Source corpus | 15 documents; 18,433,195 bytes of PDF; corpus `sclc-literature-v1` |
| Index | **Pending** (record indexed size and chunk count shown after indexing) |
| Indexing recipe | App defaults for a local Bookshelf: embedding model `text-embedding-3-small (Copilot)`; answer generation **GPT-6 Astra** (or its newer version or an equivalent model); chunking settings are not exposed in the form |
| Index-ready condition | The Bookshelf shows **Successful** with 15 files, and a test question returns citations from these papers |

## 4. Prerequisites

- **Access:** Microsoft Discovery app; GitHub account with a GitHub Copilot subscription; access to GPT-6 Astra or its newer version or an equivalent model.
- **Environment:** Internet access to `pmc-oa-opendata.s3.amazonaws.com` and `raw.githubusercontent.com`. No Python, containers or Azure resources are needed.
- **Container runtime:** None needed. Docker, Docker Desktop and Podman are not required.
- **Authentication:** App sign-in only. No secrets are used.
- **Data:** All 15 papers are PubMed Central open-access articles recorded as **CC BY 4.0**, and none is marked retracted. Keep attribution. The papers are downloaded from their sources, not redistributed in this repository. When the Bookshelf is built and queried, the app sends document chunks and questions to GitHub using the user's Copilot account; this is acceptable here because the papers are public.

## 5. Setup — one reproducible reference path

1. **Select profile:** `sclc-literature-v1`, local App project, GPT-6 Astra (or its newer version or an equivalent model).
2. **Install/provision:** App only. Services: N/A.
3. **Download and verify the papers (assistant):** with the user's permission, create a `sclc-papers` folder in the open project and download all 15 files from section 2 into it. Download with `curl.exe --fail --location --retry 3 --connect-timeout 20 --max-time 120`, one file at a time, and skip files that already pass; don't use PowerShell `Invoke-WebRequest`, which can hang with no timeout. If a file fails or times out, retry it once more, then continue with the rest. Check each file's size and SHA-256. Report a table of all 15 with pass or fail. **Done when:** 15 of 15 pass.
4. **Create the Bookshelf (assistant if the app allows it):** if your Bookshelf tool can create shelves (for example a `bookshelf` tool with `create`, `add_content` and `start_indexing` actions), ask the user's permission, then create a shelf named `sclc-literature` with the description `Fifteen open-access papers on small-cell lung cancer treatment.`, add the 15 PDFs from `sclc-papers`, start indexing, and check `status` until indexing has finished for all 15 files. Tell the user which answer model the shelf uses. **Not yet tested end to end; report any error exactly.** If your tools cannot create a Bookshelf, start your final chat reply (not a progress or thinking line, and not inside a collapsed tool step) with the sentence **"I can't create the Bookshelf for you, so please fill in this form in the app:"**, then write all of these steps and values in your normal chat reply, as a numbered list the user can read without expanding anything. Never put the steps only in a tool-call title, progress line or collapsed step. End the reply with the line **"Take your time. When the Bookshelf shows Successful in green, click Yes below."** Then ask exactly one question, with clickable choices so the user never has to type: "Have you created sclc-literature with the form, and does it show Successful?" with the choices **Yes, it shows Successful**, **Not yet: show me the steps**, **It shows Failed** and **I used a different model**. If the user picks **Not yet: show me the steps**, reply with only the numbered form steps below as plain text (no tool call), then ask the same question again. Don't call any Bookshelf tool (list, search, ask or status) until the user answers: the local Bookshelf engine runs one job at a time, and a call during indexing makes indexing fail with "capacity is occupied". If the user picks **It shows Failed**, tell them to click **Retry indexing** on the Bookshelf, wait for **Successful** (in green), and ask the same question again. Assume the answer generation model is GPT-6 Astra unless the user picks **I used a different model**. In that case, continue normally and note in Step 3 that the run used a newer or equivalent model instead of GPT-6 Astra. Don't ask the user to confirm each step, and don't ask free-text questions during setup.
   1. In the left sidebar, click **AI capabilities** (it opens in a new tab at the top of the app), then the **Bookshelves** tab, then **New bookshelf**. The first time, a box asks "Use GitHub Copilot for Bookshelf answers in this workspace?": click **Use Copilot answers**.
   2. On **1. Details**: **Name** `sclc-literature` (3 to 24 letters, numbers or hyphens); **Description** `Fifteen open-access papers on small-cell lung cancer treatment.` (optional); **Answer generation** is required. Wait for the model list to load, then choose **GPT-6 Astra**; if it isn't in the list, choose its newer version or an equivalent model. Leave **Embedding model** (below it) as it is. Click **Next**.
   3. On **2. Files**: click **Upload**, choose **Folder** ("Add an entire folder"), select the project's `sclc-papers` folder and confirm. Click the arrow next to `sclc-papers` in the file list to expand it and check that 15 PDFs are listed. Click **Next**.
   4. On **3. Review + create**: check the values and click **Create**.
   5. Wait while the status shows **Indexing**; don't send anything in the chat until it changes. When it shows **Successful** (in green), go back to the chat by clicking its tab at the top (or the session under **Sessions** on the left), then click **Yes, it shows Successful**.
5. **Verify readiness (assistant):** use your Bookshelf list tool (`list`, or `discovery.bookshelf.listShelves`) and confirm `sclc-literature` is listed (and, if a document count is shown, that it is 15). Then use your Bookshelf ask tool (`ask`, or `discovery.bookshelf.ask` with `shelfNames: ["sclc-literature"]`) with a short test question, for example "Which drug is studied in the LURBICLIN study?", and confirm the answer cites a paper from this set. **Done when:** the shelf is listed and the test answer is cited. If a Bookshelf question returns "Tool execution failed", ask it once more. If it fails again, don't list failed checks; tell the user only: "Click **New session** and paste the same step's prompt again. Your papers and Bookshelf are kept." If the Bookshelf tools are missing, stop and report the exact error. Apply the same rule in Steps 2 and 3.

## 6. Fixed prompt + matching output

**Binding:** profile `sclc-literature-v1`; Bookshelf `sclc-literature` built from the 15 papers in section 2; validated with GPT-6 Astra for both chat and Bookshelf answer generation. A newer version or an equivalent model is fine; wording will differ, and the run passes on the same checks.

**Exact predefined prompt**

```text
Using only the sclc-literature Bookshelf, summarise the current treatment options for extensive-stage small-cell lung cancer. Cover: (1) first-line chemo-immunotherapy and who is eligible; (2) second-line options after platinum-based chemotherapy, including lurbinectedin and topotecan-class agents; (3) DLL3-targeted therapy, including tarlatamab; and (4) what molecular subtypes or biomarkers suggest about who benefits. For every claim, cite the paper it comes from. End with a short table comparing the second-line options and a list of questions these papers cannot answer.
```

**Matching output** — answers are written by a model, so wording varies between runs. A run matches when it passes every check below.

| Acceptance | Check |
|---|---|
| Required format / artifacts | A written answer with four labelled parts, a second-line comparison table and a "not covered" list. Every factual claim has a citation to one of the 15 papers. |
| Exact checks | Cites only papers from this set (no outside sources). Mentions each of these treatments, which appear in the paper titles: durvalumab, lurbinectedin, topotecan, belotecan, nab-paclitaxel and tarlatamab. Cites at least one review (R1–R6) and at least one primary study (P1–P9). |
| Approximate / domain checks | Claims match the cited papers; no invented trial results or numbers; limitations stated where the papers disagree or are small studies. A reviewer spot-checks at least five citations against the PDFs. |
| Pass condition | All exact checks pass and the five spot-checked citations match their papers. |

**Assistant reply format:** In Step 2, give the answer only; don't mention or offer the citation audit, which is Step 3. In Step 3, put everything in the chat reply itself, in this order, without asking first: (1) the pass/fail table with one row per check above; (2) the five claims, each with the exact supporting passage and its paper; (3) a one-sentence verdict. Don't put them only in a saved file or a collapsed step.

## 7. Expected runtime

Two complete runs on Windows 11 x64, 2026-11-18, with GPT-6 Astra. Times are wall-clock in the chat and include the user clicking through prompts.

| Stage | Measured / Estimated | First response (optional) | Completion duration / range, with units | Conditions / observations / runs |
|---|---|---|---|---|
| One-time install/provision/setup | Measured | N/A | 1 to 3 min | Download and SHA-256 check of 18 MB of papers, including the download approval click; 15/15 passed |
| One-time data loading/indexing | Measured | N/A | 4 to 11 min | User fills in the Bookshelf form, then local indexing of 15 PDFs to **Successful** (in green) with no retry; the shelf reported 15 documents |
| Cold-start prompt run | Measured | 2.5 to 3 min | 5 to 6 min | Step 2 research question; in both runs the assistant asked one follow-up to fill retrieval gaps. Step 3 check took 2 to 3 min |
| Warm prompt run | Pending | Pending | Pending | Repeat question in the same session; not measured |

## 8. Troubleshooting, cleanup and extensions

- **A step shows no new messages for 10 minutes:** click **New session** and paste the same step's prompt again. Papers that already passed are kept.
- **A download fails or a checksum doesn't match:** re-download that one file from its link in section 2. Do not substitute another version of the paper.
- **Indexing shows Failed with "capacity is occupied":** the local Bookshelf engine runs one job at a time and something used it during indexing. Click **Retry indexing** on the Bookshelf and don't use the chat until it shows **Successful** (in green).
- **Indexing shows Failed for another reason:** delete the Bookshelf and create it again with the same 15 files. Record the error shown.
- **Paper set note:** P9 was originally PMC12459094 (tarlatamab vs real-world physician's choice, The Oncologist 2025). That PDF's internal file index is damaged (saved with several incremental updates), so the app's local document converter finds 0 pages and indexing fails. It was replaced on 2026-11-17 by PMC13255975, a CC BY real-world tarlatamab study whose PDF the converter reads normally (10 pages).
- **No answer generation models are listed:** the app shows "This GitHub account has no compatible Bookshelf answer generation models." Check the GitHub Copilot sign-in and subscription; the Bookshelf can't be created without one.
- **Answers say details are "not established by retrieved passages":** the Bookshelf answers from the passages it retrieves, not whole papers, so some trial numbers (for example response rates or survival) may be missing even though the PDF contains them. This is expected; the answer should label them as retrieval gaps, not claim the papers lack them. Asking a narrower follow-up question about one paper usually retrieves more.
- **The Step 3 passage check fails with "Tool execution failed":** seen once on 2026-11-18 when asking the Bookshelf for exact passages. The assistant then read the downloaded PDFs directly with a local Python PDF library, which worked on the test machine but needs Python. If that isn't available, retry the Step 3 prompt once in the same chat.
- **"Tool execution failed":** click **New session** and paste the same step's prompt again. Your papers and Bookshelf are kept. (Seen 2026-11-18: the answer model briefly returned `BadRequestError`; a new session fixed it.)
- **A Bookshelf question fails with an error:** a transient error has been seen on local Bookshelf questions (model returned HTTP 409, reported as "Failed to ask local bookshelf: 500"); retrying in a new session succeeded. Record the error and retry once.
- **Cleanup:** delete the `sclc-literature` Bookshelf from **AI capabilities → Bookshelves** and delete the `sclc-papers` folder. No cloud resources are created.
- **Optional vertical addendum:** This is literature research, not medical advice. Answers summarise the 15 papers only and may be out of date.

## 9. Publication checklist

- [x] One reference path reproduced; versions, sample inputs and prompt fixed to the tested profile.
- [x] Output validated; exact/approximate acceptance criteria and domain checks explicit.
- [ ] Applicable configuration/specs complete; unused fields N/A; compatibility checked; no unverified minima claimed.
- [x] Timings labeled with conditions; setup/indexing distinct from cold/warm runs.
- [x] No secrets; samples permitted (CC BY 4.0, downloaded from source); cleanup documented. Owner, version and validation date recorded in section 1.
- [x] README completed from `README-Template.md`; its three step prompts are identical to **Copy-paste prompts (same as the README)** in this guide.
- [x] Every required file downloaded from its published link and checked against its recorded size and SHA-256; all links resolve; no `[Fill in]` placeholders remain. (15/15 papers re-verified 2026-11-17; unknown values are marked Pending.)
