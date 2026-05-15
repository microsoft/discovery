# Create, Validate, and Publish Tools to Azure Container Registry

This section covers the complete process of building, validating, and publishing your tool container images to Azure Container Registry (ACR) after you have created the Dockerfile following the [Docker file generation guide](./c--generate-docker-file.md).

## Overview

Once your Dockerfile and supporting scripts are ready, you need to build the container image, perform thorough validation testing, and publish it to Azure Container Registry for use in the Microsoft Discovery platform.

## Prerequisites

Before proceeding with container image creation and publishing, ensure you have:

### Required Tools and Access

1. **Docker Environment**
   - Docker Desktop or Docker Engine running
   - Sufficient disk space (minimum 10GB free)
   - Network access for downloading base images

2. **Azure Access**
   - Azure CLI installed and configured (`az --version`)
   - Active Azure subscription with appropriate permissions
   - Access to an Azure Container Registry instance

3. **Authentication Setup**
   - Logged into Azure CLI: `az login`
   - ACR login configured: `az acr login --name <registry-name>`

### Required Permissions

Ensure your Azure account has the following permissions:

- **AcrPush** role on the target Azure Container Registry
- **Contributor** role on the resource group (if creating new ACR)
- **Reader** role on the subscription for resource discovery

## Building the Docker Image

Once you've created your Dockerfile (or if you're using the existing one in the molToolkit directory), you can build and test your Docker image locally. This ensures that your containerized tool works as expected before publishing it to a container registry.

Navigate to the directory containing your Dockerfile and run:

```bash
# Build the image with a tag
docker build -t moltoolkit:latest .
```

## Testing the Docker Image Locally

To test your Docker image locally, you'll need to:

1. Navigate to the tool directory
2. Run the container with mounted volumes
3. Validate the output

The `molToolkit` directory contains:

- `app/` - Contains Python modules for molecular analysis
- `Dockerfile` - Container definition
- `MolToolkit-tool-definition.yaml` - Tool configuration
- `MolToolkit-agent-definition.yaml` - Agent configuration

### Running molToolkit Tests

> **Note**: The `-it` flags require an interactive terminal (TTY). For scripted or CI/CD environments, omit the `-it` flags and use `--rm` only.

```bash
# Navigate to the molToolkit directory if you're not already there
cd 6-solutions/tools-and-models/molToolkit

# Test SMILES validation
docker run --rm \
  -v "$(pwd)/input:/input" \
  -v "$(pwd)/output:/output" \
  moltoolkit:latest \
  python -c "from molecular_utils import validate_smiles; print(validate_smiles('CCO'))"

# Test functional group identification
docker run --rm \
  moltoolkit:latest \
  python -c "from mol_functional_groups import identify_functional_groups; print(identify_functional_groups('c1ccccc1O'))"

# Test conformer generation
docker run --rm \
  moltoolkit:latest \
  python -c "from get_low_energy_conformer import get_low_energy_conformer; mol, xyz = get_low_energy_conformer('CCO'); print(xyz)"
```

### Running with Custom Python Scripts

You can also run custom Python scripts using the molToolkit environment:

```bash
# Create a test script
echo 'from molecular_utils import calculate_molecular_weight, calculate_logp
smiles = "CCO"
print(f"MW: {calculate_molecular_weight(smiles)}")
print(f"LogP: {calculate_logp(smiles)}")' > /tmp/test_script.py

# Run the custom script
docker run --rm \
  -v "/tmp/test_script.py:/app/test_script.py" \
  moltoolkit:latest \
  python /app/test_script.py
```

## Prepare for Azure Container Registry Publishing

### Configure Azure Container Registry

```bash
# Set registry variables
ACR_NAME="<your-acr-name>"
RESOURCE_GROUP="<your-resource-group>"
LOCATION="<your-location>"

# Create ACR if it doesn't exist
az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $ACR_NAME \
  --sku Standard \
  --location $LOCATION \
  --admin-enabled true

# Get ACR login server
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --query loginServer --output tsv)
echo "ACR Login Server: $ACR_LOGIN_SERVER"
```

### Authenticate with ACR

```bash
# Using Azure CLI (recommended)
az acr login --name $ACR_NAME

# Verify authentication
az acr repository list --name $ACR_NAME --output table
```

## Tag and Push Images to ACR

### Tag Images for ACR

```bash
# Tag the image for ACR
docker tag <tool-name>:latest $ACR_LOGIN_SERVER/<tool-name>:latest
docker tag <tool-name>:latest $ACR_LOGIN_SERVER/<tool-name>:v1.0.0

# Verify tags
docker images | grep $ACR_LOGIN_SERVER
```

### Push Images to ACR

```bash
# Push latest tag
echo "Pushing latest tag..."
docker push $ACR_LOGIN_SERVER/<tool-name>:latest

# Push version tag
echo "Pushing version tag..."
docker push $ACR_LOGIN_SERVER/<tool-name>:v1.0.0

# Verify push success
az acr repository show --name $ACR_NAME --repository <tool-name>
az acr repository show-tags --name $ACR_NAME --repository <tool-name> --output table
```

## Post-Publication Validation

### Verify ACR Repository

```bash
# List repositories in ACR
az acr repository list --name $ACR_NAME --output table

# Show repository details
az acr repository show --name $ACR_NAME --repository <tool-name>

# List all tags
az acr repository show-tags --name $ACR_NAME --repository <tool-name> --output table

# Show manifest details
az acr repository show-manifests --name $ACR_NAME --repository <tool-name> --output table
```

### Test Pull and Run from ACR

```bash
# Remove local images to test ACR pull
docker rmi <tool-name>:latest $ACR_LOGIN_SERVER/<tool-name>:latest

# Pull from ACR
docker pull $ACR_LOGIN_SERVER/<tool-name>:latest

# Test with sample data using molToolkit
cd 6-solutions/tools-and-models/molToolkit

docker run --rm \
  -v "$(pwd)/input:/input" \
  -v "$(pwd)/output:/output" \
  $ACR_LOGIN_SERVER/<tool-name>:latest \
  python -c "from molecular_utils import validate_smiles; print(validate_smiles('CCO'))"
```

## Next Steps

After successfully publishing your tool to ACR:

1. Proceed to [Tool Definition Creation](./e--create-tool-definition.md)
2. Review [Agent Definition Creation](../agents-publishing/a--create-agent-definition.md)

## Additional Resources

- [Azure Container Registry Documentation](https://docs.microsoft.com/en-us/azure/container-registry/)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Container Security Best Practices](https://docs.microsoft.com/en-us/azure/container-registry/container-registry-best-practices)
