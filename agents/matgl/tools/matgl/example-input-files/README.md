# MatGL Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Structures
- Named compatible MatGL model
- Potential or property prediction settings

## Expected output contract

- Predicted properties or energies and forces
- Relaxed structures and trajectories when requested

## Validation

Backend requirements change across MatGL releases; distinguish property-only models from interatomic potentials.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
