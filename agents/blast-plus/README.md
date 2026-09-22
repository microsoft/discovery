# NCBI BLAST+ Agent for Microsoft Discovery

> Local sequence similarity search using the NCBI BLAST+ suite. Build custom databases and run blastn/blastp/blastx against them entirely offline.

**Domain:** Sequence Search  
**Upstream project:** [https://blast.ncbi.nlm.nih.gov](https://blast.ncbi.nlm.nih.gov)  
**License:** Public Domain (NCBI)  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Build BLAST databases from FASTA with makeblastdb
- Run blastn / blastp / blastx searches
- Tabular output for downstream parsing

## Tool Actions

| Action | Description |
|---|---|
| `makeblastdb` | Build a BLAST database from a FASTA file in the input directory. |
| `run_blast` | Run a BLAST search of query sequences against a database. |

## Container Dependencies

- **conda-forge:** blast

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
