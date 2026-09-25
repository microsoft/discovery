# Flow Cytometry Referee

Flow Cytometry Referee reviews standard FCS flow-cytometry files and supporting analysis material for technical
quality and reproducibility. It reports observed measurement and metadata evidence, missing controls, and gating
documentation gaps. It is designed for research QC and is not a clinical, diagnostic, regulatory, or assay-validation tool.

## Overview

Researchers often receive event files, a gating figure, and partial panel documentation from different systems. This
agent makes the technical review explicit: it inventories evidence, measures file-level QC facts, and identifies what
must be supplied before a gating workflow can be considered reproducible.

## Architecture

The prompt agent uses a parameterized Foundry chat model and the `flow-qc` Python environment. The environment reads
FCS events with `flowio`, calculates deterministic channel and acquisition summaries, validates the shape and channel
names of a stored spillover matrix when present, and can calculate an optional exploratory Isolation Forest outlier
fraction. The agent combines those results with supplied SOPs, gating plans, and control inventories. The outlier
score flags unusual measurement events only; it does not classify cells or samples or establish a QC threshold.

## Prerequisites

- An Azure subscription with Microsoft Discovery deployment permissions.
- An Azure AI Foundry project and a chat-model deployment for `{{CHAT-MODEL}}`.
- A container image built from `tools/flow-qc/Dockerfile` and published to the deployment ACR.
- Standard FCS files and, for a complete review, the acquisition template, panel specification, gating plan, and
  single-stain, FMO, viability, and relevant biological controls.

## Configuration

| Parameter | Description | Example |
| --- | --- | --- |
| `{{CHAT-MODEL}}` | Foundry chat-model deployment | `gpt-4o-deployment` |
| `{{flowQcToolId}}` | Deployed Discovery tool ARM resource ID | `/subscriptions/.../tools/flow-qc` |

## Usage

1. Deploy the agent and the `flow-qc` tool through Discovery.
2. Supply one or more FCS files and the available supporting documents.
3. Ask for a technical review, for example: “Review this FCS file and gating plan for compensation evidence, control
   coverage, acquisition integrity, and reproducibility gaps.”
4. Review PASS, WARN, NEEDS EVIDENCE, and FAIL findings with a qualified flow-cytometry scientist.

## Tools

`flow-qc` provides a Python code environment with `flowio`, NumPy, pandas, scikit-learn, and `flow_qc_utils`.
It can read standard FCS files, summarize event and channel values, inspect and validate stored compensation-related
metadata, evaluate acquisition-time continuity, calculate an exploratory event-outlier fraction, and create a
technical QC dashboard. A declared-range-limit fraction is a measurement-range check, not proof of detector
saturation. Derived reports belong in the configured output directory.

## Known Limitations

- It does not inspect microscopy images or imaging flow-cytometry imagery.
- It cannot prove compensation is correct from FCS metadata alone.
- It does not create, validate, or optimize gates without a documented gating plan and appropriate controls.
- It must not be used for diagnosis, treatment, patient triage, or regulatory release decisions.
- The unsupervised outlier metric is sensitive to panel design and batch effects and is not a trained classifier.

## Support

For issues or questions, open an issue at https://github.com/AzizMuminov/discovery/issues.

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the catalog contribution workflow.
