# Tellurium Agent for Microsoft Discovery

> Simulate and analyze SBML/Antimony kinetic models of biochemical networks with the libRoadRunner ODE engine.

**Domain:** Systems Biology  
**Upstream project:** [http://tellurium.analogmachine.org](http://tellurium.analogmachine.org)  
**License:** Apache-2.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Deterministic time-course simulation of SBML models
- Steady-state and parameter analysis

## Tool Actions

| Action | Description |
|---|---|
| `simulate_model` | Run a deterministic time-course simulation of each SBML model. |

## Container Dependencies

- **pip:** tellurium

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
