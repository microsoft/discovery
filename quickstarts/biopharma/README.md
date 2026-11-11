# QuickStart Scenarios — BioPharma

**Draft.** This package describes the owner-supplied CDK frozen-reference
workflow. Archive publication, owner review of these packaging changes and a
fresh-project test of the shared runner remain blockers. It is not a new
full discovery campaign or a published scenario-catalog entry.

## 1. Scenario identity

Recompute decision scoring, saved-model solubility inference for 1,100 eligible
parents and ranking/native exports for 100 exploratory structures. Preserve
the owner profile `cdk-frozen-reference-v1`. Evidence curation, receptor/ligand
preparation, 6,600 primary docking pairs, fitted-model training and report
narrative are **reused**. No new docking, training or scientific retrieval.

Source: Ash's operational bundle v1 and proposed guide revision 0.11, with
historical reference work dated 2026-11-02 and a second-machine run dated
2026-11-05. This shorter repository entry preserves the frozen prompt and
points to the owner asset inventory; it does not replace the separately
approved fresh-science extension or claim that extension is packaged here.

## 2. Configuration matrix

| Component | Frozen reference |
| --- | --- |
| Host/model | Discovery App coordinating chat with `gpt-6-astra`; backend revision/settings not recorded. Direct CLI compute does not use a model. |
| Agents | Existing coordinator and local command/file capability; no new specialist agents, CLIO, Scientific Reasoning, Bookshelf or Discovery Engine. |
| Skills | Shared runner, explicitly loaded in a fresh project; its activation/run is not yet validated. |
| Runtime | Python **3.13.14**, 64-bit, exact pins in [requirements.txt](requirements.txt). |
| Execution | One scientific stage at a time, one numerical thread, no GPU; 1,800-second timeout per stage, no automatic retry. |
| Input | Exact clean snapshot in [assets.json](assets.json); never substitute the timed archive. |
| Output location | Launcher's `runs/<id>/` beneath the approved bundle root; coordinator evidence separate under `results/<id>/`. |

The original `workflow.py`, `acceptance.py`, `profile.json`, PowerShell wrapper,
offline guard, tests and sanitized reference receipts are in the operational
archive. Do not copy different historical scripts in their place.

## 3. System requirements

Historical path: Windows 11 x64; second-machine App Stable 0.0.2 with a fresh
Python installation. Other scenario platforms are **unvalidated**, not proven
unsupported. App platform availability is separate. Use a short writable local
bundle path below 180 characters, outside App session trees. The launcher
requires 3,000,000,000 free bytes as a safety allowance, not a measured minimum.
It extracts approximately 1.05 GB per new run, plus environments and outputs.
RAM minimum was not established.

## 4. Prerequisites

Both archives and integrity attachments are enumerated in
[the asset manifest](assets.json), with exact size/hash metadata. No approved
anonymous public archive URL has been supplied; external distribution is
blocked, even though an author with the original inputs can inspect them.
Verify source/provenance before loading the saved joblib model; a hash alone
does not make an untrusted model safe.

If the exact Python is missing, use the
[Python 3.13.14 release page](https://www.python.org/downloads/release/python-31314/)
and the installer appropriate to an approved platform profile. A newer 3.13
is not this pin. Do not silently downgrade/uninstall existing Python, change
global PATH or assume a native ARM/emulation route works. An installer conflict
is a blocker to resolve with the user/IT; keep other projects intact.

## 5. Setup

Follow [Getting started](../GETTING-STARTED.md) to create a fresh project with
the bundled runner. Display the readiness table in ordinary chat and present
all 14 dependencies even when Python or another prerequisite is unresolved.

- **NumPy 2.4.3 — Required**\
  Numerical arrays and scoring calculations.
- **SciPy 1.17.1 — Required**\
  Scientific algorithms and statistics.
- **pandas 2.2.3 — Required**\
  Compound tables, predictions and CSV outputs.
- **scikit-learn 1.8.0 — Required**\
  Saved-model inference and clustering.
- **joblib 1.5.3 — Required**\
  Trusted, hash-verified saved-model loading.
- **RDKit 2025.9.6 — Required**\
  Structures, descriptors, fingerprints and native exports.
- **Meeko 0.7.1 — Required**\
  Molecular preparation/file-format support; no new docking authorized.
- **Gemmi 0.7.5 — Required**\
  Crystallographic and structural file handling.
- **Biopython 1.86 — Required**\
  Biological sequence and structure utilities.
- **Requests 2.32.5 — Required**\
  Source-script HTTP support; frozen science does not retrieve new data.
- **Markdown 3.10.2 — Required**\
  Retained report conversion to HTML.
- **Beautiful Soup 4.13.4 — Required**\
  HTML parsing; distribution name `beautifulsoup4`.
- **openpyxl 3.1.5 — Required**\
  Excel file handling.
- **Pillow 12.1.1 — Required**\
  Images used by reporting.

Ask exactly in ordinary chat, not a selectable UI:

> Do you select all 14 required dependencies listed above? Reply Yes or No in
> ordinary chat. This selects dependencies only; it does not authorize
> installation or computation.

Yes selects the full set; No/ambiguous pauses, not partial installation. Next,
verify and obtain approval for the short bundle destination and safe launcher
extraction. Keep the large snapshot **unextracted** beside the launcher. Keep
the older bundled guide at its manifest-listed path but ignore it for
instructions; do not move it and waive the resulting integrity failure.

After runtime/destination/source gates pass, ask **separate installation
approval**, naming all pins, destination and necessary transitive dependencies
(not fully locked). Report the active pip index without credentials. Only then
use the verified owner's `setup --consent-install`, which creates a new
environment and prints its exact interpreter. It installs packages, not Python.
Use that interpreter for `pip check`, pin verification and native preflight.

Only after preflight passes ask **separate computation approval**, naming the
bounded scope and exclusions. Mode choice and file-tool permission are not
compute consent. See [profile.md](profile.md) for ordering and native paths.

## 6. Fixed prompt and matching output

[The frozen launch prompt](prompts/frozen.txt) is retained from the proposed
v0.11 guide with line endings normalized to LF and its hash recorded. It applies
**after** approved launcher preparation; the starting folder need not already
contain extracted source. It is not consent by itself.

The native acceptance script compares four decision/ranking JSON results and
three CSV results (all fields/order), plus SMILES, 100 valid SDF structures,
identities and coordinates, and the same 1,100 parents across six targets.
Numeric relative/absolute tolerance is $10^{-10}$; coordinate absolute
tolerance is $10^{-4}\,\mathrm{\mathring{A}}$. It requires the exact added
caution “No all-CDK selectivity claim.” in the ranking summary.

The expected native receipt is `completed`, all five stages passed and
`semantic_acceptance.json` passed (seven listed comparisons plus structural/
pair assertions). Reconcile recomputed values against the retained baseline,
not against preexisting output filenames. Link the new report, dashboard,
CSV/SDF/SMILES exports, receipts, logs and artifact hashes.

Zero experimentally established broad threefold-selective leads and the
failed CDK7 native-pose gate remain explicit. Solubility is not full ADME;
docking is not experimental potency/selectivity validation.

## 7. Runtime

One historical second-machine run measured setup at about 46 minutes and run
wall time at 45 minutes 16 seconds. About 37 minutes preceded the first stage
while extracting, hashing 33,442 payloads and checkpointing; five stages then
took about 2.5 minutes. This is one observed run, not a guaranteed wait or a
cross-platform benchmark. That run does not validate this new packaging.

## 8. Troubleshooting and cleanup

Record package/index host and actual HTTP/TLS error without credentials;
do not change pins, disable TLS or bypass organization policy. A quiet initial
verification phase is not a scientific-stage timeout. Read progress evidence
no more frequently than the profile permits; honor cancellation and safety
issues. Do not start CLIO or unrelated science to diagnose the delay.

Standalone preflight produces `preflight-<id>.json` at the bundle root.
The native run later owns `runs/<id>/preflight.json`. Resume requires exact
checkpoint/launcher hashes and explicit approval. Preserve failed attempts;
do not remove a lock without checking its exact process. A Python socket guard
is not an OS sandbox. Cleanup requires explicit approval for run-owned paths.

## 9. Publication checklist

- [ ] Archive public location, code/data rights and release notices confirmed.
- [ ] Owner accepts this focused guide/profile adaptation.
- [ ] Clean-project runner activation, exact-runtime setup and full run tested.
- [ ] Recomputed/native output checks and scientific limitations reviewed.
- [ ] Maintainer approves packaging and release status.

See [file accounting](FILES.md) and [scenario.json](scenario.json). Historical
7/7 acceptance is reference evidence only; all new execution remains Not run.