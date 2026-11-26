---
name: token-estimator-mvp
description: "Estimate AI planning ranges from a work description or explicitly authorized safe project context. Provides coarse class ranges or conditional planning bases without requiring token guesses."
license: MIT
---
# Token estimator MVP

Use this skill for first-pass AI planning guidance. It is not a scientific
execution service.

Use only the bundled [CLI](scripts/estimate.js) or [API](scripts/model.js)
with [calibration](resources/calibration.json) and
[profiles](resources/work-profiles.json). Never invent formulas or ask users
for token budgets.

## Procedure

1. Identify the deliverable from the request. Context is optional.
2. Map to the [input guide](references/input-guide.md) and
   [contract](resources/contract.schema.json), version 1.2.0.
3. Leave unknown facts unknown. Provide conditional bases when supported.
4. For "run an existing workflow," use `existing-workflow-operation`.
5. Count shared setup/checks once. Separate independent review as its own task.
6. Run the estimator with sanitized JSON:

   ```sh
   node scripts/estimate.js --input examples/coarse-prediction.json
   ```

7. Report status, mapping, assumptions, uncertainty and exclusions.

## Package notes

Copy this entire directory to `skills/token-estimator-mvp/` in the target
repository. Keep files relative and project-local. No installs, credentials,
network access, or external authoring workspace are required.

See [examples](examples/README.md) for supported scenarios.

Run tests:

```sh
node --test tests/model.test.js tests/phases.test.js tests/operations.test.js tests/behavior.test.js tests/packaging.test.js tests/skill-guidance.test.js
```

This package ships provisional community reference ranges. They are planning
heuristics requiring broader community validation and are not statistical bounds
or evidence of customer outcomes.
