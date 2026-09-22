# COPASI (basico) Agent for Microsoft Discovery

> Simulation and analysis of biochemical reaction networks via COPASI through the basico Python interface: time-courses, steady states, and parameter scans.

**Domain:** Systems Biology  
**Upstream project:** [https://basico.readthedocs.io](https://basico.readthedocs.io)  
**License:** Artistic-2.0  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Deterministic and stochastic time-course simulation
- Steady-state analysis of SBML models

## Tool Actions

| Action | Description |
|---|---|
| `run_timecourse` | Load SBML models and run a deterministic time-course simulation with basico. |

## Container Dependencies

- **pip:** copasi-basico

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
