# Generic examples

All six supported classes provide either a coarse range or a conditional
planning base without requiring token guesses.

From this skill directory:

```sh
node scripts/estimate.js --input examples/description.json
node scripts/estimate.js --input examples/coarse-prediction.json
node scripts/estimate.js --input examples/operation.json
```

See all JSON files in this folder for additional scenarios.

## Notes

- Generic prediction can use the alternative-phase envelope with no required phase.
- Unknown readiness/depth/checking can preserve a conditional base while keeping
  full totals null.
- External-resource-only requests stay unknown.
- These fixtures are deterministic examples, not measurements of real-world
  project outcomes.
