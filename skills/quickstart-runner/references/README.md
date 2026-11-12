# Preparing exact-file downloads (maintainers)

Customers start with the scenario README and full owner guide. They do not
need this inventory or the packaging script to understand or run the scenario.

`downloads.json` records required filenames, byte lengths, SHA-256 hashes,
and publication status. It includes required inputs that are not yet publicly
available, so a clean checkout may report missing files. This inventory is
for packaging, not scientific execution. Source and published guide hashes are
recorded separately where they differ; archive bytes remain unchanged.

## Local verification and review download

Use an existing Python 3.10+ for these author-only operations; no package install,
network, extraction, agent invocation, model loading or scientific work occurs.

```console
python skills/quickstart-runner/scripts/package_download.py check --scenario biopharma
python skills/quickstart-runner/scripts/package_download.py prepare --scenario biopharma --destination ../BioPharma-exact-review --local-review --apply
```

`prepare` is a no-write plan without `--apply`. It requires a new destination
and refuses unexpected files, modified bytes and symlinks. `--local-review`
means only local author review, not publication or science approval. It copies
exact inputs/guide into one new folder, adds the shared skill and short start
instructions, and creates a sibling ZIP containing the same bytes. ZIPs/tars
inside that outer download remain byte-identical to the originals.

The helper requires all listed source files and a completed guide before it
can prepare a bundle. Byte checks establish consistency, not permissions,
active skills, or runtime success.

## Public repository release

The BioPharma 168,396,900-byte snapshot exceeds GitHub's normal Git-object limit.
Use versioned repository releases for approved large files. The script creates
local bundles only; it does not upload them.

Before upload, verify rights, absence of private content, account/destination,
author approval and exact filenames/checksums. Preserve original source and
licence notices. The SiPhy archive is included in Git; BioPharma's large snapshot
and the protected CMS archive are not public downloads. Local file availability
and checksum verification do not establish redistribution rights.

After an approved release is actually uploaded, put the **real download links**
in the scenario README's supporting-files section and the inventory, and verify
anonymous download bytes. Repository source-code ZIPs omit ignored files.

List unavailable reference outputs in the scenario README. Keep source guides
and scientific criteria intact; use the [blank template](../../../quickstarts/templates/QuickStart-Template.md)
when authoring a new scenario.