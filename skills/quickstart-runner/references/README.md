# Preparing exact-file downloads (maintainers)

Customers start with the scenario README and full owner guide. They do not
need this inventory or the packaging script to understand or run the scenario.

`downloads.json` records the actual expected published-file bytes. It is an
internal download inventory, **not** a second scientific profile. The complete
guides have only personal attribution removed and published filename references
normalized to QuickStart; their original source digests and published-copy
digests are recorded separately. Scientific instructions are not shortened.
Archive contents, checksums and supporting attachments are unchanged. Git
attributes preserve the recorded bytes through checkout.

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

The helper checks all available source files but refuses to make a runnable
download without a completed guide. It never fabricates CMS/Bookshelf recipes.
Byte checks prove consistency, not permissions, active skills or runtime success.

## Public repository release

The BioPharma 168,396,900-byte snapshot exceeds GitHub's normal Git-object limit.
Large archives should be **versioned release assets on the repository**; do not
replace them with inventory-only documentation or fake URLs. The script makes
local bundles only; no upload is performed by it.

Before upload, verify rights, absence of private content, account/destination,
author approval and exact filenames/checksums. The complete SiPhy tar is now
included directly after the contributor confirmed public-sharing permission
for the archive and all bundled papers on 2026-11-11. Original source notices
remain intact; the confirmation is not an independent rights audit. The CMS
archive remains protected and unapproved.
Do not remove Git exclusions to bypass those decisions. No public sharing of
these files is authorized merely because a local copy exists.

After an approved release is actually uploaded, put the **real download links**
in the scenario README's supporting-files section and the recorded release location, and verify
anonymous download bytes. Only then can “download all files from the repo” be
claimed. A source-code ZIP alone currently omits ignored, unpublished files.

The originals may retain missing historical output links; list those as
missing in the scenario README, never silently rewrite the owner Markdown.
The [original blank template](../../../quickstarts/templates/QuickStart-Template.md)
is included unchanged. Do not replace it with the completed SiPhy guide or a
generated template.