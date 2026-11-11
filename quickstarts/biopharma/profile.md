# BioPharma runner profile

Profile `cdk-frozen-reference-v1`; guide [README.md](README.md) governs. This
packaging profile is draft, not a product-native catalog record. Exact scientific
runtime settings remain in the hash-pinned owner's operational archive.

## Required capabilities and bounds

- Existing coordinating chat with `gpt-6-astra`; local file and command tools.
- Python 3.13.14, 64-bit, all 14 pins; Windows x64 historical evidence only.
- No specialist-agent installation, Bookshelf, CLIO, Scientific Reasoning,
  fresh data, new docking/training, GPU or cloud deployment.
- One scientific stage/thread, 1,800 s per stage, **zero automatic retries**.
- New short bundle root; keep native `runs/<id>/` intact and separate from
  coordinator `results/<id>/`. A fresh project can initially contain ZIPs only.

## Fixed preparation sequence (parent local commands, not agent delegation)

1. Inspect model/runtime/platform and hash/size of both archives and supporting
   attachments against [assets.json](assets.json). Collect independent blockers.
   Display all pins and obtain the exact ordinary-chat full-set selection from
   the guide even when installation is not needed. Selection is not consent.
2. Obtain asset-staging approval for a new short destination, check archive
   members and the full supplied manifest, then extract **only** the operational
   bundle without overwriting. Leave the snapshot zipped beside `workflow.py`.
   Preserve the old guide at its manifest path; the current scenario guide
   stays separate. Reject mismatches/unsafe extraction, do not waive them.
3. If runtime is mismatched, give the exact publisher option and pause; never
   remove or overwrite another Python automatically. Verify executable, version,
   bitness and architecture. Report pip index with credentials stripped.
4. With all other install gates resolved, obtain separate installation approval
   for the full pinned set plus transitive dependencies and the new environment.
   Run `<selected-python> workflow.py setup --consent-install`. Record the
   returned `isolated_python`. Check all pins and `-m pip check` with it.
   If an authorized run-owned environment already satisfies every pin, report
   No installation needed rather than invoking setup anyway.
5. Run `<isolated-python> workflow.py preflight` only from the verified bundle.
   Read the **printed** receipt path (standalone form `preflight-<id>.json`),
   require status `ready` and exit 0. It does not check the App model or grants.
6. Ask mode choice (unless already selected), explain historical silent startup
   and bounded scope, then ask `Approve the bounded frozen computation` / `Pause`.
   Ordinary-chat approval fallback uses the guide's explicit bounded wording.

## Scientific sequence (one native launch)

Only after step 6 approval, run `<isolated-python> workflow.py run --approve-compute`
in the verified root. Do not issue five independent commands: the launcher owns
decision, solubility, ranking, acceptance and presentation with native checkpoints.
Read receipt/log evidence at most every 5–10 minutes while active; prefer host
completion notifications. The initial approximately 37-minute historical quiet
phase is not a timer guaranteeing success or authorizing restart.

Require native `receipt.json` completed; five stages passed;
`semantic_acceptance.json` passed; valid fresh candidate structures/exports and
dashboard; reconcile retained/recomputed work. Original reference receipts
in the archive are never used as this run's result. The exact owner prompt is
[prompts/frozen.txt](prompts/frozen.txt); its wording about the open bundle root
starts after preparation, not before files are unpacked.

## Stop and recovery

Honor user Stop, integrity errors, policy issues and native timeouts. Preserve
failed work and report the failed gate. No automatic retry or stale-lock
deletion. Native resume is separately approved and allowed only if its full
checkpoint/source validation succeeds. Do not repackage new science data or
weaken the owner's acceptance to turn a failed run into a pass.