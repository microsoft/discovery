# QuickStart Scenarios

Explore guided workflows for Microsoft Discovery. Find available QuickStart
guides, supporting files, and instructions for a fresh project below.

## Choose a scenario

| Vertical / collection | QuickStart | Availability |
| --- | --- | --- |
| [BioPharma](biopharma/README.md) | [CDK Target Selection and Lead Discovery](biopharma/cdk-frozen-reference/README.md) | Ready to run from its guide link; all required files available. Fresh end-to-end run not yet recorded. |
| [Silicon and Physics](siphy/README.md) | [Specification to verified RTL](siphy/spec-to-rtl/README.md) | Guide and setup archive available; see scenario requirements and reference-evidence limitations. |
| [Chemistry and Materials Science](cms/README.md) | [Moisturizer formulation](cms/moisturizer-formulation/README.md) | In preparation; prompt and corpus metadata available. |
| [Bookshelf](bookshelf/README.md) | [SCLC literature research](bookshelf/sclc-literature/README.md) | In preparation; paper metadata and source links available. |

Each QuickStart has its own folder under its vertical or collection. Open a
vertical to browse its scenarios, or select a QuickStart directly above.

## Start a run

Every QuickStart runs the same way: **you give Discovery the link to the
scenario's guide.** The assistant reads the guide, downloads the required
files into your project, and walks you through setup, the run and checking
your results. You don't download, attach or unzip anything yourself.

1. Open the scenario README. Its **guide link** is at the top.
2. In Microsoft Discovery, create a **New project** in a new empty folder and
   click **New session**. Select the model the README names.
3. Paste the README's starting message, which includes the guide link, and send it.
4. Answer the assistant's questions. It asks separately before downloading
   files, installing anything and starting the computation.

Each README also has a fallback for when the assistant can't open the link.
Available now: **BioPharma**. Silicon and Physics, Chemistry and Materials
Science, and Bookshelf are being moved to this format; until then, follow the
steps in their own READMEs. Do not start a scenario while required inputs are
unavailable.

## Add another scenario

Use the [QuickStart template](templates/README.md) to document your scenario,
required inputs, setup, fixed prompt, and validated results. Include supporting
files with their provenance and distribution terms. Add each scenario in its
own folder under the appropriate vertical and link it from that vertical's README.