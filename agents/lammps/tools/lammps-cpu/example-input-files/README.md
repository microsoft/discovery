# LAMMPS Example Input Files

This directory contains LAMMPS input scripts and data files for non-equilibrium molecular dynamics (NEMD) simulations using the heat exchange (HEX) and enhanced heat exchange (eHEX) algorithms.

## System Types

### Lennard-Jones (LJ) Fluid
The Lennard-Jones fluid is a simple model system where particles interact via the Lennard-Jones potential—a mathematical function that approximates the interaction between neutral atoms or molecules. It includes a short-range repulsion (atoms can't overlap) and a longer-range attraction (van der Waals forces). Despite its simplicity, the LJ model captures essential features of real fluids and is widely used as a benchmark system in molecular dynamics simulations because it's computationally efficient and well-understood.

### SPC/E Water
SPC/E (Extended Simple Point Charge) is a rigid 3-site model for water molecules. Each water molecule consists of three charged sites (one oxygen and two hydrogens) with fixed bond lengths and angles. This model includes electrostatic interactions between partial charges, making it more complex than LJ but more realistic for studying water properties. SPC/E accurately reproduces many properties of liquid water including density, diffusion, and thermal conductivity.

## Files Overview

### Input Scripts

These are LAMMPS input scripts that define the simulation parameters, force fields, thermostats, and output settings.

#### **in.lj.hex**
- **System:** Lennard-Jones (LJ) fluid
- **Method:** Heat Exchange (HEX) algorithm
- **Purpose:** NEMD simulation to compute thermal conductivity using the original HEX thermostat
- **Requires:** `data.lj`
- **Outputs:** Temperature profile and energy evolution data

#### **in.lj.ehex**
- **System:** Lennard-Jones (LJ) fluid
- **Method:** Enhanced Heat Exchange (eHEX/a) algorithm
- **Purpose:** NEMD simulation using the improved eHEX algorithm with better energy conservation
- **Requires:** `data.lj`
- **Outputs:** Temperature profile (`out.Tlj_ehex`) and energy evolution (`out.Elj_ehex`)
- **Reference:** Wirnsberger et al., J. Chem. Phys. 143, 124104 (2015)

#### **in.spce.hex**
- **System:** SPC/E water model
- **Method:** Heat Exchange (HEX) algorithm
- **Purpose:** NEMD simulation for water with HEX thermostat, includes long-range electrostatics
- **Requires:** `data.spce`
- **Outputs:** Temperature profile and energy evolution data

#### **in.spce.ehex**
- **System:** SPC/E water model
- **Method:** Enhanced Heat Exchange (eHEX/a) algorithm
- **Purpose:** NEMD simulation for water with eHEX thermostat
- **Requires:** `data.spce`
- **Outputs:** Temperature profile and energy evolution data
- **Note:** Uses PPPM for long-range electrostatics

#### **in.lj.gk**
- **System:** Lennard-Jones (LJ) fluid
- **Method:** Green-Kubo equilibrium method
- **Purpose:** Compute thermal conductivity from heat flux autocorrelation function (HFACF)
- **Requires:** `data.lj`
- **Outputs:** Heat flux autocorrelation data (`out.Jlj_gk`)
- **Note:** Equilibrium method - no imposed temperature gradient. Useful for cross-validation with NEMD results.

### Data Files

These files contain the initial atomic configurations (coordinates, velocities, box dimensions) for the simulations.

#### **data.lj**
- **System:** Lennard-Jones fluid
- **Atoms:** 2,000 atoms
- **Type:** Single atom type
- **Description:** Pre-equilibrated configuration for LJ NEMD simulations
- **Box:** Elongated in z-direction for thermal gradient
- **Used by:** `in.lj.hex`, `in.lj.ehex`

#### **data.spce**
- **System:** SPC/E water
- **Molecules:** Water molecules with rigid geometry
- **Description:** Pre-equilibrated water configuration for NEMD simulations
- **Box:** Elongated in z-direction for thermal gradient
- **Used by:** `in.spce.hex`, `in.spce.ehex`
- **Note:** Includes partial charges for electrostatic interactions

## Quick-Test Files

The `quick-test/` subdirectory contains modified versions of all input files with **reduced simulation times** for faster testing and development iterations.

### Differences from Full Simulations

| Parameter | Full Simulation | Quick-Test | Speedup |
|-----------|-----------------|------------|---------|
| **LJ tprod** | 5000 | 500 | 10x |
| **LJ total steps** | ~714,000 | ~71,400 | 10x |
| **SPC/E tprod** | 1,000,000 (1 ns) | 10,000 (10 ps) | 100x |
| **SPC/E total steps** | ~333,333 | ~3,333 | 100x |
| **LJ thermo frequency** | 10,000 | 1,000 | More output |
| **SPC/E thermo frequency** | 1,000 | 100 | More output |
| **Log file extension** | varies | `.log` | Consistent |

### Quick-Test Files

```
quick-test/
├── in.lj.hex      # LJ + HEX (10x faster)
├── in.lj.ehex     # LJ + eHEX (10x faster)
├── in.lj.gk       # LJ + Green-Kubo (10x faster)
├── in.spce.hex    # SPC/E + HEX (100x faster)
├── in.spce.ehex   # SPC/E + eHEX (100x faster)
├── data.lj        # LJ data file (copy)
└── data.spce      # SPC/E data file (copy)
```

### When to Use Quick-Test Files

- **Development:** Testing script logic and workflow integration
- **Debugging:** Verifying LAMMPS commands and output formats
- **CI/CD:** Automated testing pipelines
- **Learning:** Understanding simulation behavior without long waits

### When to Use Full Simulations

- **Production runs:** Generating publication-quality data
- **Convergence studies:** Ensuring statistically meaningful results
- **Algorithm comparison:** Accurate HEX vs eHEX analysis

## Usage

To run a simulation, use:

```bash
# Full simulation
lmp -in in.lj.ehex

# Quick test (from quick-test directory)
lmp -in quick-test/in.lj.ehex
```

For real-time progress visibility, use the `-screen stdout` flag:

```bash
lmp -in in.lj.ehex -screen stdout -log simulation.log
```

Replace `in.lj.ehex` with the desired input script.

## Key Differences: HEX vs eHEX

- **HEX:** Original heat exchange algorithm for NEMD
- **eHEX:** Enhanced version with improved energy conservation and stability
- Both methods impose a thermal gradient by exchanging kinetic energy between hot and cold regions

## Credits

These input files are modified versions of example scripts from the supplementary material (open access) of:

**Wirnsberger, P., Frenkel, D., & Dellago, C. (2015).** "An enhanced version of the heat exchange algorithm with excellent energy conservation properties." *Journal of Chemical Physics*, 143, 124104.

The original examples were created to demonstrate the eHEX/a algorithm and have been adapted for use in this repository.

## References

For detailed information about the eHEX algorithm:
- Wirnsberger, P., Frenkel, D., & Dellago, C. (2015). An enhanced version of the heat exchange algorithm with excellent energy conservation properties. *J. Chem. Phys.*, 143, 124104.
- arXiv: http://arxiv.org/pdf/1507.07081
