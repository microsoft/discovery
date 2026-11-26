# Validated Scenarios

Explore guided workflows for Microsoft Discovery. Pick a scenario, then run it
by sending its README's three prompts in a Discovery chat.

## Choose a scenario

| Vertical / collection | Validated Scenario | What it does | Model | Run time | Availability |
| --- | --- | --- | --- | --- | --- |
| [BioPharma](biopharma/README.md) | [CDK Target Selection and Lead Discovery](biopharma/cdk-frozen-reference/README.md) | Reruns the analysis of a CDK lead-discovery campaign from its saved results and checks it against the validated reference. | GPT-6 Astra | About 1.5 hours the first time (45 min setup, 45 min run) | Ready to run from its guide link; all required files available. Fresh end-to-end run not yet recorded. |
| [Bookshelf](bookshelf/README.md) | [SCLC treatment literature research](bookshelf/sclc-literature/README.md) | Builds a Bookshelf from 15 open-access papers and answers a cited research question. | GPT-6 Astra | About 15 to 25 minutes | Available. Tested end to end on Windows 11 x64. |
| [Chemistry and Materials Science](cms/README.md) | [Moisturizer formulation](cms/moisturizer-formulation/README.md) | Moisturizer formulation research. | Pending | Pending | In preparation; prompt and corpus metadata available. |

Run times come from each scenario's measured run and vary with your machine and network.
Found a problem? [Report it](https://github.com/microsoft/discovery/issues/new?template=validated-scenario-feedback.yml) with the scenario, the step and what you saw.

Each Validated Scenario has its own folder under its vertical or collection. Open a
vertical to browse its scenarios, or select a Validated Scenario directly above.

## Start a run

Every Validated Scenario runs the same way: **select the model and send the README's
three prompts in a Discovery chat.** The first prompt already contains the
guide link. You only need the Discovery app. The assistant reads the guide,
downloads what it needs, and walks you through setup, the run and checking
your results.

**Don't have the app yet?** Download it from the
[Discovery download page](../README.md) and follow the
[install guide](../docs/discovery-app/install.md). You need a GitHub account
with a GitHub Copilot subscription to sign in.

1. Open **Microsoft Discovery**. On **Projects**, click **New project**, create
   a new empty folder, and click **Open local project**. (Discovery needs a
   project before you can chat.)
2. Click **New session**.
3. Select the model named in the scenario README.
4. Send the README's three prompts in order: **set up and confirm the
   environment**, **run the experiment**, and **verify the results against
   the validated reference**. Each step has a prompt for when the assistant
   downloads the files from the guide link (recommended) and one for when you
   download them yourself.
5. Answer the assistant's questions. It asks before downloading files,
   installing anything and starting the run.

Each scenario README gives the exact clicks, the model and the guide link.
Available now: **BioPharma** and **Bookshelf**.
Chemistry and Materials Science is being moved to this format; until then,
follow the steps in its own README.

**Do I need Docker?** Usually not. Each README's **What you need** table has a
**Container runtime** row. BioPharma and Bookshelf need none. Validated Scenarios that
run container tools need one container engine: we recommend free
[Podman](https://podman.io/docs/installation), and Docker works if you already
have it. Docker Desktop is never required; it needs a paid per-user
subscription in larger organizations
([Docker Desktop license](https://docs.docker.com/subscription/desktop-license/)).

## Add another scenario

Use the [Validated Scenario template](templates/README.md) to document your scenario,
required inputs, setup, fixed prompt, and validated results. Include supporting
files with their provenance and distribution terms. Add each scenario in its
own folder under the appropriate vertical and link it from that vertical's README.