# QuickStart Scenarios

Explore guided workflows for Microsoft Discovery. Find available QuickStart
guides, supporting files, and instructions for a fresh project below.

## Choose a scenario

| Vertical / collection | QuickStart | Availability |
| --- | --- | --- |
| [BioPharma](biopharma/README.md) | [CDK frozen-reference replay](biopharma/cdk-frozen-reference/README.md) | Guide and all required files available; scientific snapshot downloads from the `cdk-frozen-reference-v0.11` release. |
| [Silicon and Physics](siphy/README.md) | [Specification to verified RTL](siphy/spec-to-rtl/README.md) | Guide and setup archive available; see scenario requirements and reference-evidence limitations. |
| [Chemistry and Materials Science](cms/README.md) | [Moisturizer formulation](cms/moisturizer-formulation/README.md) | In preparation; prompt and corpus metadata available. |
| [Bookshelf](bookshelf/README.md) | [SCLC literature research](bookshelf/sclc-literature/README.md) | In preparation; paper metadata and source links available. |

Each QuickStart has its own folder under its vertical or collection. Open a
vertical to browse its scenarios, or select a QuickStart directly above.

## Start a run

1. Open the scenario README and check its availability and requirements.
2. Download the full guide and all required inputs. Keep their original filenames.
3. Create a fresh Discovery project in a short local folder.
4. [Load the shared runner](../skills/quickstart-runner/README.md#use-in-a-fresh-project),
   attach the guide, and send the scenario's starting instruction.
5. Follow the setup and execution approvals, then check the resulting artifacts.

The runner guides the assistant through the selected scenario; it is not a
standalone application. Setup, installation, and computation require separate
approval. Do not start a scenario while required inputs are unavailable.

## Add another scenario

Use the [QuickStart template](templates/README.md) to document your scenario,
required inputs, setup, fixed prompt, and validated results. Include supporting
files with their provenance and distribution terms. Add each scenario in its
own folder under the appropriate vertical and link it from that vertical's README.