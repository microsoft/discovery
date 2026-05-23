# Statistical Validation Agent

## Overview

Computational workflows in drug discovery, molecular simulation, and QSAR modeling produce numerical results that require rigorous statistical validation before they can inform decisions. Without systematic quality checks, subtle issues — inflated p-values, missing effect sizes, uncorrected multiple comparisons, inappropriate test selection — erode confidence in downstream conclusions.

The Statistical Validation Agent (`statagent`) acts as an omnipresent quality checker that monitors data and results at every stage of a computational pipeline. It provides comprehensive hypothesis testing with automatic test selection, effect size estimation, correlation analysis, bootstrap confidence intervals, Bayesian analysis, and domain-specific threshold evaluation for QSAR, docking, molecular dynamics, quantum chemistry, free energy perturbation, and ADMET workflows. The agent generates publication-quality HTML validation reports with interactive Plotly charts and machine-readable JSON output.

The intended user is a computational chemist, bioinformatician, or data scientist who needs reproducible, statistically rigorous evaluation of experimental or simulated results. A successful outcome is a confidence-scored validation report with actionable recommendations.

### Key capabilities

| Capability | Description |
|---|---|
| **Descriptive statistics** | Summary statistics with proper error bars (SD, SEM, 95% CI, IQR) and outlier detection. |
| **Correlation analysis** | Auto-selection of Pearson, Spearman, or Kendall methods based on data normality and ties. |
| **Hypothesis testing** | Automatic assumption checking and test selection with effect sizes and power analysis. |
| **Multiple comparison correction** | Holm–Šidák and Benjamini–Hochberg FDR correction for multi-test scenarios. |
| **Model evaluation** | Regression and classification metrics with residual diagnostics and cross-validation. |
| **Bootstrap confidence intervals** | Non-parametric CIs for any statistic via resampling. |
| **Bayesian analysis** | Bayes factors and credible intervals for small-sample or ambiguous-evidence scenarios. |
| **Domain-specific thresholds** | Pre-configured quality thresholds for QSAR, docking, MD, QC, FEP, and ADMET domains. |
| **Validation state tracking** | Cumulative confidence scoring across multi-step pipelines with JSON serialization. |
| **HTML reports** | Publication-quality validation reports with interactive Plotly charts and JSON export. |

## Architecture

```
User Prompt
    │
    ▼
┌──────────────────┐
│  LLM Planner     │  (model: {{CHAT-MODEL}}, temperature 0)
│  (reasoning)     │
└──────┬───────────┘
       │  tool call: statagent
       ▼
┌───────────────────────────────────┐
│  Tool Container (CPU)             │
│  ┌─────────────────────────────┐  │
│  │ statagent_utils library     │  │  ValidationState, DescriptiveAnalyzer,
│  │                             │  │  CorrelationAnalyzer, HypothesisTester,
│  │                             │  │  EffectSizeCalculator, BootstrapCI,
│  │                             │  │  BayesianAnalyzer, ModelEvaluator,
│  │                             │  │  ReportGenerator, quick_validate
│  │ numpy / scipy / statsmodels │  │  numerical and statistical computation
│  │ scikit-learn                │  │  ML model evaluation
│  │ pandas                      │  │  data manipulation
│  │ matplotlib / seaborn        │  │  static visualization
│  │ plotly                      │  │  interactive charts
│  │ pingouin                    │  │  advanced statistical tests
│  │ jinja2                      │  │  HTML report templating
│  └─────────────────────────────┘  │
└───────────┬───────────────────────┘
            │
            ▼
  Validation report (HTML), metrics (JSON),
  confidence score, recommendations
            │
            ▼
┌──────────────────────┐
│  LLM Planner         │
│  (interpret results) │
└──────────┬───────────┘
           │
           ▼
     User response
```

**Data flow:**

1. The user provides a CSV dataset or describes the validation task (e.g., "validate predicted vs. experimental binding affinities").
2. The LLM planner generates a Python script using `statagent_utils` functions.
3. The tool container executes the script — loads data, checks assumptions, runs statistical tests, evaluates domain thresholds, and builds a validation report.
4. Results are saved to `/output/` as an HTML report and a JSON file with all metrics.
5. The planner interprets the confidence score, summarizes findings, and provides recommendations.

**External dependencies:** None at runtime. All statistical libraries are pre-installed in the container. No GPU required — CPU-only compute.

## Prerequisites

| Requirement | Details |
|---|---|
| **Azure subscription** | An active Azure subscription with permissions to create resources. |
| **Azure AI Foundry project** | A deployed Azure AI Foundry project with agent capabilities enabled. |
| **Model deployment** | A chat-completion model deployed and referenced as `{{CHAT-MODEL}}`. |
| **Compute** | CPU compute is sufficient. Recommended SKU: `Standard_D4s_v3`. No GPU required. |
| **Network access** | Not required at runtime; all libraries and models are pre-installed in the container image. |

## Configuration

Register the agent with the following parameters:

| Parameter | Value | Description |
|---|---|---|
| `name` | `statagent` | Agent identifier. |
| `displayName` | `Statistical Validation Agent` | Human-readable agent name shown in Discovery Studio. |
| `toolName` | `statagent` | Tool identifier used in tool calls. |
| `toolId` | `{{statagentToolId}}` | Unique tool ID assigned during provisioning. |
| `model` | `{{CHAT-MODEL}}` | The backing LLM deployment name. |
| `container.gpu` | `false` | CPU-only; no GPU required. |
| `container.packages` | `statagent_utils, numpy, scipy, statsmodels, scikit-learn, pandas, matplotlib, seaborn, pingouin, plotly, jinja2` | Python packages inside the container. |

### Example agent definition (YAML snippet)

```yaml
kind: prompt
name: statagent
displayName: Statistical Validation Agent
model:
  id: '{{CHAT-MODEL}}'
  options:
    temperature: 0
    topP: 0
discoveryExtensions:
  tools:
    - toolId: '{{statagentToolId}}'
      confirmation: Disabled
```

## Usage

### Step 1 — Build and publish the container image

```bash
catalog_publish_image(
    image_name="statagent:latest",
    dockerfile_path="Dockerfile",
    build_context="."
)
```

### Step 2 — Publish the tool and agent definitions

```bash
catalog_publish_tool(tool_yaml_path="statagent-tool-definition.yaml")
catalog_publish_agent(
    agent_yaml_path="statagent-agent-definition.yaml",
    tool_name="statagent"
)
```

### Step 3 — Deploy via Discovery Studio

Navigate to the Statistical Validation Agent card in Discovery Studio and click **Deploy**. Fill in the configuration parameters listed above.

### Step 4 — Example prompts

**Validate predicted vs. experimental binding affinities:**

```text
I have a CSV with columns 'predicted_dG' and 'experimental_dG' for 50 compounds.
Run a full statistical validation: check data quality, compute correlations with
auto-selection, test significance, evaluate against QSAR domain thresholds, and
generate a validation report.
```

**Compare two docking methods:**

```text
I have docking scores from AutoDock Vina and Glide for the same 30 ligands in two
CSV columns. Compare the methods statistically: check if there's a significant
difference, compute effect sizes, run both frequentist and Bayesian tests, and
report which method performs better.
```

**Evaluate a classification model on imbalanced data:**

```text
I have true labels and predicted labels for a toxicity classifier (y_true and y_pred
columns). The dataset is imbalanced (10% positive). Evaluate the model with appropriate
metrics, compute confidence intervals on accuracy, and rate it against ADMET domain
thresholds.
```

**Intermediate pipeline validation:**

```text
I'm running a multi-step computational workflow. At this step, I have MD simulation
energies in a CSV. Validate the simulation convergence: check energy drift, temperature
stability, and RMSD equilibrium against MD domain thresholds. Save the validation
state for the next step.
```

### Step 5 — Example output

```json
{
  "status": "completed",
  "confidence_score": 87,
  "confidence_label": "MODERATE",
  "checks_passed": 12,
  "checks_failed": 2,
  "output_files": {
    "validation_report": "/output/validation_report.html",
    "validation_results": "/output/validation_results.json",
    "correlation_plot": "/output/correlation_scatter.png"
  }
}
```

## Support

If you encounter issues or have feature requests:

- **GitHub Issues:** Open an issue at [microsoft/microsoft-discovery-samples](https://github.com/microsoft/discovery-catalog/issues) with the label `agent/statagent`.
- **Contact:** [discovery-catalog@microsoft.com](mailto:discovery-catalog@microsoft.com)
- **Documentation:** Refer to the [Microsoft Discovery authoring guide](https://github.com/microsoft/microsoft-discovery-samples/blob/main/docs/authoring-guide.md) for agent development best practices.
- **Community:** Join the discussion in the repository's Discussions tab for questions and tips.


## Tools

| Tool | Path | Description |
|---|---|---|
| `statagent` | `tools/statagent/` | Statistical validation agent for rigorous evaluation of computational workflow results. |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.