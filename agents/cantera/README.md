# Cantera Agent for Microsoft Discovery

> Chemical kinetics, thermodynamics, and transport for combustion and reacting flows. Compute equilibria and simulate reactors on CPU.

**Domain:** Chemical Kinetics  
**Upstream project:** [https://cantera.org](https://cantera.org)  
**License:** BSD-3-Clause  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Chemical equilibrium calculations
- Constant-pressure reactor ignition simulation

## Tool Actions

| Action | Description |
|---|---|
| `equilibrate` | Compute chemical equilibrium at given temperature and pressure for a gas mixture. |

## Container Dependencies

- **pip:** cantera

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
