# BioPharma — start here

Reproduce a frozen-reference lead-generation workflow with the
**[BioPharma v0.11 QuickStart guide](QuickStart-BioPharma%20LeadGen%20v0.11.md)**.

**Availability:** All required files are publicly available. The 168 MB
scientific snapshot is downloaded from the
[`cdk-frozen-reference-v0.11` release](https://github.com/microsoft/discovery/releases/tag/cdk-frozen-reference-v0.11);
the other five files are in this scenario's [`files`](files/) folder.

## Quick start: paste the guide link into Discovery

1. In **Microsoft Discovery Stable**, click **New project**, create and select a
   new empty folder (for example `QuickStart-BioPharma` in Downloads), and click
   **Open local project**. Click **New session**.
2. In the chat's model menu, select **GPT-6 Astra**.
3. Paste this message and send it:

```text
Run this QuickStart: https://github.com/microsoft/discovery/blob/main/quickstarts/biopharma/cdk-frozen-reference/QuickStart-BioPharma%20LeadGen%20v0.11.md
Read the whole guide, download its required files into this project, and walk me through setup, the default frozen-reference run, and checking my results against the reference. Ask me before downloading, installing anything or starting the computation.
```

4. Answer the assistant's questions. It asks separately before downloading
   files (about 169 MB), selecting and installing packages, and starting the
   run. The run needs **Python 3.13.14, 64-bit**; if it is missing, the
   assistant gives you the installer link. Python is not installed automatically.

The steps below are the manual alternative.

## 1. Get the guide and its files

Obtain the guide and the **six required files** listed under
[Supporting files](#supporting-files). Keep their original filenames.

Create a new short folder, for example `CDK-run` in Downloads. Put the guide,
both unopened ZIPs, both checksum files, manifest CSV and validation JSON in it.
Do not copy old sessions or installed environments. The small ZIP includes
the launcher and historical validation files.

## 2. Create the project and load the runner

Open Discovery and choose its new/local-project action for this folder. A
folder picker hides files; this does not mean the folder is empty. Initialize
the project if prompted and start a **new session**.

Select **GPT-6 Astra (`gpt-6-astra`)**. Follow the
[shared runner instructions](../../../skills/quickstart-runner/README.md), then
attach the full v0.11 guide. Send:

> Use the quickstart-runner skill to follow the attached BioPharma v0.11
> QuickStart guide from these supplied files. Run the default frozen-reference
> scenario. Check readiness first, prepare the supplied bundle when approved,
> and keep dependency selection, installation and computation approvals separate.

If the runtime does not discover the skill, attach its SKILL.md explicitly
alongside the guide. Neither Markdown file is a Python program.

## 3. Follow setup in the guide

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
guide at its manifest-listed path but follows your attached v0.11 instead.

The supplied `workflow.py setup --consent-install` creates an isolated
environment and installs the pinned packages from the snapshot. Use its
printed interpreter for package checks and preflight.

## 4. Approve and run the frozen computation

After successful setup/preflight, choose the offered run mode and separately
approve bounded computation. The native command is
`workflow.py run --approve-compute` with the verified isolated Python.
The guide's prompts and safety gates govern, not an implied approval in this README.

Default scope recomputes scoring, saved-model inference and ranking; it reuses
docking, training, evidence and narrative. No CLIO, fresh retrieval, new docking
or training is required. A historical first run was quiet for about 37 minutes
before stage 1; that is an observation, not a guaranteed duration. Follow the
guide's progress instructions, honor cancellation and preserve errors.

## 5. Check the result

Use the **new run's** receipt, semantic acceptance, stage logs, dashboard and
100-structure exports. Historical files inside `validation/` are comparison
evidence, not this run's outputs. A previous frozen run passed seven listed
semantic comparisons; this updated customer route is still awaiting its own
recorded test. Keep the guide's scientific limitations visible.

The supplied v0.11 guide is a proposed revision. Windows x64 has historical
reference evidence; other scientific-platform routes are unvalidated.

## Supporting files

Place these six files beside the full v0.11 guide. Verify the checksums before
setup; a different snapshot is not interchangeable with this reference.

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
follow the attached v0.11 guide for instructions. The launcher extracts the
large snapshot during the approved workflow.

Retain the snapshot's MIT campaign-code licence and source-specific data notices.