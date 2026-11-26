# token-estimator-mvp

Portable MVP for coarse AI token planning ranges from task descriptions.

## Install location

Copy this directory to:

`skills/token-estimator-mvp`

## Usage (Node 18+)

CLI:

```sh
node scripts/estimate.js --input examples/description.json
```

API:

```js
const { createEstimator, VERSION } = require('./scripts/model.js');
```

## Limitations

- Planning helper only; no scientific execution.
- Uses provisional coarse ranges and assumptions.
- Unknown scope remains null instead of fabricated totals.

## Public calibration status

Bundled references are sanitized, compact, and public-safe. They provide
provisional community planning ranges requiring broader validation; they are
not statistical bounds or customer evidence.
