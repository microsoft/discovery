# ClinicalTrials Agent

An AI agent for accessing clinical trial data from ClinicalTrials.gov, providing a comprehensive interface to search and download information about medical studies, interventions, trial phases, eligibility criteria, enrollment data, and results using the ClinicalTrials.gov API v2. Access over 400,000 clinical studies from around the world.

## Quick Start

### Building the Docker Image

```bash
# 1. Build the Docker image
docker build -t clinicaltrials:latest .

# 2. Test the image
docker run --rm clinicaltrials:latest \
    python3 -c "from clinicaltrials_utils import ClinicalTrialsUtils; \
                utils = ClinicalTrialsUtils(); \
                print('ClinicalTrials agent ready')"
```

## Overview

The ClinicalTrials agent provides access to the ClinicalTrials.gov API v2 for searching and retrieving clinical trial data. Key features include:

- **No Authentication Required**: ClinicalTrials.gov API is publicly accessible
- **400,000+ Studies**: Access to clinical trials worldwide
- **Comprehensive Data**: Study design, conditions, interventions, eligibility, enrollment, sponsors, locations, and results
- **Safe Date Handling**: Built-in utilities for ClinicalTrials.gov's variable date formats
- **Phase Filtering**: Strict phase matching to exclude combined phases

## Agent Capabilities

### Core Functions

1. **Study Search**: Flexible search with multiple filters (condition, intervention, location, status, phase)
   - `search_studies()` — Multi-parameter search
   - `search_by_condition()` — Search by medical condition
   - `search_by_intervention()` — Search by treatment/drug
   - `search_recruiting_studies()` — Find currently recruiting trials

2. **Study Details**: Comprehensive information for specific trials
   - `get_study_details(nct_id)` — Full study metadata by NCT ID

3. **Download Workflows**: Complete search-and-download pipelines
   - `download_trial_data()` — One-line search with detailed data download
   - `download_study_data()` — Full download workflow with progress output

4. **Date Handling**: Safe utilities for ClinicalTrials.gov's variable date formats
   - `sort_studies_by_date()` — Sort studies with automatic format handling
   - `filter_studies_by_year()` — Filter by year range
   - `filter_studies_by_date()` — Filter by full date range
   - `get_study_year()` — Extract year as integer
   - `get_date_parts()` — Extract year, month, day components

### Search Parameters

| Parameter | Description | Example Values |
|-----------|-------------|----------------|
| `query` | General text search | "CAR-T therapy" |
| `condition` | Disease or condition | "Cancer", "Diabetes", "COVID-19" |
| `intervention` | Treatment/intervention | "Pembrolizumab", "Physical Therapy" |
| `location` | Geographic location | "United States", "California" |
| `status` | Study status | "RECRUITING", "COMPLETED", "ACTIVE_NOT_RECRUITING" |
| `phase` | Study phase | "PHASE1", "PHASE2", "PHASE3", "PHASE4" |

### Data Fields Available

Each study includes:
- **Identification**: NCT ID, title, acronym
- **Description**: Brief summary, detailed description
- **Status**: Overall status, start/completion dates, last update
- **Design**: Study type, phase, allocation, intervention model, masking, primary purpose
- **Conditions**: Medical conditions, keywords
- **Interventions**: Type, name, description of treatments
- **Enrollment**: Participant count and type (actual/anticipated)
- **Eligibility**: Criteria text, gender, age limits, healthy volunteers
- **Sponsor**: Lead sponsor, collaborators
- **Locations**: Facility names, cities, states, countries
- **Results**: Availability and link to results data

## Build Docker Image

### Step 1: Build and Publish Docker Image


   ```bash
   docker build -t clinicaltrials:latest .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag clinicaltrials:latest mycontainerregistry.azurecr.io/clinicaltrials:latest
   ```

   > Replace `mycontainerregistry` with your actual ACR name

3. **Login to Azure Container Registry**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image**:

   ```bash
   docker push mycontainerregistry.azurecr.io/clinicaltrials:latest
   ```

## File Structure

```text
clinicalTrials/
├── Dockerfile                              # Container image definition
├── ClinicalTrials-tool-definition.yaml     # Tool configuration (YAML)
├── ClinicalTrials-agent-definition.yaml    # Agent configuration (YAML)
├── clinicaltrials_utils.py                 # Utility library
└── README.md                               # This deployment guide
```

## Usage

### Basic Search and Download

```python
from clinicaltrials_utils import download_trial_data
import json

OUTPUT_DIR = '/output'

results = download_trial_data(
    condition="Breast Cancer",
    intervention="Immunotherapy",
    max_results=15
)

with open(f"{OUTPUT_DIR}/final_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print(f"Found {results['total_studies_found']} studies")
```

### Search Recruiting Trials by Location

```python
from clinicaltrials_utils import ClinicalTrialsUtils
import json

OUTPUT_DIR = '/output'
utils = ClinicalTrialsUtils()

studies = utils.search_recruiting_studies(
    condition="Lung Cancer",
    location="California",
    max_results=20
)

detailed = []
for study in studies[:5]:
    details = utils.get_study_details(study["nct_id"])
    if details:
        detailed.append(details)

results = {
    "total_recruiting": len(studies),
    "detailed_studies": detailed
}

with open(f"{OUTPUT_DIR}/final_results.json", "w") as f:
    json.dump(results, f, indent=2)
```

### Search by Intervention with Condition Analysis

```python
from clinicaltrials_utils import ClinicalTrialsUtils
import json

OUTPUT_DIR = '/output'
utils = ClinicalTrialsUtils()

studies = utils.search_by_intervention(intervention="Pembrolizumab", max_results=25)

conditions_count = {}
for study in studies:
    for condition in study.get("conditions", []):
        conditions_count[condition] = conditions_count.get(condition, 0) + 1

results = {
    "intervention": "Pembrolizumab",
    "total_trials": len(studies),
    "conditions_treated": conditions_count,
    "trials": studies
}

with open(f"{OUTPUT_DIR}/final_results.json", "w") as f:
    json.dump(results, f, indent=2)
```

### Safe Date Handling

```python
from clinicaltrials_utils import download_trial_data, sort_studies_by_date, filter_studies_by_year

OUTPUT_DIR = '/output'

results = download_trial_data(condition="Diabetes", phase="PHASE3", max_results=50)
studies = results.get("detailed_data", [])

# Sort by start date
sorted_studies = sort_studies_by_date(studies, date_field="start_date")

# Filter by year range
recent_studies = filter_studies_by_year(studies, min_year=2020)
```

## Date Handling

ClinicalTrials.gov returns dates in multiple formats (`YYYY-MM-DD`, `YYYY-MM`, or `YYYY`). Always use the built-in helper functions instead of `datetime.strptime()` directly:

| Function | Purpose |
|----------|---------|
| `parse_clinical_trial_date(date_str)` | Normalize to `YYYY-MM-DD` string |
| `sort_studies_by_date(studies, field)` | Sort with automatic format handling |
| `filter_studies_by_year(studies, min_year)` | Filter by year range |
| `filter_studies_by_date(studies, min_date)` | Filter by full date range |
| `get_study_year(study, field)` | Extract year as integer |
| `get_date_parts(date_str)` | Extract year, month, day components |

**Common pitfall**: `parse_clinical_trial_date()` returns a **string** in `YYYY-MM-DD` format, NOT a `datetime` object. Use `get_date_parts()` or `get_study_year()` for integer comparisons.

## Best Practices

1. **Use high-level convenience functions** (`download_trial_data`, `search_clinical_trials`) for simple workflows
2. **Use the ClinicalTrialsUtils class** for custom multi-step workflows
3. **Respect API rate limits**: The utility module automatically adds 0.5-second delays between requests
4. **Use safe date handling**: Always use built-in date utilities, never `datetime.strptime()` directly
5. **Use strict phase filtering** when exact phase matching is needed: `strict_phase_filter=True`
6. **Handle missing data**: Some trials have limited data depending on status and submission completeness
7. **Save results to `final_results.json`**: Always store final output in the standard location

## Common Pitfalls

1. **Direct date parsing**: Using `datetime.strptime(date, "%Y-%m-%d")` fails on partial dates like `"2023-06"`. Always use `parse_clinical_trial_date()` or `sort_studies_by_date()`.
2. **Assuming date is a datetime object**: `parse_clinical_trial_date()` returns a string, not a `datetime` object. Use `get_study_year()` for integer comparisons.
3. **Phase search returning combined phases**: A search for `PHASE1` may return `"PHASE1, PHASE2"` trials. Use `strict_phase_filter=True` for exact matching.
4. **Missing fields**: Not all studies have all fields populated. Always use `.get()` with defaults.

## Libraries Included

- **requests**: HTTP client for ClinicalTrials.gov API v2
- **pandas**: Data manipulation and analysis
- **matplotlib**: Visualization of trial trends and statistics

## Complementary Agents

- **PubMed Agent**: For biomedical literature search and citation analysis
- **ChEMBL Agent**: For bioactivity and pharmacological data
- **BindingDB Agent**: For protein-ligand binding affinity data
- **PDBSearch Agent**: For protein structure search and retrieval

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → Clinical Trials (LLM) → ClinicalTrials.gov Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** ClinicalTrials.gov container for clinical trial data retrieval via API v2

## Prerequisites

- Azure subscription with Contributor role
- Azure AI Foundry project with a model deployment (e.g. GPT-4o)
- Docker for building the tool container image
- Azure Container Registry (ACR) for hosting the tool image

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{model}}` | Azure AI Foundry model deployment name | `gpt-4o` |


## Support

For issues or questions, open a GitHub issue:
<https://github.com/microsoft/discovery-catalog/issues>

Microsoft Discovery team contact: discovery-catalog@microsoft.com


## Tools

| Tool | Path | Description |
|---|---|---|
| `clinicalTrials` | `tools/ClinicalTrials/` | ClinicalTrials is a tool for accessing clinical trial data from ClinicalTrials.gov, providing a comprehensive interface to search and download info... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.