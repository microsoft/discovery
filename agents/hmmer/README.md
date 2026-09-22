# HMMER Agent for Microsoft Discovery

> Profile hidden Markov model search for sensitive detection of remote homologs and protein domains (Pfam-style).

**Domain:** Sequence Search  
**Upstream project:** [http://hmmer.org](http://hmmer.org)  
**License:** BSD-3-Clause  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Build profile HMMs from alignments (hmmbuild)
- Search sequences with profiles (hmmsearch)

## Tool Actions

| Action | Description |
|---|---|
| `hmmbuild` | Build a profile HMM from a multiple sequence alignment. |
| `hmmsearch` | Search a sequence database with a profile HMM. |

## Container Dependencies

- **conda-forge:** hmmer

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
