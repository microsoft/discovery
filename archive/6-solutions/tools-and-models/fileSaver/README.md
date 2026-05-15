# FileSaver Tool & Agent Deployment Guide

This guide provides step-by-step instructions for deploying the FileSaver tool and its associated agent to the Microsoft Discovery platform.

You can use the tool when agent needs to generate code based on user goal and then store it in a data asset for consumption by next agent in workflow.

## Overview

FileSaver is a versatile file management tool designed to save AI-generated content in various formats including code files, configuration files, and documentation. This deployment includes:

- **Dockerfile**: A dockerfile used for creation of FileSaver tool container image
- **Tool Definition**: Configuration for the FileSaver tool
- **Agent Definition**: AI agent configuration for FileSaver

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
   docker build -t filesaver:latest .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag filesaver:latest mycontainerregistry.azurecr.io/filesaver:latest
   ```

   > Replace `mycontainerregistry` with your actual ACR name

3. **Login to Azure Container Registry**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image** to your container registry:

   ```bash
   docker push mycontainerregistry.azurecr.io/filesaver:latest
   ```

### Step 2: Update Tool Definition

1. **Edit the tool definition file** (`fileSaverTool-tool-definition.yaml`)
2. **Update the ACR path** in the image section:

   ```yaml
   infra:
     - name: worker 
       infra_type: container
       image:
         acr: mycontainerregistry.azurecr.io/filesaver:latest  # Update this line
   ```

   > Replace `mycontainerregistry` with your actual ACR name

### Step 3: Convert YAML to JSON

Use the provided utility to convert YAML definitions to JSON format required by the platform:

1. **Convert the tool definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py fileSaverTool-tool-definition.yaml --output fileSaverTool-tool-definition.json --json
   ```

2. **Convert the agent definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py fileSaverAgent.yaml --output fileSaverAgent.json --json
   ```

### Step 4: Deploy Platform Resources

#### 4.1 Create Tool Resource

Deploy the FileSaver tool to the Discovery platform using the generated JSON definition. This creates the computational environment for running file operations.

> **Reference**: See [Tool Deployment Guide](../../../4-how-to/6-tools-models-agents/b--tool-deployment.md) for detailed steps

#### 4.2 Create Agent Resource

Deploy the FileSaver agent using the agent JSON definition. This creates the AI agent that can generate and save various types of files through natural language.

> **Reference**: See [Agent Deployment Guide](../../../4-how-to/6-tools-models-agents/c--agent-deployment.md) for detailed steps

#### 4.3 Create Workflow Resource

Create a workflow that utilizes the FileSaver agent for code generation and file management tasks.

#### 4.4 Create Project Resource

Set up a project to organize and manage your file generation workflows.

> **Reference**: See [Project Creation Guide](../../../4-how-to/7-projects/a--creating-project.md) for detailed steps

#### 4.5 Create an Investigation

Create a project investigation that utilizes the FileSaver agent for generating and saving various types of files.

> **Reference**: See [Creating Investigations Guide](../../../4-how-to/8-investigations/a--creating-investigation.md) for detailed steps

#### 4.6 Run an investigation

Run the investigation with prompts such as:

- "Generate a Python script for data analysis and save it as analysis.py"
- "Create a Verilog module for a counter circuit and save it as counter.v"
- "Generate a JSON configuration file for a web application and save it as config.json"
- "Create a markdown documentation file for the project and save it as docs.md"

Wait for response and check the generated files in the outputs.

## File Structure

```text
fileSaver/
├── Dockerfile                          # Container image definition
├── fileSaverTool-tool-definition.yaml  # Tool configuration (YAML)
├── fileSaverAgent.yaml                 # Agent configuration (YAML)
├── app/                                # Application source code
│   ├── fileSaver.py                    # Main file saving logic
│   └── io_utils.py                     # I/O utilities and logging
└── README.md                           # This deployment guide
```

## Key Configuration Details

### Agent Capabilities

The FileSaver agent provides:

- **Multi-format Code Generation**: Supports Python, Verilog, JavaScript, JSON, YAML, XML, C/C++, Java, and Markdown
- **Intelligent File Formatting**: Automatically formats code based on file type and best practices
- **Syntax Validation**: Validates generated code for correctness before saving
- **Flexible File Management**: Saves files with appropriate extensions and naming conventions
- **Content Processing**: Handles escape sequences, HTML entities, and Unicode characters

### Supported File Types

The tool supports generation and saving of:

- **Programming Languages**: Python (.py), JavaScript (.js), C/C++ (.c/.cpp), Java (.java), Verilog (.v)
- **Data Formats**: JSON (.json), YAML (.yaml), XML (.xml)
- **Web Technologies**: HTML (.html), CSS (.css)
- **Documentation**: Markdown (.md)
- **Database**: SQL (.sql)
- **Custom Text Files**: Any text-based format

### Key Features

- **Smart Content Processing**: Handles escaped characters and HTML entities
- **Syntax Validation**: Validates Python, JSON, YAML, and other structured formats
- **Code Formatting**: Applies appropriate formatting based on file type
- **Safe File Naming**: Sanitizes file names to prevent security issues
- **Output Management**: Saves all files to `/app/outputs` directory for easy retrieval

## Additional Resources

- [Microsoft Discovery Documentation](../../)
- [Container Image Creation Guide](../../../4-how-to/5-tool-image/a--create-and-publish-container-image.md)

## Support

For platform-specific issues, refer to the [user guide documentation](../../../4-how-to/) or contact your platform administrator.
