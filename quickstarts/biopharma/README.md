# BioPharma — start here

Run **[Quick-Start-BioPharma LeadGen v0.11.md](Quick-Start-BioPharma%20LeadGen%20v0.11.md)**.
This is the full 113,732-byte guide from the prepared CDK folder, unchanged.
It includes setup, all 14 dependencies, prompts, expected outputs and the
original scientific appendix. This README only tells you how to start it.

## 1. Get the guide and its files

Download the guide above and the **six required files** listed on
[the files page](files/README.md). Keep their exact filenames. The large
snapshot still needs its public repository-release download; do not begin with
only the guide. An author holding the supplied local copies can test that path
separately from public-download readiness.

Create a new short folder, for example `CDK-run` in Downloads. Put the guide,
both unopened ZIPs, both checksum files, manifest CSV and validation JSON in it.
Do not copy old sessions, virtual environments or a previous Discovery project.
The small ZIP already contains the launcher and `validation/` reference files;
they need not be downloaded individually or recreated.

## 2. Create the project and load the runner

Open Discovery and choose its new/local-project action for this folder. A
folder picker hides files; this does not mean the folder is empty. Initialize
the project if prompted and start a **new session**.

Select **GPT-6 Astra (`gpt-6-astra`)**. Follow the
[shared runner instructions](../../skills/quickstart-runner/README.md), then
attach the full v0.11 guide. Send:

> Use the quickstart-runner skill to follow the attached BioPharma v0.11
> QuickStart guide from these supplied files. Run the default frozen-reference
> scenario. Check readiness first, prepare the supplied bundle when approved,
> and keep dependency selection, installation and computation approvals separate.

The skill and Markdown are instructions for the assistant, not Python programs
to execute. If the runtime does not discover the skill, explicitly attach its
SKILL.md too and record that manual-loading route; do not claim discovery worked.

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

The approved owner `workflow.py setup --consent-install` creates an isolated
environment and uses pip for the pinned packages. There is no separately
invented requirements file here: the actual requirements come from the
snapshot and are installed by the supplied setup. Use its printed interpreter
for package checks and preflight, not whichever Python happens to be on PATH.

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

The v0.11 guide is a proposed revision pending owner review. Windows x64 has
historical reference evidence; other scientific-platform routes are unvalidated.
No installation, scientific run or release approval occurs by reading these files.