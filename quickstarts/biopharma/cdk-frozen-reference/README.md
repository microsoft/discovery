# BioPharma — start here

Reproduce a frozen-reference lead-generation workflow with the
**[BioPharma v0.11 QuickStart guide](QuickStart-BioPharma%20LeadGen%20v0.11.md)**.

**Availability:** The guide and operational files are available. The required
scientific snapshot has no public download yet; do not start without it.

The authorized publication target is the dedicated `cdk-frozen-reference-v0.11`
release in `microsoft/discovery`. **Publication is pending a maintainer upload.**
The preparation command below fails closed until that exact asset is publicly
available; an approved target is not evidence that the file has been published.

## 1. Get the guide and its files

Obtain the guide and the **six required files** listed under
[Supporting files](#supporting-files). Keep their original filenames.

Create a new short folder, for example `CDK-run` in Downloads. Put the guide,
both unopened ZIPs, both checksum files, manifest CSV and validation JSON in it.
Do not copy old sessions or installed environments. The small ZIP includes
the launcher and historical validation files.

### Starting from the GitHub scenario URL

Give Discovery this scenario's GitHub URL and ask it to read this README before
following the full guide. A repository URL alone is not proof that its release
assets were downloaded or its runner activated.

Obtain a checkout or GitHub source-code ZIP of `microsoft/discovery`, retaining
the repository layout. From its root, use an existing Python 3.10+ interpreter:

```console
python quickstarts/biopharma/cdk-frozen-reference/download_inputs.py --destination ../CDK-run
```

Choose a **new, short destination outside the checkout** whose parent exists.
On Windows, keep the checkout short too; deep paths can exceed filesystem limits.
This preparation helper uses only Python's standard library. The scientific
workflow still requires the separate Python 3.13.14 interpreter described below.

The helper copies the full guide and five small original files from the checkout,
downloads the unchanged scientific ZIP from the dedicated upstream release, and
checks all seven files against the existing exact-byte inventory. It also copies
the shared runner as `quickstart-runner.md` and the repository licence. Both ZIPs
remain unopened. No installation, scientific work or automatic skill activation
occurs. It refuses existing destinations, missing releases and incorrect bytes;
there is no private-path, alternate-host or different-snapshot fallback.

Only after preparation succeeds, open the destination in Discovery and attach
the full guide and `quickstart-runner.md` explicitly (manual skill loading).
Continue with the approval gates below. Keep the checkout for the instructions.

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
| `cdk_non_md_deliverables.zip` | Exact frozen scientific snapshot, 168,396,900 bytes | **Public download not yet available** |
| `cdk_non_md_deliverables.sha256` | Exact checksum for the large ZIP | [Download](files/cdk_non_md_deliverables.sha256) |

The large ZIP's SHA-256 is
`bfc939735a574ccc2375ae9808e9242fb79efc545d5b3f314cc38e5d0cefa076`.
The snapshot is not included in the repository checkout or source-code ZIP.

### What is inside the small ZIP?

The ZIP contains `workflow.py`, `profile.json`, `launch.ps1`, `acceptance.py`,
the offline guard, tests, manifest, and a **validation folder** with reference
receipts and stage logs. Preserve all member paths, including the older guide;
follow the attached v0.11 guide for instructions. The launcher extracts the
large snapshot during the approved workflow.

Retain the snapshot's MIT campaign-code licence and source-specific data notices.

### Maintainer publication gate

Publish only the original `cdk_non_md_deliverables.zip`, **168,396,900 bytes**,
with SHA-256
`bfc939735a574ccc2375ae9808e9242fb79efc545d5b3f314cc38e5d0cefa076`.
Use the dedicated `cdk-frozen-reference-v0.11` release in `microsoft/discovery`,
not a personal fork, and do not mark it as the repository's latest product release.
Review the retained source-specific rights and absence of private material before
upload. Never overwrite a conflicting tag, release or asset.

The downloader's fixed target is the following **pending endpoint, not an
available download**:

```text
https://github.com/microsoft/discovery/releases/download/cdk-frozen-reference-v0.11/cdk_non_md_deliverables.zip
```

After publication, anonymously download and verify the exact size and SHA-256,
then update the availability notice, supporting-files table and only the
BioPharma entry in the shared
[download inventory](../../../skills/quickstart-runner/references/downloads.json).
Until then, retain the unavailable status and `publicationApproved: false`.
That inventory flag is the packaging gate, not evidence that approval to create
the release is absent. Do not mark the scenario runnable based on local bytes.