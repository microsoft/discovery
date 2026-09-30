# Validation baseline debt

The ratchet baseline is temporary migration debt. New entries are prohibited;
new exceptions must use an expiring CODEOWNER-approved waiver.

**Owner:** Discovery catalog CODEOWNERS  
**Removal target:** December 31, 2026  
**Tracking rule:** This checklist is complete only when
`.github/policy/baseline.json` has zero entries.

## POL-016: GWP parity image

- [ ] Replace or remove
  `agents/gwp-predictor/training/results/parity_holdout_al.png`.
- [ ] Remove its `POL-016` baseline entry.

## POL-015: GWP generated HTML

- [ ] Move, regenerate in CI, or remove
  `agents/gwp-predictor/training/results/gwp_predictor_overview.html`.
- [ ] Remove its `POL-015` baseline entry.

## POL-015: RTL Yosys test artifact

- [ ] Replace or remove `agents/rtl-yosys-syn/.test`.
- [ ] Remove its `POL-015` baseline entry.
