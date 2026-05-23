# PubMed Tool & Agent Deployment Guide

This guide provides step-by-step instructions for deploying the PubMed tool and its associated agent to the Microsoft Discovery platform.

## Overview

PubMed provides access to biomedical literature from the PubMed database, supporting research article search and citation analysis workflows. This deployment includes:

- **Dockerfile**: Used for creation of the PubMed tool container image
- **Tool Definition**: Configuration for the PubMed tool
- **Agent Definition**: AI agent configuration for PubMed

## Prerequisites

Before starting the deployment, ensure you have:

1. Access to Microsoft Discovery platform
2. Azure Container Registry (ACR) with appropriate permissions
3. Docker installed locally for image building
4. Azure CLI or PowerShell for resource management

## Build Docker Image

### Step 1: Build and Publish Docker Image


   ```bash
   docker build -t pubmed:latest .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag pubmed:latest mycontainerregistry.azurecr.io/pubmed:latest
   ```

   > Replace `mycontainerregistry` with your actual ACR name

3. **Login to Azure Container Registry**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image** to your container registry:

   ```bash
   docker push mycontainerregistry.azurecr.io/pubmed:latest
   ```

## File Structure

```text
pubMed/
├── Dockerfile                          # Container image definition
├── PubMed-tool-definition.yaml         # Tool configuration (YAML)
├── PubMed-agent-definition.yaml        # Agent configuration (YAML)
├── PubMed-EnvVars.json                 # Environment variables configuration
└── README.md                           # This deployment guide
```

## Key Configuration Details

### Agent Capabilities

The PubMed agent provides:

- **Literature Search**: Search by keywords, authors, journals, and more
- **Citation Analysis**: Retrieve and process citation information
- **Metadata Extraction**: Extract article details, abstracts, and author information
- **Publication Trend Analysis**: Analyze research trends over time
- **Flexible File Management**: Saves results and citation data with appropriate naming conventions

## API Libraries Included

### PyMed

- Simple Python wrapper for PubMed searches
- Easy-to-use interface for article retrieval
- Automatic handling of search results pagination

### BioPython (Entrez)

- Comprehensive NCBI API access
- Advanced search capabilities
- Citation linking and analysis features
- XML parsing for detailed metadata extraction

### Additional Libraries

- **Pandas**: For data manipulation and analysis
- **Matplotlib**: For visualization of publication trends
- **Requests**: For direct API calls when needed

## Usage

### Basic Literature Search

```python
from pymed import PubMed
import json

pubmed = PubMed(tool="MyTool", email="your_email@example.com")
results = pubmed.query("machine learning healthcare", max_results=50)

articles_data = []
for article in results:
    article_data = {
        "title": article.title,
        "abstract": article.abstract,
        "authors": [str(author) for author in article.authors] if article.authors else [],
        "journal": article.journal,
        "publication_date": str(article.publication_date) if article.publication_date else None,
        "pubmed_id": article.pubmed_id,
        "doi": article.doi
    }
    articles_data.append(article_data)

with open("/output/final_results.json", "w") as f:
    json.dump(articles_data, f, indent=2)

```

### Citation Analysis

```python
from Bio import Entrez
import json
import os

# Get email and API key from environment variables with fallbacks
email = os.getenv("PUBMED_EMAIL", "your_email@example.com")
api_key = os.getenv("PUBMED_API_KEY")

Entrez.email = email
if api_key:
    Entrez.api_key = api_key

# Search for articles
handle = Entrez.esearch(db="pubmed", term="CRISPR", retmax=100)
search_results = Entrez.read(handle)
handle.close()

pmid_list = search_results["IdList"]

# Get citation information
citations_data = []
for pmid in pmid_list:
    handle = Entrez.elink(dbfrom="pubmed", id=pmid, linkname="pubmed_pubmed_citedin")
    citation_results = Entrez.read(handle)
    handle.close()
    
    citations_data.append({
        "pmid": pmid,
        "cited_by_count": len(citation_results[0].get("LinkSetDb", [])),
        "citing_articles": citation_results[0].get("LinkSetDb", [])
    })

with open("/output/citation_analysis.json", "w") as f:
    json.dump(citations_data, f, indent=2)
```

## Environment Variables Configuration

The PubMed agent supports the following environment variables for configuration:

- **`PUBMED_EMAIL`** (Required): Your email address for NCBI API access
  - Default: `"your_email@example.com"` (placeholder)
  - Example: `"researcher@university.edu"`

- **`PUBMED_API_KEY`** (Optional): Your NCBI API key for higher rate limits
  - Default: None (uses 3 requests/second limit)
  - With API key: 10 requests/second limit
  - Get your key at: [NCBI API Key Registration](https://ncbiinsights.ncbi.nlm.nih.gov/2017/11/02/new-api-keys-for-the-e-utilities/)

Set these environment variables in your `PubMed-EnvVars.json` file:

```json
{
    "PUBMED_EMAIL": "your_actual_email@example.com",
    "PUBMED_API_KEY": "your_actual_ncbi_api_key"
}
```

## Important Notes

- **Email Required**: Both PyMed and BioPython require a valid email address for NCBI API access
- **Rate Limiting**: Be mindful of NCBI's rate limits (3 requests per second without API key)
- **API Key**: Consider registering for an NCBI API key for higher rate limits
- **Data Usage**: Respect PubMed's terms of service and data usage policies

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → PubMed (LLM) → PubMed Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** PubMed container for biomedical literature search via PubMed/NCBI API with PMC integration

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
| `pubMed` | `tools/PubMed/` | PubMed is a tool for accessing biomedical literature from the PubMed database, providing a simple interface to search and download research article... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.