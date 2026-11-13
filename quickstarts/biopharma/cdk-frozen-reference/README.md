# QuickStart BioPharma — CDK Target Selection and Lead Discovery

Reproduce the final stages of a CDK drug-discovery experiment: Discovery
recalculates decision scores, predicts solubility for 1,100 molecules, ranks
100 candidate structures, and checks your results against the original run.

## How to run this QuickStart

You only need the Discovery app. You don't download, attach or unzip any files:
the assistant reads the guide from its link and gets everything it needs.

**Don't have the app yet?** Download it from the
[Discovery download page](../../../README.md) and follow the
[install guide](../../../docs/discovery-app/install.md). You need a
**GitHub account with a GitHub Copilot subscription** to sign in, and about
3 GB of free disk space.

1. **Open Microsoft Discovery** (Stable). Sign in with your GitHub account if it asks.
2. **Create a project.** The app opens on **Projects**. Click **New project**.
   In the folder window, open **Documents**, click **New folder**, name it
   `QuickStart-BioPharma`, select it, and click **Open local project**.
   (Discovery needs a project before you can chat. If a project is already
   open, click its name at the top left to get back to **Projects**.)
3. **Open a chat.** Click **New session** on the left.
4. **Select the model.** In the chat box, open the model menu and choose
   **GPT-6 Astra**.
5. **Paste the guide link.** Right-click this link and choose **Copy link**:
   **[BioPharma QuickStart guide](QuickStart-BioPharma%20LeadGen%20v0.11.md)**.
   In the chat box, type `Run this QuickStart: `, paste the link
   (**Ctrl+V**), and press **Enter**.
6. **Answer the assistant's questions.** It asks before it downloads the files
   (about 169 MB), before it installs anything, and before it starts the run.
   Reply in the chat. When it finishes, it shows your results and whether they
   match the original run.

**One thing you may have to install yourself:** the experiment needs
**Python 3.13.14 (64-bit)**. If you don't have it, the assistant tells you and
gives you the download link. It does not install Python for you.

**Availability:** All required files are publicly available. The 168 MB
scientific snapshot is downloaded from the
[`cdk-frozen-reference-v0.11` release](https://github.com/microsoft/discovery/releases/tag/cdk-frozen-reference-v0.11);
the other five files are in this scenario's [`files`](files/) folder.
Button labels were checked against Discovery Stable 0.0.4 on Windows.

## What happens next

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

## If the assistant can't open the link

Use this only if the assistant reports that it cannot open GitHub links or
download files. Note exactly what it said, then:

1. Download the [guide](QuickStart-BioPharma%20LeadGen%20v0.11.md) and the
   six files under [Supporting files](#supporting-files) into a new empty
   folder, for example `QuickStart-BioPharma` in Downloads. Keep the original
   filenames and don't unzip anything. On GitHub file pages, use
   **Download raw file**; don't save the web page.
2. In Discovery Stable, click **New project**, select that folder, click
   **Open local project**, then **New session**. Select **GPT-6 Astra**.
3. Attach `QuickStart-BioPharma LeadGen v0.11.md` with the chat's attachment
   control and send:

```text
Run the attached BioPharma QuickStart using the files in this project. Read the whole guide, then walk me through setup, the default frozen-reference run, and checking my results against the reference. Ask me before installing anything or starting the computation.
```

Everything under [What happens next](#what-happens-next) then applies.

## Supporting files

The assistant downloads these six files for you. They are listed here for
reference and for the fallback above. A different snapshot is not
interchangeable with this reference.

| Original filename | Purpose | Repository download |
| --- | --- | --- |
| `cdk_operational_bundle_v1.zip` | Small launcher bundle, 50,301 bytes | [Download](files/cdk_operational_bundle_v1.zip) |
| `cdk_operational_bundle_v1.sha256` | Exact checksum for the small ZIP | [Download](files/cdk_operational_bundle_v1.sha256) |
| `cdk_operational_bundle_v1_manifest.csv` | Original member paths, sizes and hashes | [Download](files/cdk_operational_bundle_v1_manifest.csv) |
| `cdk_operational_bundle_v1_validation.json` | Original handoff verification record | [Download](files/cdk_operational_bundle_v1_validation.json) |
| `cdk_non_md_deliverables.zip` | Exact frozen scientific snapshot, 168,396,900 bytes | [Download from release](https://github.com/microsoft/discovery/releases/download/cdk-frozen-reference-v0.11/cdk_non_md_deliverables.zip) |
| `cdk_non_md_deliverables.sha256` | Exact checksum for the large ZIP | [Download](files/cdk_non_md_deliverables.sha256) |

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