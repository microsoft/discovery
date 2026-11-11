# QuickStart Scenarios

**Choose a scenario, download its full QuickStart guide and supporting files,
then follow its README in a new Discovery project.** The QuickStart Markdown
is the instruction the assistant follows; the files are its inputs. Do not
start from another person's project, sessions or installed environment.

| Scenario | Start here | Full QuickStart guide | Supporting files |
| --- | --- | --- | --- |
| BioPharma | [Instructions](biopharma/README.md) | [Full v0.11 guide](biopharma/Quick-Start-BioPharma%20LeadGen%20v0.11.md) | [BioPharma files](biopharma/files/README.md) |
| SiPhy | [Instructions](siphy/README.md) | [Full Spec-to-RTL guide](siphy/QuickStart-Spec-to-RTL.md) | [SiPhy files](siphy/files/README.md) and [original scenario skill](siphy/skill%201.md) |
| CMS | [Status and inputs](cms/README.md) | Completed owner guide awaited | [CMS files](cms/files/README.md) |
| Bookshelf | [Status and papers](bookshelf/README.md) | Completed owner guide awaited | [Bookshelf files](bookshelf/files/README.md) |

## Which skill do I use?

Use the [shared QuickStart runner](../skills/quickstart-runner/SKILL.md), with
[installation instructions](../skills/quickstart-runner/README.md). It reads
the full selected guide; it does not replace that guide with another profile
or silently change the scenario. The original SiPhy skill is also retained
unchanged, as supplied. The SiPhy README explains its older-guide differences.

## Start a run

1. Open the selected scenario's **README**, not a JSON manifest.
2. Obtain its **full guide and every required file** from the listed locations.
3. Put them in a new short local folder and open/create a Discovery project
   there. Do not install scientific packages before the guide checks readiness.
4. Load the shared runner and attach the full QuickStart guide. Send the
   starting instruction in that scenario's README.
5. Follow its separate setup and execution approvals. Verify its actual outputs.

## Download status

The guide/skill/small text files are repository content. The BioPharma
168,396,900-byte snapshot cannot be a normal Git blob. Large scenario downloads
will be **assets of a versioned release in this same repository**, linked from
each files page. No release has been published yet: a GitHub source-code ZIP
alone does not currently contain every runtime input. The files pages say
exactly what is present locally and what still needs a public download.

The BioPharma and SiPhy guides are retained in full, with personal attribution
removed from the public copies. Scientific instructions, prompts, results and
checklists are unchanged. The original scenario skill, archives and integrity
attachments remain byte-for-byte unchanged. Historical result links and open
publication items are not claims of newly available or validated evidence.

## Plan for completing publication

1. **Now — agree the skeleton.** Review these scenario folders, full supplied
   guides, start READMEs, original small attachments, shared runner and the
   [unchanged template](templates/Quick-Start-Template.md). CMS and Bookshelf
   keep clearly labelled spaces for their completed owner guides.
2. **Next — complete each handoff.** Add the missing owner guides and reference
   outputs, confirm which files may be shared publicly, and test the selected
   guide from a fresh project. Do not infer permission or success from a file
   being present in an internal source folder.
3. **Then — publish the downloads.** Upload the approved exact large archives
   as versioned releases in this repository, replace the pending download
   notices with real links, and verify download checksums. No archive upload
   is part of the skeleton push; the scenario is ready only after its stated
   setup and output checks actually pass.

## Add another scenario

See [Templates](templates/README.md). Deliver the completed original template,
its required input files, and any scenario skill. No customer should need to
understand a second profile, file-inventory document or duplicate requirements
file to start. Repository review and actual clean-start validation remain
separate from the raw E2E handoff to Engineering.

## Repository support files

- `.gitattributes` preserves checked-in guide and attachment bytes across
   Windows/macOS/Linux checkouts; the navigation READMEs use standard line endings.
- `.gitignore` prevents large or private local files and generated caches from
   being committed accidentally. It does not delete those local files.
- This README is the scenario index and start page. Customers do not need to
   edit either Git settings file to use a QuickStart.