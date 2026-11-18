# Validated Scenario Bookshelf — SCLC Treatment Literature Research

> **Draft, not yet validated.** The setup and paper set are ready to try. The
> research question is proposed and needs owner approval, and there is no
> reference answer yet. Your run helps create it.

## Checklist

1. Install the [Discovery app](../../../README.md) and sign in.
2. Create a project in a new `Downloads\Validated-Scenario-SCLC-Bookshelf` folder and click **New session**.
3. Select **GPT-6 Astra**.
   *(Prefer to download the papers yourself? Do [option B](#option-b-download-the-files-yourself) here.)*
4. Send the [Step 1 prompt](#step-1-set-up-and-confirm-the-environment): download the papers and build the Bookshelf.
5. Send the [Step 2 prompt](#step-2-run-the-experiment): ask the research question.
6. Send the [Step 3 prompt](#step-3-verify-your-results-against-the-validated-reference): **your answer**, checked against the acceptance criteria.

## What this Validated Scenario does

A **Bookshelf** is a searchable library you build inside Discovery from your
own documents. The assistant answers questions using only those documents and
cites which paper each fact comes from.

In this Validated Scenario you build a Bookshelf from **15 open-access research papers
on small-cell lung cancer (SCLC)**, an aggressive lung cancer. The papers
include treatment guidelines, reviews and clinical studies on first-line
chemo-immunotherapy, second-line drugs such as lurbinectedin and topotecan,
and newer DLL3-targeted drugs such as tarlatamab.

Then you ask one fixed research question: *what are the current treatment
options for extensive-stage SCLC, and what does the evidence say?* You get a
written answer where every claim cites one of the 15 papers, plus a comparison
table and a list of what the papers can't answer.

This is literature research, not medical advice. The answer only reflects
these 15 papers.

## What you need

| Requirement | Details |
| --- | --- |
| Discovery app | Download it from the [Discovery download page](../../../README.md) and follow the [install guide](../../../docs/discovery-app/install.md). |
| Sign-in | A GitHub account with a GitHub Copilot subscription. |
| Model | **GPT-6 Astra** (`gpt-6-astra`). Choose it in the chat's model menu. |
| Computer | Windows 11, 64-bit (expected). Not yet tested on any system. |
| Disk space | About 1 GB free. |
| Internet | Needed to download about 18 MB of papers. |
| Container runtime | None needed. You don't need Docker, Docker Desktop or Podman. |

No Python or Azure setup needed.

## How long it takes

From one run on Windows 11 (2026-11-18). Your times will vary.

| Stage | Time |
| --- | --- |
| 1. Set up and confirm (download papers, build and index the Bookshelf) | About 15 minutes: about 3 minutes to download and check the papers, then about 11 minutes to fill in the Bookshelf form and wait for indexing. |
| 2. Ask the research question | About 5 minutes (the first answer arrives after about 2.5 minutes; the assistant then asks a follow-up to fill gaps). |
| 3. Check the answer | About 2 minutes. |

## What's in the files

The 15 papers are listed with exact sizes, checksums and download links in
**section 2 of the [guide](Validated-Scenario-Bookshelf-SCLC-Literature.md)**. They
come straight from PubMed Central's open-access collection and are licensed
CC BY 4.0. They are not stored in this repository.

- **[manifest.json](files/manifest.json):** full details for each paper: title, journal, year, DOI, licence, download link and checksum.
- **[selection_sclc.json](files/selection_sclc.json):** the 15 paper IDs and each one's role (6 reviews or guidelines, 9 primary studies).

## Before you start: open a project and a chat

1. **Open Microsoft Discovery.** Sign in with your GitHub account if it asks.
2. **Create a project.** The app opens on **Projects**. Click **New project**.
   In the folder window, click **Downloads** on the left, then click
   **New folder** at the top left. Name it `Validated-Scenario-SCLC-Bookshelf`, click
   it once to select it, and click **Open local project**. (Avoid
   OneDrive-synced folders such as Documents or Desktop.)
3. **Open a chat.** Click **New session** on the left.
4. **Select the model.** In the chat box, open the model menu and choose
   **GPT-6 Astra**.

## Run it in three steps

Copy each prompt into the chat in order. Wait for each step to finish before
sending the next one.

There are two ways to get the papers. Pick one:

### Option A: the assistant downloads the files (recommended)

Nothing to do yet. Go straight to
[Step 1](#step-1-set-up-and-confirm-the-environment) and use the **A** prompt.

### Option B: download the files yourself

1. Open the [guide](Validated-Scenario-Bookshelf-SCLC-Literature.md) and go to the
   paper table in section 2.
2. In your `Validated-Scenario-SCLC-Bookshelf` folder, create a folder named
   `sclc-papers`.
3. For each of the 15 papers, right-click **Download**, choose
   **Save link as**, and save it into `sclc-papers`. Keep each filename
   exactly as it is (for example `PMC10378571.1.pdf`).
4. Check that `sclc-papers` has exactly 15 PDF files.
5. In the chat, attach the guide: click the attachment button, select
   `Validated-Scenario-Bookshelf-SCLC-Literature.md` (download it first with
   **Download raw file** on its GitHub page), and click **Attach files**.

### Step 1: Set up and confirm the environment

**A. The assistant downloads the papers:**

```text
Set up this Validated Scenario: https://github.com/faranm-stack/discovery/blob/docs/validated-scenarios/validated-scenarios/bookshelf/sclc-literature/Validated-Scenario-Bookshelf-SCLC-Literature.md
Read the whole guide and tell me in plain language what this experiment does. Then download the 15 papers into a sclc-papers folder in this project and check each file's size and checksum. Ask me before downloading. After that, create the sclc-literature Bookshelf from those 15 papers yourself with your Bookshelf tool: ask me first, then add all 15 PDFs, start indexing and wait until it is indexed, and tell me which answer model it uses. If your Bookshelf tools can't create a Bookshelf, tell me so, show me the guide's form steps and exact values as a numbered list in your reply, then ask me with clickable choices whether it shows Successfully indexed. Then ask it a short test question to confirm it works. Don't ask the research question yet. Finish by telling me whether everything is ready.
```

**B. You downloaded the papers yourself** (guide attached):

```text
Set up this Validated Scenario from the attached guide, using the 15 papers already in the sclc-papers folder of this project. Read the whole guide and tell me in plain language what this experiment does. Check each file's size and checksum. Then create the sclc-literature Bookshelf from those 15 papers yourself with your Bookshelf tool: ask me first, then add all 15 PDFs, start indexing and wait until it is indexed, and tell me which answer model it uses. If your Bookshelf tools can't create a Bookshelf, tell me so, show me the guide's form steps and exact values as a numbered list in your reply, then ask me with clickable choices whether it shows Successfully indexed. Then ask it a short test question to confirm it works. Don't ask the research question yet. Finish by telling me whether everything is ready.
```

**While Step 1 runs:**

- **Allow once boxes:** the app shows these when the assistant opens a link or
  runs a command. Click the arrow next to **Allow once** and choose
  **Allow for this session** so you don't have to click each one. That applies
  only to this chat; the assistant still asks before downloading anything.
- **Collapsed steps:** if a line in the chat ends with an arrow (**>**), click
  the arrow to expand it and see the details.

**What you'll click in Step 1:** the assistant asks you a few questions with
buttons. You don't type anything.

1. **May I download the 15 papers?** Click **Yes**.
2. The assistant creates the Bookshelf for you if it can. **Only if it can't**,
   it asks whether to create it with the app's form. Click **Yes**, then fill in
   the form:

   1. In the left sidebar, click **AI capabilities** (it opens in a new tab at
      the top of the app), then **Bookshelves**, then **New bookshelf**. If a
      box asks **Use GitHub Copilot for Bookshelf answers in this workspace?**,
      click **Use Copilot answers** (it appears only the first time).
   2. On **1. Details**, enter **Name** `sclc-literature` and **Description**
      `Fifteen open-access papers on small-cell lung cancer treatment.` Wait for
      the model list to load, then under **Answer generation** choose **GPT-6 Astra** (if it isn't
      listed, choose the first model). Leave **Embedding model** below it as it
      is. Click **Next**.
   3. On **2. Files**, click **Upload**, choose **Folder**, select the
      project's `sclc-papers` folder and confirm. Click the arrow next to
      `sclc-papers` in the file list to expand it and check that 15 PDFs are
      listed. Click **Next**.
   4. On **3. Review + create**, check the values and click **Create**.
   5. Wait while the status shows **Indexing**. Don't type in the chat until it
      changes to **Successfully indexed**. If it shows **Indexing failed**,
      click **Retry indexing** and wait again.
3. **Only if you filled in the form:** go back to the chat by clicking its tab
   at the top (or your session under **Sessions** on the left), then click
   **Yes, it shows Successfully indexed**.

**Done when:** all 15 papers pass their checksum, the Bookshelf shows
**Successfully indexed**, and the test question comes back with a citation.

**If you see "Tool execution failed":** wait 5 minutes, click **New session**,
and paste the same step's prompt again. Your papers and Bookshelf are kept.

**What you'll see when Step 1 finishes:** the assistant stops and waits for
you. Its last message says something like *"Everything is ready for the
research step. All 15 PDFs passed size and SHA-256 verification ... The
research question has not been asked."* It then shows:

- the short test question and its answer, with the cited paper under
  **Sources** (you can open the PDF there);
- a table of all 15 papers (R1 to R6, P1 to P9) with their file names, sizes and
  checksums, each marked **True**. It may open beside the chat.

It may also say it can't confirm the answer model itself. That's expected.
Paste the Step 2 prompt into the same chat to continue.

### Step 2: Run the experiment

**A or B (same prompt either way):**

```text
Ask the research question in section 6 of the guide, using only the sclc-literature Bookshelf. Show me the full answer with a citation for every claim, the second-line comparison table and the list of questions the papers can't answer. Tell me how long it took.
```

**Done when:** you have a full written answer with citations. The assistant
stops again after the answer; paste the Step 3 prompt into the same chat.

### Step 3: Verify your results against the validated reference

**A or B (same prompt either way):**

```text
Check your answer against the acceptance criteria in section 6 of the guide. Show me a table of each check with pass or fail: it cites only these 15 papers; it mentions durvalumab, lurbinectedin, topotecan, belotecan, nab-paclitaxel and tarlatamab; it cites at least one review (R1-R6) and at least one primary study (P1-P9); and it has the four parts, the table and the not-covered list. Then pick five claims and show me the exact passage in the cited paper that supports each one. Tell me in one sentence whether this run passes.
```

**Done when:** every check passes and the five spot-checked claims match
their papers. Save the answer: until there is an official reference answer,
a passing run reviewed by the owner becomes it.

## Supporting files

The 15 papers are listed with exact sizes, SHA-256 checksums and download
links in section 2 of the [guide](Validated-Scenario-Bookshelf-SCLC-Literature.md).
They are downloaded from PubMed Central, not stored in this repository.

| Original filename | Bytes | SHA-256 | Purpose | Download |
| --- | ---: | --- | --- | --- |
| `manifest.json` | 12,774 | `1acc677072de955f44393454cd3f66c856697e4d122b7c8208cd8842f3874711` | Each paper's title, journal, year, DOI, licence, download link and checksum | [Download](files/manifest.json) |
| `selection_sclc.json` | 1,541 | `c0229224c86755318948290d142729b14e78323d8b101b894e50a5c93c2b9246` | The 15 paper IDs and their roles (6 reviews or guidelines, 9 primary studies) | [Download](files/selection_sclc.json) |

## Status and next steps

- **Ready:** the 15 papers, their download links and checksums (all checked on 2026-11-17), and the setup steps.
- **Pending:** owner approval of the research question, a first timed run, and a reviewed reference answer.
- The papers are recorded as CC BY 4.0. Keep attribution when you share the answer.
