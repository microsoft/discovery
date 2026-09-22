# Samtools / BCFtools Agent for Microsoft Discovery

> Manipulate high-throughput sequencing alignments (SAM/BAM/CRAM) and variant calls (VCF/BCF): sorting, indexing, statistics, and filtering.

**Domain:** Genomics  
**Upstream project:** [https://www.htslib.org](https://www.htslib.org)  
**License:** MIT  
**Compute:** CPU-only (no GPU required)

## Capabilities

- Alignment statistics (flagstat, idxstats)
- Variant statistics and filtering

## Tool Actions

| Action | Description |
|---|---|
| `process_alignments` | Compute flagstat and idxstats summaries for BAM/CRAM alignment files. |
| `process_variants` | Compute summary statistics for VCF/BCF variant files with bcftools stats. |

## Container Dependencies

- **conda-forge:** samtools, bcftools
- **pip:** pysam

## Usage

This agent is invoked through Microsoft Discovery. Provide an input
directory with your data files and an output directory for results.
Each action writes `final_results.json` plus detailed artifacts.
