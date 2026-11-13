# QuickStart BioPharma — CDK Target Selection and Lead Discovery

## Checklist

1. Install the [Discovery app](../../../README.md) and sign in.
2. Create a project in a new `Downloads\QuickStart-CDK-Lead-Discovery` folder and click **New session**.
3. Select **GPT-6 Astra**.
   *(Prefer to download the files yourself? Do [Route B](#route-b-download-the-files-yourself) here.)*
4. Send the [Step 1 prompt](#step-1-set-up-and-confirm-the-environment): set up and confirm the environment.
5. Send the [Step 2 prompt](#step-2-run-the-experiment): run the experiment.
6. Send the [Step 3 prompt](#step-3-verify-your-results-against-the-validated-reference): **your results**, compared with the validated reference.

## What this QuickStart does

Cyclin-dependent kinases (CDKs) are enzymes that control cell division and are
well-known cancer drug targets. In the original Discovery campaign, an AI-led
workflow chose a CDK target, gathered published evidence, docked about 1,100
candidate molecules against six CDKs, trained a solubility model, and ranked
the most promising leads.

This QuickStart is a **frozen-reference run**: it repeats part of the original
analysis to check that the results match. It uses a **snapshot**, a saved
copy of the original study's data and results, and on your own computer it will:

- Recalculate the target-selection decision scores.
- Predict water solubility for all 1,100 candidate molecules with the trained model.
- Rank the candidates and export the top 100 as ready-to-view 3D structures.
- Build a report and dashboard of the results.
- **Compare your results with the original run**, so you can see for yourself
  that they match.

It does not repeat the slow parts of the campaign (literature search, docking
and model training); it reuses their saved results. The results are
computational predictions, not lab-tested drugs. As in the original campaign,
no candidate is confirmed as broadly selective across the CDKs, and the docking
check for one target (CDK7) failed; your report keeps these limitations.

## What you need

| Requirement | Details |
| --- | --- |
| Discovery app | Download it from the [Discovery download page](../../../README.md) and follow the [install guide](../../../docs/discovery-app/install.md). |
| Sign-in | A GitHub account with a GitHub Copilot subscription. |
| Model | **GPT-6 Astra** (`gpt-6-astra`). Choose it in the chat's model menu. |
| Computer | Windows 11, 64-bit (tested). Other systems are untested. |
| Python | **Python 3.13.14, 64-bit**, exactly this version. If you don't have it, the assistant gives you the download link; it does not install Python for you. |
| Disk space | About 3 GB free. |
| Internet | Needed to download about 169 MB of files and the Python packages. |

## How long it takes

Times are from one measured run on a Windows 11 PC; yours will vary.

| Stage | Time |
| --- | --- |
| 1. Set up and confirm the environment | About 45 minutes the first time, including installing Python and 14 Python packages. Faster if Python is already installed. |
| 2. Run the experiment | About 45 minutes. The first ~37 minutes are quiet while the data is unpacked and checked; the analysis itself takes about 2 minutes. |
| 3. Verify against the reference | A few minutes. |

## What's in the files

There are six files. In route A below the assistant downloads them for you;
you don't need to open them.

- **`cdk_non_md_deliverables.zip` (168 MB): the snapshot**, a saved copy of
  the original study's data and results.
  It holds the original campaign's inputs, intermediate results and final
  outputs: the 1,100-molecule library, the evidence it used, the prepared
  protein structures, all 6,600 docking results, the trained solubility model,
  and the original rankings, report and dashboard. Your run recomputes the
  final stages from these inputs; the **original results in this file are the
  reference your results are compared against**.
- **`cdk_operational_bundle_v1.zip` (50 KB): the run kit.** The launcher that
  runs the experiment, the script that compares your results with the
  reference, and records from the validated reference run.
- **Four small checksum and manifest files**, used to confirm the two ZIPs
  downloaded correctly and haven't changed.

## Before you start: open a project and a chat

1. **Open Microsoft Discovery.** Sign in with your GitHub account if it asks.
2. **Create a project.** The app opens on **Projects**. Click **New project**.
   In the folder window, click **Downloads** on the left, then click
   **New folder** at the top left. Name it `QuickStart-CDK-Lead-Discovery`,
   click it once to select it, and click **Open local project**.
   (Avoid OneDrive-synced folders such as Documents or Desktop; syncing can
   interfere with the run. Discovery needs a project before you can chat. If a
   project is already open, click its name at the top left to get back to
   **Projects**.)
3. **Open a chat.** Click **New session** on the left.
4. **Select the model.** In the chat box, open the model menu and choose
   **GPT-6 Astra**.

The app shows **Allow once** boxes when the assistant opens a link or runs a
command. To stop clicking each one, click the arrow next to **Allow once** and
choose **Allow for this session**. That applies only to this chat; the
assistant still asks you in the chat before downloading, installing or
starting the run.

## Run it in three steps

Copy each prompt into the chat in order. Wait for each step to finish before
sending the next one, and answer the assistant's questions along the way.

There are two ways to get the files, and each step has a prompt for both:

- **A. The assistant downloads them (recommended):** skip straight to
  [Step 1](#step-1-set-up-and-confirm-the-environment) and use the **A** prompts.
- **B. You download them yourself:** follow the steps below, then use the
  **B** prompts.

### Route B: download the files yourself

1. **Download these seven files.** Right-click each link, choose
   **Save link as**, and save it into your
   `Downloads\QuickStart-CDK-Lead-Discovery` project folder. Keep each
   filename exactly as it is.

   | # | File | What it is |
   | --- | --- | --- |
   | 1 | [QuickStart-BioPharma LeadGen v0.11.md](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/QuickStart-BioPharma%20LeadGen%20v0.11.md) | The guide (you'll attach this in Step 1) |
   | 2 | [cdk_non_md_deliverables.zip](https://github.com/microsoft/discovery/releases/download/cdk-frozen-reference-v0.11/cdk_non_md_deliverables.zip) | The original campaign data and reference results (168 MB) |
   | 3 | [cdk_non_md_deliverables.sha256](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/files/cdk_non_md_deliverables.sha256) | Checksum for file 2 |
   | 4 | [cdk_operational_bundle_v1.zip](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/files/cdk_operational_bundle_v1.zip) | The run kit (50 KB) |
   | 5 | [cdk_operational_bundle_v1.sha256](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/files/cdk_operational_bundle_v1.sha256) | Checksum for file 4 |
   | 6 | [cdk_operational_bundle_v1_manifest.csv](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/files/cdk_operational_bundle_v1_manifest.csv) | List of what's inside file 4 |
   | 7 | [cdk_operational_bundle_v1_validation.json](https://raw.githubusercontent.com/microsoft/discovery/main/quickstarts/biopharma/cdk-frozen-reference/files/cdk_operational_bundle_v1_validation.json) | Verification record for file 4 |

2. **Check the folder.** Open `Downloads\QuickStart-CDK-Lead-Discovery` in File
   Explorer. You should see exactly these seven files. If Windows added
   `(1)` or `.txt` to a name, rename it back. **Don't unzip the ZIP files**;
   the assistant handles that.
3. **Open the project and chat** as described in
   [Before you start](#before-you-start-open-a-project-and-a-chat), selecting
   this same folder.
4. **Attach the guide.** In the chat box, click the attachment button, select
   `QuickStart-BioPharma LeadGen v0.11.md`, and click **Attach files**. Check
   that the filename appears above the chat box.
5. **Send the Step 1 B prompt below**, then continue with Steps 2 and 3.

### Step 1: Set up and confirm the environment

**A. The assistant downloads the files:**

```text
Set up this QuickStart: https://github.com/microsoft/discovery/blob/main/quickstarts/biopharma/cdk-frozen-reference/QuickStart-BioPharma%20LeadGen%20v0.11.md
Read the whole guide and tell me in plain language what this experiment does. Then prepare this project for the default frozen-reference run: download the six required files into this project, check each file's size and checksum, check the model, Python 3.13.14, disk space and local access, show me the 14 required Python packages, and install what's needed. Ask me before downloading and before installing anything. Do not start the computation. Finish by telling me whether the environment is ready and what, if anything, still needs my action.
```

**B. You downloaded the files yourself** (after [Route B](#route-b-download-the-files-yourself)
steps 1–4, with the guide attached), send:

```text
Set up this QuickStart from the attached guide, using the six required files already in this project. Read the whole guide and tell me in plain language what this experiment does. Then prepare this project for the default frozen-reference run: check each file's size and checksum, check the model, Python 3.13.14, disk space and local access, show me the 14 required Python packages, and install what's needed. Ask me before installing anything. Do not start the computation. Finish by telling me whether the environment is ready and what, if anything, still needs my action.
```

**Done when:** the assistant says the environment is **Ready** and the
preflight check passed.

### Step 2: Run the experiment

**A or B (same prompt either way):**

```text
Run the default frozen-reference computation from the guide. Before starting, tell me exactly what will run, what will not run, and how long it should take, and ask for my approval. While it runs, check progress no more than every 5 to 10 minutes and don't restart it. When it finishes, tell me whether every stage completed and show me the run ID and receipt.
```

When it asks for approval, reply:

```text
I approve the bounded fixed-input computation for cdk-frozen-reference-v1. No new docking, training or data retrieval.
```

**Done when:** the assistant reports that all stages completed and gives you a
run ID.

### Step 3: Verify your results against the validated reference

**A or B (same prompt either way):**

```text
Compare my new run with the validated reference result. Use my run's semantic_acceptance.json and receipt.json, not the historical files in validation/. Show me a table of every comparison with pass or fail and any differences, and confirm each of these: the target decision still recommends CDK4 with CDK2 as the alternative; all 1,100 solubility predictions match; the top 100 candidates match in order, identity and 3D coordinates; all 6,600 docking pairs are accounted for; and the limitations are kept (no confirmed broadly selective lead, and the CDK7 check failed). Then open my report and dashboard, give me links to them, and tell me in one sentence whether my run reproduced the reference.
```

**Done when:** every comparison passes and the assistant links your new
report and dashboard. If anything fails, keep the run ID and the error; don't
start a second run without asking the assistant first.

**Availability:** All required files are publicly available. The 168 MB
scientific snapshot is downloaded from the
[`cdk-frozen-reference-v0.11` release](https://github.com/microsoft/discovery/releases/tag/cdk-frozen-reference-v0.11);
the other five files are in this scenario's [`files`](files/) folder.
Steps checked on Windows with Discovery app version 0.0.4.

## Details: what the assistant does at each stage

The assistant follows the guide and asks you before each step.

### Setup

The assistant checks the model, OS/architecture, Python, files, space and access.
The reference needs **Python 3.13.14, 64-bit**. If absent, the guide supplies
the publisher installation steps; then the assistant rechecks the exact
interpreter. **pip installs packages, not Python itself.** Do not automatically
uninstall or downgrade another Python to resolve a mismatch.

It shows **all 14 packages** from the guide and asks the full-set **Yes/No in
ordinary chat**. Yes selects them; it does not authorize installation. After
source integrity, a short destination and other readiness checks pass, approve
the required file preparation and installation separately.

The assistant verifies both ZIPs and the complete supplied manifest, safely
unpacks the **small operational ZIP only** into the new project root, and leaves
the large snapshot zipped beside the launcher. It preserves the older bundled
guide at its manifest-listed path but follows the v0.11 guide instead.

The supplied `workflow.py setup --consent-install` creates an isolated
environment and installs the pinned packages from the snapshot. Use its
printed interpreter for package checks and preflight.

### Run the experiment

After successful setup/preflight, choose the offered run mode and separately
approve bounded computation. The native command is
`workflow.py run --approve-compute` with the verified isolated Python.
The guide's prompts and safety gates govern, not an implied approval in this README.

Default scope recomputes scoring, saved-model inference and ranking; it reuses
docking, training, evidence and narrative. No CLIO, fresh retrieval, new docking
or training is required. A historical first run was quiet for about 37 minutes
before stage 1; that is an observation, not a guaranteed duration. Follow the
guide's progress instructions, honor cancellation and preserve errors.

### Check your results

Use the **new run's** receipt, semantic acceptance, stage logs, dashboard and
100-structure exports. Historical files inside `validation/` are comparison
evidence, not this run's outputs. A previous frozen run passed seven listed
semantic comparisons; this updated customer route is still awaiting its own
recorded test. Keep the guide's scientific limitations visible.

The supplied v0.11 guide is a proposed revision. Windows x64 has historical
reference evidence; other scientific-platform routes are unvalidated.

## Supporting files

The assistant downloads these six files for you in route A; in route B you
download them yourself. A different snapshot is not interchangeable with this
reference.

| Original filename | Bytes | SHA-256 | Purpose | Repository download |
| --- | ---: | --- | --- | --- |
| `cdk_operational_bundle_v1.zip` | 50,301 | `874eba9d9e1ee72d38c257f7904d93953bcb8dc2ec55cf4c2732009c57e74f2f` | Small launcher bundle | [Download](files/cdk_operational_bundle_v1.zip) |
| `cdk_operational_bundle_v1.sha256` | 97 | `a793e0bb6e34945ad04e230d1b185f66eebd1861219962f9afcff31ebeb46325` | Exact checksum for the small ZIP | [Download](files/cdk_operational_bundle_v1.sha256) |
| `cdk_operational_bundle_v1_manifest.csv` | 2,130 | `04bfa2ab5f0b4095dcf94d3e37ba1019e5f8d4fe6dfa281835ca9a389bbac474` | Original member paths, sizes and hashes | [Download](files/cdk_operational_bundle_v1_manifest.csv) |
| `cdk_operational_bundle_v1_validation.json` | 1,152 | `0709258b42b18800e7eb4414c965862715370ce1c28f5d9721c3bcb1eceea71f` | Original handoff verification record | [Download](files/cdk_operational_bundle_v1_validation.json) |
| `cdk_non_md_deliverables.zip` | 168,396,900 | `bfc939735a574ccc2375ae9808e9242fb79efc545d5b3f314cc38e5d0cefa076` | Exact frozen scientific snapshot | [Download from release](https://github.com/microsoft/discovery/releases/download/cdk-frozen-reference-v0.11/cdk_non_md_deliverables.zip) |
| `cdk_non_md_deliverables.sha256` | 95 | `702e1df41eb1b1d22106487e0c003b3b5109c06bdbb0c4e4504af110cd24c07b` | Exact checksum for the large ZIP | [Download](files/cdk_non_md_deliverables.sha256) |

The large ZIP's SHA-256 is
`bfc939735a574ccc2375ae9808e9242fb79efc545d5b3f314cc38e5d0cefa076`.
It is too large for a regular repository file, so it is hosted in the release
above and is not included in a repository checkout or source-code ZIP.

### What is inside the small ZIP?

The ZIP contains `workflow.py`, `profile.json`, `launch.ps1`, `acceptance.py`,
the offline guard, tests, manifest, and a **validation folder** with reference
receipts and stage logs. Preserve all member paths, including the older guide;
follow the v0.11 guide for instructions. The launcher extracts the
large snapshot during the approved workflow.

Retain the snapshot's MIT campaign-code licence and source-specific data notices.