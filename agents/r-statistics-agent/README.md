# R Statistics Agent

## Overview

R Statistics Agent writes and runs R scripts for researchers analyzing tabular
data. It supports descriptive statistics, hypothesis tests, regression,
resampling, and visualization, returning reproducible scripts, tables, plots,
and the R session information rather than unsupported numerical claims.

## Architecture

1. A prompt agent uses the configured chat model to clarify the research
   question, inspect available data, and propose an analysis.
2. After user confirmation, Discovery runs the generated script in the
   `r-statistics` CPU-only code environment using
   `Rscript --vanilla "/{{scriptName}}"`.
3. The script reads mounted assets from `/input` and writes deliverables to
   `/output`. Scratch files go in `/workdir`. Scripts must be self-contained;
   persistent sessions and cross-call filesystem state are not assumed.
4. The agent summarizes the observed results, assumptions, warnings, and
   artifact locations. Discovery's data-handling tools remain enabled for
   asset inspection and output handling.

The image uses the policy-approved Docker Official Image `r-base:4.5.3`,
pinned to an immutable multi-platform digest. It runs as UID/GID `10001:10001`,
does not copy datasets or credentials into the image, and requires no external
API or runtime package downloads. `--vanilla` disables startup profiles and
workspace restoration; it is not a sandbox for untrusted R code.

## Prerequisites

- A Discovery workspace and permission to register tools and deploy agents.
- A compatible chat model deployment accessible to the workspace.
- An Azure Container Registry and permission to build/push the tool image;
  the execution infrastructure needs permission to pull it.
- A CPU node pool meeting the tool's resource requirements. The definition
  requests a minimum of 1 vCPU, 2 GiB RAM, and 4 GiB ephemeral storage.
- Mount permissions allowing UID/GID `10001:10001` to read the script and
  input assets and write `/output` and `/workdir`. Mounted volumes override
  image-directory ownership; configure their permissions at deployment.
- Docker with Linux container support and Python 3 for local integration tests.

## Configuration

| Parameter | Description |
| --- | --- |
| `{{CHAT-MODEL}}` | Chat model deployment name; temperature defaults to zero. |
| `{{rStatisticsToolId}}` | ARM resource ID of the registered `r-statistics` tool. |
| `{name}` in the tool image | Deployer-substituted ACR name; image path is `r-statistics:1.1.0`. |

Register the tool before deploying the agent, substitute its resource ID in
[agent.yaml](agent.yaml), and resolve the model deployment. No subscription,
registry, or tool resource ID is hardcoded. Both human-in-the-loop input and
tool confirmation are enabled.

There are no required API keys or secret environment variables. The image sets
`HOME=/home/rworker`, `TMPDIR=/workdir`, `OMP_NUM_THREADS=1`, and
`OPENBLAS_NUM_THREADS=1` to provide writable scratch space and avoid implicit
thread oversubscription.

## Usage

Deploy through Discovery Studio or your catalog deployment workflow after
building and registering the tool. Attach your dataset, identify its relevant
columns and study design, and approve the proposed execution.

Example prompts:

- "Inspect my uploaded CSV, report column types and missingness, and create
  descriptive statistics and histograms without silently dropping rows."
- "Compare response between treatment and control. Check whether the samples
  are independent, explain the test assumptions, and report the effect size,
  95% confidence interval, and p-value."
- "Fit response as a function of dose, save coefficient estimates and confidence
  intervals, and generate residual diagnostics. Explain any assumption violations."
- "Bootstrap the median with seed 42 and 2,000 resamples. Save the interval,
  generated script, and session information."

### Local build and validation

The tool folder contains the tool definition, reproducible image build inputs,
optional container tests, and a synthetic usage example. Only `Dockerfile`,
`packages.csv`, and `install-packages.R` enter the Docker build context;
tests and examples are not included in the image.

Run from the repository root in PowerShell:

```powershell
docker build --tag r-statistics:1.1.0 .\agents\r-statistics-agent\tools\r-statistics
python -m unittest discover -s .\agents\r-statistics-agent\tools\r-statistics -p "test_*.py" -v
```

Set `R_STATISTICS_IMAGE` if testing another tag. The tests require an already
built image and fail explicitly if Docker or the image is unavailable. They
check the R version, recommended packages, non-root identity, directory
permissions, regression estimates, PNG artifacts, reproducibility files,
invalid-input rejection, exact package versions, headless ggplot2 rendering,
zero-outlier tables, all-missing/constant columns, small samples, and nonzero
error exit status. Test containers disable
networking, drop Linux capabilities, and enable `no-new-privileges`.

The included [analysis example](tools/r-statistics/examples/analysis.R) reads
[five synthetic observations](tools/r-statistics/examples/observations.csv)
and fits `y ~ x`. The test mounts the script at `/analysis.R` (matching the
code-environment root script convention), inputs at `/input`, and a temporary
output directory at `/output`. Expected estimates are intercept `0.7` and slope
`2.1`. This tiny fixture demonstrates execution, not scientific validity.

## Tools

| Tool | Interface | Inputs | Outputs |
| --- | --- | --- | --- |
| [r-statistics](tools/r-statistics/tool.yaml) | R code environment; no fixed actions | R script and mounted CSV/TSV or other explicitly supported text data | Script-defined CSV/text tables, PNG/PDF plots, executed script, and session information in `/output` |

Installed capabilities include base R and recommended packages: `stats`,
`utils`, `graphics`, `grDevices`, `datasets`, `methods`, `MASS`, `Matrix`,
`survival`, and `lattice`, plus **ggplot2 4.0.0**. The
[package manifest](tools/r-statistics/packages.csv) pins ggplot2 and its added
dependencies; the [build installer](tools/r-statistics/install-packages.R)
installs only those versions, without automatic dependency resolution, and
verifies each installed version. CRAN moves older tarballs into its Archive;
the installer logs a download failure before trying the current location for
the same pinned version. Failure at both locations stops the build.
Headless PNG output uses the Cairo graphics device.
The example produces `coefficients.csv`, `model-summary.txt`, `scatter.png`,
`diagnostics.png`, `analysis.R`, and `session-info.txt`. Larger results belong
in artifacts because execution logs can be truncated.

## Known Limitations

- The image includes ggplot2 but not the complete tidyverse, Bioconductor, RStudio, or
  notebook services. Dependencies must be added through a reviewed image
  rebuild, not installed by the agent at runtime.
- In-memory R analyses are limited by node memory and ephemeral storage.
  GPU acceleration and distributed execution are not configured.
- Arbitrary R execution is powerful and is not made safe by non-root identity
  alone. Apply platform isolation, resource limits, and appropriate network
  policy. No network restriction is declared by this tool definition.
- Mounted input permissions must be set read-only by the execution platform;
  the Dockerfile cannot enforce permissions on externally mounted volumes.
- Small samples, missing data, dependence, confounding, and violated model
  assumptions can invalidate conclusions. Outputs require scientific review
  and are not clinical or regulatory advice.
- The pinned base digest makes rebuilds reproducible but does not acquire
  future fixes automatically. Review upstream updates, scan images, update
  the digest/version, and rerun tests before publishing an updated image.
- Local container tests do not validate Discovery's deployed R execution,
  asset promotion, confirmation UX, or model behavior. Verify these in your
  target workspace after tool and agent deployment.

## Support

Contact <discovery-catalog@microsoft.com> or use the
[Microsoft Discovery discussions](https://techcommunity.microsoft.com/category/azure/discussions/microsoft-discovery-discussions).

## Contributing

Follow the [catalog contribution workflow](../../CONTRIBUTING.md) and
[agent authoring guide](../../docs/authoring-guides/agent-authoring-guide.md).
Rerun the container tests after changing the image or example. The repository's
privileged PR workflows validate catalog data but do not execute submitted tool
code. Do not hand-edit the generated catalog registry.
