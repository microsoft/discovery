# Biopython Agent for Microsoft Discovery

> Foundational bioinformatics toolkit for sequence I/O and analysis: parse FASTA/GenBank/PDB, compute sequence statistics, translate, and manipulate biological sequences.

**Domain:** Bioinformatics  
**Upstream project:** [https://biopython.org](https://biopython.org)  
**License:** BSD-3-Clause  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Parse FASTA, GenBank, and other sequence formats
- Compute GC content, molecular weight, and composition
- Translate nucleotide sequences to protein

## Tool Actions

| Action | Description |
|---|---|
| `parse_sequences` | Parse sequence files and emit a per-record summary (id, length, description). |
| `analyze_sequence` | Compute GC content, molecular weight, and (for nucleotides) a protein translation per record. |

## Container Dependencies

- **pip:** biopython

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
