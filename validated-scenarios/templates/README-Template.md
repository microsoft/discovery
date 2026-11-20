<!--
AUTHORING INSTRUCTIONS: delete this comment when the README is complete.
This is the scenario README: the page a non-expert scientist follows with only the Discovery app installed.
Complete it together with the guide made from Validated-Scenario-Template.md, and save it as README.md beside the guide.
- Write in plain English. Explain every technical term the first time it appears.
- The prompts in "Run it in three steps" must be identical, word for word, to the guide's "Copy-paste prompts (same as the README)" section.
- Take every fact (model, versions, times, file sizes, SHA-256) from the guide or from recorded run evidence. Never invent one; write "Pending" if it is not known yet.
- Keep these headings and their order; the Checklist links depend on them. Use N/A for anything that does not apply.
-->

# Validated Scenario [Fill in: vertical] — [Fill in: scenario title]

## Checklist

1. Install the [Discovery app](https://github.com/microsoft/discovery/blob/main/README.md) and sign in.
2. Create a project in a new `Downloads\[Fill in: Validated-Scenario-Scenario-Name]` folder and click **New session**.
3. Select **[Fill in: model]**, or its newer version or an equivalent model if it's no longer listed.
   *(Prefer to download the files yourself? Do [option B](#option-b-download-the-files-yourself) here.)*
4. Send the [Step 1 prompt](#step-1-set-up-and-confirm-the-environment): set up and confirm the environment.
5. Send the [Step 2 prompt](#step-2-run-the-experiment): run the experiment.
6. Send the [Step 3 prompt](#step-3-verify-your-results-against-the-validated-reference): **your results**, compared with the validated reference.

## What this Validated Scenario does

[Fill in: two or three short paragraphs in plain English. What scientific question this answers; what the assistant will do on the user's computer, as a bullet list; what the user sees at the end; what it does not do; and the key scientific limitations the results keep.]

## What you need

| Requirement | Details |
| --- | --- |
| Discovery app | Download it from the [Discovery download page](https://github.com/microsoft/discovery/blob/main/README.md) and follow the [install guide](https://github.com/microsoft/discovery/blob/main/docs/discovery-app/install.md). |
| Sign-in | A GitHub account with a GitHub Copilot subscription. |
| Model | Validated with **[Fill in: model]** (`[Fill in: model id]`). If it's no longer in the model menu, choose its newer version or an equivalent model. |
| Computer | [Fill in: tested OS and architecture]. Other systems are untested. |
| Software | [Fill in: exact runtimes and versions, and whether the assistant installs them; or N/A] |
| Container runtime | [Fill in one: **None needed.** *or* **Podman** (recommended, free): [install Podman](https://podman.io/docs/installation). Docker also works if you already have it running. Tested with: <runtime and version>.] |
| Disk space | [Fill in] |
| Internet | [Fill in: what is downloaded and its total size] |

## How long it takes

[Fill in: "Times are from N measured run(s) on …" or "Not measured yet".]

| Stage | Time |
| --- | --- |
| 1. Set up and confirm the environment | [Fill in] |
| 2. Run the experiment | [Fill in, including any long quiet periods the user should expect] |
| 3. Verify against the reference | [Fill in] |

## What's in the files

[Fill in: one bullet per required file or file group, in plain English: what it is, its size, and which file holds the validated reference results that Step 3 compares against.]

## Before you start: open a project and a chat

1. **Open Microsoft Discovery.** Sign in with your GitHub account if it asks.
2. **Create a project.** The app opens on **Projects**. Click **New project**.
   In the folder window, click **Downloads** on the left, then click
   **New folder** at the top left. Name it `[Fill in: Validated-Scenario-Scenario-Name]`,
   click it once to select it, and click **Open local project**.
   (Avoid OneDrive-synced folders such as Documents or Desktop; syncing can
   interfere with the run. If a project is already open, click its name at the
   top left to get back to **Projects**.)
3. **Open a chat.** Click **New session** on the left.
4. **Select the model.** In the chat box, open the model menu and choose
   **[Fill in: model]** (or its newer version or an equivalent model if it's no longer listed).

## Run it in three steps

Copy each prompt into the chat in order. Wait for each step to finish before
sending the next one, and answer the assistant's questions along the way.

There are two ways to get the files. Pick one:

### Option A: the assistant downloads the files (recommended)

Nothing to do yet. Go straight to
[Step 1](#step-1-set-up-and-confirm-the-environment) and use the **A** prompt.

### Option B: download the files yourself

1. **Download these files.** Right-click each link, choose **Save link as**,
   and save it into your `Downloads\[Fill in: Validated-Scenario-Scenario-Name]` project
   folder. Keep each filename exactly as it is.

   | # | File | What it is |
   | --- | --- | --- |
   | 1 | [Fill in: guide filename, linked to its raw.githubusercontent.com URL] | The guide (you'll attach this in Step 1) |
   | [Fill in] | [Fill in: one row per required file, with its direct download link] | [Fill in] |

2. **Check the folder.** You should see exactly these files. If Windows added
   `(1)` or `.txt` to a name, rename it back. Don't unzip anything; the
   assistant handles that.
3. **Open the project and chat** as described in
   [Before you start](#before-you-start-open-a-project-and-a-chat), selecting
   this same folder.
4. **Attach the guide.** In the chat box, click the attachment button, select
   the guide, and click **Attach files**. Check that the filename appears above
   the chat box.
5. **Send the Step 1 B prompt below**, then continue with Steps 2 and 3.

### Step 1: Set up and confirm the environment

**A. The assistant downloads the files:**

```text
[Fill in: Step 1 A prompt. Start with "Set up this Validated Scenario:" and the guide's GitHub link. Ask the assistant to explain the experiment in plain language, download and check every required file, check the environment, and ask before downloading or installing. If the Validated Scenario uses containers, add: "Check whether Podman or Docker is installed and running. If neither is, ask me before installing Podman. Don't install Docker Desktop." End with "Do not start the computation."]
```

**B. You downloaded the files yourself** (after [option B](#option-b-download-the-files-yourself)
steps 1–4, with the guide attached), send:

```text
[Fill in: Step 1 B prompt. Same as A, but "from the attached guide, using the files already in this project" and without the download.]
```

**While Step 1 runs:**

- **Allow once boxes:** the app shows these when the assistant opens a link or
  runs a command. Click the arrow next to **Allow once** and choose
  **Allow for this session** so you don't have to click each one. That applies
  only to this chat; the assistant still asks before downloading, installing or
  running anything.
- **Collapsed steps:** if a line in the chat ends with an arrow (**>**), click
  the arrow to expand it and see the details.

**Done when:** [Fill in: observable ready check, for example "the assistant says the environment is Ready".]

### Step 2: Run the experiment

**A or B (same prompt either way):**

```text
[Fill in: Step 2 launch prompt. Ask the assistant to say what will and won't run and how long it takes, ask for approval, and report completion with a run ID.]
```

When it asks for approval, reply:

```text
[Fill in: exact approval reply, naming the scenario and its limits; or delete this block if no approval is needed.]
```

**Done when:** [Fill in: observable completion check, for example a run ID.]

### Step 3: Verify your results against the validated reference

**A or B (same prompt either way):**

```text
[Fill in: Step 3 prompt. Name the new run's output files to compare (not the stored reference copies), list each acceptance check from guide section 6, ask for a pass/fail table and links to the results, and a one-sentence verdict.]
```

**Done when:** [Fill in: every acceptance check passes.] If anything fails, keep
the run ID and the error; don't start a second run without asking the assistant
first.

**Something went wrong or was unclear?** In the same chat, send:
`Write a short problem report for this Validated Scenario: the scenario, the step, the model I used, my operating system, the exact error or reply, and what you tried. Leave out secrets, tokens and personal file paths.`
Then paste the report into a [Validated Scenario feedback issue](https://github.com/microsoft/discovery/issues/new?template=validated-scenario-feedback.yml).

## Supporting files

| Original filename | Bytes | SHA-256 | Purpose | Download |
| --- | ---: | --- | --- | --- |
| [Fill in] | [Fill in] | [Fill in] | [Fill in] | [Fill in: direct link] |
