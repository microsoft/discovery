# iverilog Tool Deployment Guide

This guide explains how to build a Docker image for iverilog, push it to Azure Container Registry (ACR), and deploy the tool control plane resources using the provided scripts.

## Using the Tool

iverilog is intended to compile ALL of the Verilog HDL, as described in the IEEE-1364 standard. Of course, it's not quite there yet. It does currently handle a mix of structural and behavioural constructs..

### Key Features

- Compile ALL of the Verilog HDL, as described in the IEEE-1364 standard
- Compiler that generates code employed by back-end tools
- Handle a mix of structural and behavioural constructs

## Prerequisites

- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) installed
- [Docker](https://www.docker.com/get-started) installed
- Access to an Azure subscription

## Building and Pushing the Docker Image

### Step 1: Configure Environment Variables

Before building and pushing the Docker image, set the following environment variables:

```bash
# Azure Container Registry details
export ACR_NAME="yourAcrName"
export IMAGE_NAME="iverilog"
export IMAGE_TAG="latest"
```

### Step 2: Build the Docker Image

Use the provided Dockerfile to build the iverilog image:

```bash
# Navigate to the directory containing the Dockerfile
# (The Dockerfile is in the current directory)

# Build the Docker image
docker build -t ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG} .
```

### Step 3: Authenticate and Push to ACR

```bash
# Login to Azure
az login

# Login to ACR
az acr login --name ${ACR_NAME}

# Push the image to ACR
docker push ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}
```

## Update Tool definition

Once the docker image is created an pushed to Azure Container Registry, update the repository path in tool definition under "infra" section -

```yaml
    image:
      acr: test.azurecr.io/iverilog-image:latest 
```

## Update the ARM template

## Tool Definition

The tool definition is available as `iverilog.discotool.yaml` in the current directory. This file contains the complete tool definition for deployment.

## Deploying the Tool Control Plane Resources

### Step 1: Convert YAML to JSON

**Important**: Before deployment, the YAML tool definition must be converted to JSON format for use with ARM templates or Azure Resource Manager deployments.

The tool definition is available in `iverilog.discotool.yaml` in this directory. Convert this YAML file to JSON format before proceeding with deployment.

### Step 2: Deploy Using Discovery Platform

Use the Discovery platform deployment mechanisms to deploy the tool using the converted JSON definition file:

- **Tool Definition (YAML)**: `./iverilog.discotool.yaml` (convert to JSON first)
- **Tool Definition (JSON)**: Convert the YAML file to JSON for ARM template deployment

## Available Files

The iverilog tool package includes:

- **Tool Definition**: `iverilog.discotool.yaml` - Complete tool specification
- **Agent Definition**: `iverilog.discoagent.yaml` - Agent configuration
- **Workflow**: `iVerilogReference.discoworkflow.yaml` - Reference workflow
- **Dockerfile**: Container build specification
- **Application Files**: Located in the `app/` directory
  - `html_decode.py` - HTML decoding utility
  - `syntax_error.v` - Syntax error test file
  - `testfile.v` - Test Verilog file

## Additional Resources

- [Azure Container Registry Documentation](https://docs.microsoft.com/en-us/azure/container-registry/)
- [iverilog Documentation](https://steveicarus.github.io/iverilog/usage/index.html)