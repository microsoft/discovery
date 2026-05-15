# Create and Publish Container Image

This section helps you understand when and how to create and publish tool container images to Azure Container Registry (ACR) for use with Microsoft Discovery platform.

## Overview

Before proceeding with scientific investigations on the Microsoft Discovery platform, you need access to containerized tools that can be deployed by the Supercomputer. This section covers two common scenarios for obtaining these tool images.

## Scenario Assessment

### Scenario 1: Tools Already Available per Microsoft Discovery Requirements

**If a publisher in your organization has already created and published tools to ACR**, you can skip the image creation process entirely. This means:

- Your organization's publisher has already followed the complete tool development workflow outlined in the [Publisher Guide - Tools Section](../6-tools-models-agents/tools-publishing/)
- Tool images are already available in your organization's Azure Container Registry
- You can proceed directly to [tool deployment](../6-tools-models-agents/b--tool-deployment.md)

**To verify if tools are already available:**

1. Check with your organization's Microsoft Discovery administrators
2. Review your ACR repositories for existing tool images:

   ```bash
   az acr repository list --name <your-acr-name> --output table
   ```

3. Confirm tool availability with your technical team

If tools are already published, **skip to [Tools, Models, and Agents Creation](../6-tools-models-agents/)**.

### Scenario 2: Building Tools from Scratch or Samples

**If you are building tools from scratch,** follow the [tool publishing experience](../6-tools-models-agents/tools-publishing/).

**If you need to build tool images from sample tools** provided by Microsoft Discovery or partners, you'll need to create and publish container images. This applies when:

- You're working with sample tools from the Microsoft Discovery repository
- You're adapting existing open-source tools for the platform
- You're starting fresh with new tool development

## Building and Publishing Tool Images

When you need to build tool images (Scenario 2), follow these steps:

### Prerequisites

Ensure you have the necessary setup:

- **Docker Environment**: Docker Desktop or Docker Engine running
- **Azure Access**: Azure CLI configured with appropriate permissions
- **Sample Tools**: Access to Microsoft Discovery sample tools or your custom tools

### Quick Start for Sample Tools

For the molToolkit sample tool included in the Microsoft Discovery repository:

1. **Navigate to the sample tool directory:**

   ```bash
   cd 6-solutions/tools-and-models/molToolkit
   ```

2. **Build the container image:**

   ```bash
   docker build -t moltoolkit:latest .
   ```

3. **Test the image locally** (recommended):

   ```bash
   # Test that molecular utilities are available
   docker run --rm \
     moltoolkit:latest \
     python -c "from molecular_utils import validate_smiles; print('SMILES valid:', validate_smiles('CCO'))"
   ```

4. **Tag and push to your ACR:**

   ```bash
   # Configure ACR details
   ACR_NAME="<your-acr-name>"
   ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --query loginServer --output tsv)

   # Login to ACR
   az acr login --name $ACR_NAME

   # Tag and push
   docker tag moltoolkit:latest $ACR_LOGIN_SERVER/moltoolkit:latest
   docker push $ACR_LOGIN_SERVER/moltoolkit:latest
   ```

### Detailed Image Creation Process

For comprehensive guidance on creating, validating, and publishing container images, refer to the complete documentation in the Publisher Guide:

**📖 [Complete Tool Publishing Guide](../6-tools-models-agents/tools-publishing/d--create-validate-publish-tools-to-acr.md)**

This detailed guide covers:

- **Prerequisites and Environment Setup**
- **Building Docker Images from Dockerfiles**
- **Local Testing and Validation**
- **Azure Container Registry Configuration**
- **Image Tagging and Publishing**
- **Post-Publication Verification**
- **Troubleshooting Common Issues**

> **💡 Tip**: The Publisher Guide provides the complete technical details for image creation, while this User Guide focuses on when and why you need to perform these steps.

## Validation and Next Steps

### Verify Your Tool Image is Ready

After building and publishing (or confirming availability), ensure your tool image is accessible:

```bash
# Verify the image exists in ACR
az acr repository show --name <your-acr-name> --repository <tool-name>

# Test pull from ACR
docker pull <your-acr-login-server>/<tool-name>:latest
```

## Additional Resources

- **[Azure Container Registry Documentation](https://docs.microsoft.com/en-us/azure/container-registry/)**
- **[Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)**
- **[Microsoft Discovery Tool Development Guidelines](../6-tools-models-agents/tools-publishing/)**
