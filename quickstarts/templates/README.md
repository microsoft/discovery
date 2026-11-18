# QuickStart Scenarios templates

Start with **[QuickStart-Template.md](QuickStart-Template.md)**.
Download a copy and complete it for your tested scenario.

## For scenario owners

1. Use [the blank template](QuickStart-Template.md) to document the
   scenario you actually ran.
2. Record the model, setup, inputs, prompt, results, and validation evidence.
   Label unverified requirements and distinguish measured results from estimates.
3. Create `quickstarts/<vertical>/<scenario>/` with a descriptive scenario name.
   Put the full completed Markdown beside its README, required inputs in its
   `files/` folder, and link the scenario from the vertical's README.
4. Include any required scenario-specific skill and its version. The
   [shared runner](../../skills/quickstart-runner/README.md) follows the full
   guide; conflicts with older skill versions must be reconciled explicitly.
5. Provide actual reference outputs and identify public distribution rights.
   Large approved files can be repository-release assets with exact checksums.
6. **Make it runnable with three copy-paste prompts (standard for every
   QuickStart).** A user with only the Discovery app must be able to: create a
   project, click **New session**, select the model, and send the README's
   three prompts in order. The Step 1 **A** prompt contains the guide link, so
   the user never pastes the link on its own. So the scenario README starts with
   those exact steps and names the model. The guide starts with the template's **How this
   QuickStart runs** note (default scenario, approvals, what to compare) and
   lists a **direct download link, size and SHA-256 for every required file**.
   Right after the Checklist, explain in plain English what the scenario does
   and what the user will see at the end, and name the project folder after the
   scenario (for example `QuickStart-CDK-Lead-Discovery`). Every scenario
   README follows the same layout: a very short numbered **Checklist** at the
   top; what the scenario does; **What you need** (including the model);
   estimated time for each stage; what's in the files; and **three steps with
   copy-paste prompts**: (1) set up and confirm the environment, (2) run the
   experiment, (3) verify the results against the validated reference. Give
   each step a prompt for both routes: **A**, the assistant downloads the files
   from the guide link (recommended), and **B**, the user downloaded the files
   and attaches the guide. The guide repeats the same three prompts, word for
   word, in its **Copy-paste prompts (same as the README)** section, and says
   which guide section each step covers, so a reader of either document can run
   it. Start the README from [the README template](README-Template.md), and see
   the [BioPharma README](../biopharma/cdk-frozen-reference/README.md) for a
   completed example.

**Using a model to draft a QuickStart:** open a Discovery chat in your
workspace, attach [QuickStart-Template.md](QuickStart-Template.md) and
[README-Template.md](README-Template.md) together with your scenario's run
evidence, and ask it to complete both templates. Each template starts with
authoring instructions the model follows: fill every placeholder from the
evidence, write Pending instead of guessing, keep the step prompts identical in
both files, and finish with the publication checklist. Review the draft and
run it once before publishing.

Completed examples already available:
[BioPharma v0.11](../biopharma/cdk-frozen-reference/QuickStart-BioPharma%20LeadGen%20v0.11.md) and
[Silicon and Physics: Spec-to-RTL](../siphy/spec-to-rtl/QuickStart-Spec-to-RTL.md). Check each scenario's
README for current availability and validation scope.