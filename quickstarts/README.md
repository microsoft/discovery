# QuickStart Scenarios

**Choose a scenario, download its full QuickStart guide and supporting files,
then follow its README in a new Discovery project.** The QuickStart Markdown
is the instruction the assistant follows; the files are its inputs. Do not
start from another person's project, sessions or installed environment.

**Start here:** choose a scenario below. For its guided run, get the
**[shared runner skill](../skills/quickstart-runner/SKILL.md)** as well as the
full scenario guide and input files. [How to load the skill](../skills/quickstart-runner/README.md#use-in-a-fresh-project).
The runner is instructions for the assistant, not another application to run.

| Scenario | Start here | Full QuickStart guide | Supporting files |
| --- | --- | --- | --- |
| BioPharma | [Instructions](biopharma/README.md) | [Full v0.11 guide](biopharma/QuickStart-BioPharma%20LeadGen%20v0.11.md) | [BioPharma files](biopharma/README.md#supporting-files) |
| SiPhy | [Instructions](siphy/README.md) | [Full Spec-to-RTL guide](siphy/QuickStart-Spec-to-RTL.md) | [SiPhy files](siphy/README.md#supporting-files) and [original scenario skill](siphy/skill%201.md) |
| CMS | [Status and inputs](cms/README.md) | Completed owner guide awaited | [CMS files](cms/README.md#supporting-files) |
| Bookshelf | [Status and papers](bookshelf/README.md) | Completed owner guide awaited | [Bookshelf files](bookshelf/README.md#supporting-files) |

Each scenario has one README for its instructions and supporting-file details.
Its `files/` folder holds the files themselves, without a second README to open.

## Which skill do I use?

Use **one shared runner plus one full scenario guide**. The runner supplies the
common readiness, approval and progress flow; the guide supplies the actual
scenario steps and scientific checks. The runner does not replace the guide
or make an incomplete scenario runnable.

The single source lives at `skills/quickstart-runner/`, following the
[repository skill layout](https://github.com/microsoft/discovery/blob/88a2a1cd1664b7d609659dc86c65f7f632686715/docs/authoring-guides/skill-authoring-guide.md).
That is a repository organization choice, not a customer starting point or
proof that Discovery loaded it. Start from **this page or the selected scenario
README**; both link directly to the shared runner. No search through repository
folders is required, and no second runner copy is needed inside every scenario.

The [original SiPhy skill](siphy/skill%201.md) is retained unchanged for reference
or explicit testing of that variant. Do **not** run both skills in sequence.
The SiPhy README explains its differences from the newer guide. The runner's
scripts/tests/reference inventory are maintainer utilities, not extra customer
setup steps. Fresh-project skill activation and E2E behavior remain to be tested.

## Start a run

1. Open the selected scenario's **README**, not a JSON manifest.
2. Obtain its **full guide and every required file** from the listed locations.
3. Put them in a new short local folder and open/create a Discovery project
   there. Do not install scientific packages before the guide checks readiness.
4. Load the shared runner and attach the full QuickStart guide. Send the
   starting instruction in that scenario's README.
5. Follow its separate setup and execution approvals. Verify its actual outputs.

## Download status

The guides, skills, small supporting files and the complete
[SiPhy tar archive](siphy/files/ship.tar) are repository content. The BioPharma
168,396,900-byte snapshot exceeds the normal Git file limit and still needs an
approved **versioned release download in this same repository**. No such release
has been published yet: a source-code ZIP does not contain every scenario's
runtime inputs. Each scenario README distinguishes included files from pending downloads.

The BioPharma and SiPhy guides are retained in full, with personal attribution
removed from the public copies. Scientific instructions, prompts, results and
checklists are unchanged. The original scenario skill, archives and integrity
attachments remain byte-for-byte unchanged. Historical result links and open
publication items are not claims of newly available or validated evidence.

## Plan for completing publication

1. **Now — agree the skeleton.** Review these scenario folders, full supplied
   guides, start READMEs, original small attachments, shared runner and the
   [unchanged template](templates/QuickStart-Template.md). CMS and Bookshelf
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