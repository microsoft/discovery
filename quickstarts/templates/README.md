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
6. **Make it runnable from one link (standard for every QuickStart).** A user
   with only the Discovery app must be able to: create a project, click
   **New session**, select the model, and send `Run this QuickStart:` plus the
   guide link — nothing else. So the scenario README starts with those exact
   steps and names the model. The guide starts with the template's **How this
   QuickStart runs** note (default scenario, approvals, what to compare) and
   lists a **direct download link, size and SHA-256 for every required file**.
   Start the README with a plain-English explanation of what the scenario does
   and what the user will see at the end, and name the project folder after the
   scenario (for example `QuickStart-CDK-Lead-Discovery`). Every scenario
   README follows the same layout: a very short numbered **Checklist** at the
   top; what the scenario does; **What you need** (including the model);
   estimated time for each stage; what's in the files; and **three steps with
   copy-paste prompts**: (1) set up and confirm the environment, (2) run the
   experiment, (3) verify the results against the validated reference. Give
   each step a prompt for both routes: **A**, the assistant downloads the files
   from the guide link (recommended), and **B**, the user downloaded the files
   and attaches the guide. See the
   [BioPharma README](../biopharma/cdk-frozen-reference/README.md) for the pattern.

Completed examples already available:
[BioPharma v0.11](../biopharma/cdk-frozen-reference/QuickStart-BioPharma%20LeadGen%20v0.11.md) and
[Silicon and Physics: Spec-to-RTL](../siphy/spec-to-rtl/QuickStart-Spec-to-RTL.md). Check each scenario's
README for current availability and validation scope.