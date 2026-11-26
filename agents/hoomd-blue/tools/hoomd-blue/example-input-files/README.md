# HOOMD-blue Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Initial particle configuration
- Interaction parameters and units
- Integrator and simulation settings

## Expected output contract

- GSD trajectories
- Thermodynamic logs
- Final configurations

## Validation

Select hoomd.device.GPU explicitly; validate timestep, equilibration, units, and GPU support for the selected integrator.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
