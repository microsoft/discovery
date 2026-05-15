# RetroChimera Model, Tool, & Agent Deployment Guide

This guide provides step-by-step instructions for deploying the RetroChimera tool and its associated agent to the Microsoft Discovery platform.

## Overview

RetroChimera is a model that takes as input a product molecule that one wants to synthesize, encoded as SMILES, and produces several potential chemical reactions which could be used to produce that input molecule. Each reaction is represented as a group of ingredients (reactant molecules), and those molecules are again represented each by a string of characters. This demo also asks GPT-4o to provide an analysis and summary of the results.

## Prerequisites

- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) installed
- [Docker](https://www.docker.com/get-started) installed
- Access to an Azure subscription
- A deployment of the RetroChimera model on Azure AI Foundry
- Azure Container Registry (ACR) with appropriate permissions
- Completed platform onboarding (see [user guide](../../../2-getting-started/quickstart.md))
- Assign the managed identity used in your Discovery workspace the Azure AI User role
- VM quota for a single Standard_NC40ads_H100_v5 image size

## Deployment Steps

### Step 1: Edit the retro.py script 

In the app/retro.py script, replace the URL setting on line number 9 with the actual target URI of you RetroChimera model deployment on Azure AI Foundry.

### Step 2: Login to your Azure Container Registry

> Replace `mycontainerregistry` with your actual ACR name

```bash
az login
az acr login --name mycontainerregistry
```

### Step 3: Build & Push the Docker Image

Use the provided Dockerfile to build the tool image:

> Replace `mycontainerregistry` with your actual ACR name

```bash
docker build -t "mycontainerregistry.azurecr.io/retrochimera:latest" .

docker push "mycontainerregistry.azurecr.io/retrochimera:latest"
```

Test using docker locally:

```bash
docker run -ti --rm -v "$(pwd)/output:/output" mycontainerregistry.azurecr.io/retrochimera:latest python3 retro.py --workflow "single_step" --smiles "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"

docker run -ti --rm -v "$(pwd)/output:/output" mycontainerregistry.azurecr.io/retrochimera:latest python3 retro.py --workflow "multi_step" --smiles "C=CC(=O)N1CCCCC(n2c(=O)c3ncccc3n(Cc3ccc(Oc4cccc(F)c4)cc3)c2=O)C1"
```

### Step 4: Update Tool Definition

Edit the tool definition file (`RetroChimera-Tool.yaml`) and update the ACR path in the image section:  

> Replace `mycontainerregistry` with your actual ACR name

```yaml
infra:
    - name: worker
    infra_type: container
    image:
        acr: mycontainerregistry.azurecr.io/retrochimera:latest
```

### Step 5: Convert YAML to JSON

Use the provided utility to convert YAML definitions to JSON format required by the platform:

#### 5.1 **Convert the model definition**:

```bash
python3 ../../utils/definition-content-creator.py RetroChimera-Model.yaml --output RetroChimera-Model.json --json
```

#### 5.2 **Convert the tool definition**:

```bash
python3 ../../utils/definition-content-creator.py RetroChimera-Tool.yaml --output RetroChimera-Tool.json --json
```

#### 5.3 **Convert the agent definition**:

```bash
python3 ../../utils/definition-content-creator.py RetroChimera-Agent.yaml --output RetroChimera-Agent.json --json
```

### Step 6: Deploy Platform Resources

#### 6.1 Create Model Resource

Deploy the RetroChimera model to the Discovery platform using the generated JSON definition. This creates the model resouce and the endpoint that is specified in the environment-varibles.json file.

> **Reference**: See [Tool Deployment Guide](../../../4-how-to/6-tools-models-agents/a--model-deployment.md) for detailed steps

#### 6.2 Create Tool Resource

Deploy the RetroChimera tool to the Discovery platform using the generated JSON definition. This creates the computational environment for running biomedical literature retrieval operations.

> Be sure to include the model_endpoint_ev.json with updated endpoint information specific to your deplyment.

```json
{
  "MODEL_ENDPOINT": "/subscriptions/<your subscription id>/resourceGroups/<your workspace-mrg>/providers/Microsoft.MachineLearningServices/workspaces/<your Azure Machine Learning workspace>"
}
```

> **Reference**: See [Tool Deployment Guide](../../../4-how-to/6-tools-models-agents/b--tool-deployment.md) for detailed steps

#### 6.3 Create Agent Resource

Deploy the RetroChimera agent using the agent JSON definition. This creates the AI agent that can perform literature search and citation analysis tasks.

> **Reference**: See [Agent Deployment Guide](../../../4-how-to/6-tools-models-agents/c--agent-deployment.md) for detailed steps

#### 6.4 Create Workflow Resource

Create a workflow that utilizes the RetroChimera agent to synthesize a target molecule(s).

#### 6.5 Create Project Resource

Set up a project to us use the RetroChimera workflow & agent.

> **Reference**: See [Project Creation Guide](../../../4-how-to/7-projects/a--creating-project.md) for detailed steps

#### 6.6 Create an Investigation

Create a project investigation that utilizes the RetroChimera agent for sysnthesis.

> **Reference**: See [Creating Investigations Guide](../../../4-how-to/8-investigations/a--creating-investigation.md) for detailed steps

#### 6.7 Create a data container and upload provided sample input files

These are the files tht include sample SMILES strings.

- /sample inputs/smiles-multi-step.txt
- /sample inputs/smiles-single-step.txt

> **Reference**: See [Creating Investigations Guide](../../../4-how-to/4-discovery-infra-resources/b--data-containers-data-assets.md) for detailed steps

#### 6.8 Run an investigation

Type "help" in the chat box and then press the "Enter" key or click "Send" and additional information will be returned about the tool and detailed examples of different prompts that can be used.
