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

Completed examples already available:
[BioPharma v0.11](../biopharma/cdk-frozen-reference/QuickStart-BioPharma%20LeadGen%20v0.11.md) and
[Silicon and Physics: Spec-to-RTL](../siphy/spec-to-rtl/QuickStart-Spec-to-RTL.md). Check each scenario's
README for current availability and validation scope.