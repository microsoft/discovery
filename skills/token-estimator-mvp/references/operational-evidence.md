# Operational allowance: reference basis and limits

Use the [shared CLI](../scripts/estimate.js) or [API](../scripts/model.js) for
every estimate; this page is explanatory only.

The `existing-workflow-launch` phase uses a provisional coarse envelope of
0.3-3 million input-plus-output tokens from bundled operational-preparation
references. The envelope is a planning allowance only.

What it includes:

- Reading existing instructions/configuration/inputs
- Local command and environment preparation
- Launch or blocked-attempt handoff
- Startup/status/error confirmation and short handoff

What it does not include:

- External solver CPU/GPU runtime or utilization
- Scientific-model development or raw scientific data preparation
- Continuous monitoring or open-ended troubleshooting

Transfer limits:

- References are related alternatives, not additive work items.
- This is not a guaranteed minimum, measured launch bound, or confidence interval.
- Bounded retry and monitoring checks set scope; they are not token multipliers.
