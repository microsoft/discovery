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
5. Completed platform onboarding (see [user guide](../../../4-how-to/))

## Deployment Steps

### Step 1: Build and Publish Docker Image

1. **Build the Docker image** from the provided Dockerfile:

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

### Step 2: Update Tool Definition

1. **Edit the tool definition file** (`PubMed-tool-definition.yaml`)
2. **Update the ACR path** in the image section:

   ```yaml
   infra:
     - name: worker
       infra_type: container
       image:
         acr: mycontainerregistry.azurecr.io/pubmed:latest  # Update this line
   ```

   > Replace `mycontainerregistry` with your actual ACR name

### Step 2.1: Configure Environment Variables (Optional)

1. **Edit the environment variables file** (`PubMed-EnvVars.json`)
2. **Update the email and API key** (if you have one):

   ```json
   {
       "PUBMED_EMAIL": "your_actual_email@example.com",
       "PUBMED_API_KEY": "your_actual_ncbi_api_key"
   }
   ```

   > **Note**: The API key is optional. If not provided, you'll have a 3 requests/second limit instead of 10 requests/second.

### Step 3: Convert YAML to JSON

Use the provided utility to convert YAML definitions to JSON format required by the platform:

1. **Convert the tool definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py PubMed-tool-definition.yaml --output PubMed-tool-definition.json --json
   ```

2. **Convert the agent definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py PubMed-agent-definition.yaml --output PubMed-agent-definition.json --json
   ```

### Step 4: Deploy Platform Resources

#### 4.1 Create Tool Resource

Deploy the PubMed tool to the Discovery platform using the generated JSON definition. This creates the computational environment for running biomedical literature retrieval operations.

> **Reference**: See [Tool Deployment Guide](../../../4-how-to/6-tools-models-agents/b--tool-deployment.md) for detailed steps

#### 4.2 Create Agent Resource

Deploy the PubMed agent using the agent JSON definition. This creates the AI agent that can perform literature search and citation analysis tasks.

> **Reference**: See [Agent Deployment Guide](../../../4-how-to/6-tools-models-agents/c--agent-deployment.md) for detailed steps

#### 4.3 Create Workflow Resource

Create a workflow that utilizes the PubMed agent for literature search and citation analysis tasks.

#### 4.4 Create Project Resource

Set up a project to organize and manage your biomedical literature workflows.

> **Reference**: See [Project Creation Guide](../../../4-how-to/7-projects/a--creating-project.md) for detailed steps

#### 4.5 Create an Investigation

Create a project investigation that utilizes the PubMed agent for literature search and analysis.

> **Reference**: See [Creating Investigations Guide](../../../4-how-to/8-investigations/a--creating-investigation.md) for detailed steps

#### 4.6 Run an investigation

Run the investigation with prompts such as:

- "Search for recent articles about cancer immunotherapy."
- "Find papers by a specific author on machine learning in healthcare."
- "Retrieve citation information for PubMed ID 12345678."
- "Analyze publication trends for COVID-19 research."
- "Extract metadata from articles about CRISPR gene editing."

Wait for response and check the generated outputs.

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

### Supported Data Types

- **Citation Data**: JSON, CSV, TSV formats
- **Article Metadata**: Title, abstract, authors, journal, publication date
- **Publication Analysis**: Citation counts, trend analysis
- **Custom Text Files**: Any text-based format for article content

### Key Features

- **Smart Content Processing**: Handles biomedical literature data formats and analysis
- **Safe File Naming**: Sanitizes file names to prevent security issues
- **Output Management**: Saves all files to `/output` directory for easy retrieval
- **API Integration**: Uses both PyMed and BioPython for comprehensive PubMed access
- **Email Configuration**: Properly configures NCBI API access with email requirements

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

## Usage Examples

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

## Additional Resources

- [Microsoft Discovery Documentation](../../)
- [Container Image Creation Guide](../../../4-how-to/5-tool-image/a--create-and-publish-container-image.md)
- [PubMed API Documentation](https://www.ncbi.nlm.nih.gov/books/NBK25501/)
- [PyMed Documentation](https://pypi.org/project/pymed/)
- [BioPython Entrez Documentation](https://biopython.org/docs/1.75/api/Bio.Entrez.html)

## Support

For platform-specific issues, refer to the [user guide documentation](../../../4-how-to/) or contact your platform administrator.

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
