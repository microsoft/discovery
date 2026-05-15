# Virtual Networks and Subnets for Microsoft Discovery

This guide explains how to create and configure virtual networks and subnets that are required for Microsoft Discovery infrastructure components including Storage, AKS, and Supercomputer nodepool resources.

## Overview

Virtual networks and subnets are fundamental networking components that provide secure communication between Microsoft Discovery resources. All Microsoft Discovery resources must be deployed within a properly configured virtual network to ensure:

- Secure communication between components
- Network isolation and segmentation
- Compliance with security requirements
- Optimal performance and connectivity

## Prerequisites

Before creating virtual networks and subnets, ensure you have:

- An active Azure subscription with Microsoft Discovery resource provider registered
- Sufficient permissions to create networking resources (Network Contributor role or higher)
- Understanding of your organization's network requirements and IP addressing scheme
- Familiarity with Azure networking concepts

## Virtual Network Requirements

Microsoft Discovery requires a virtual network with the following specifications:

### Address Space

- **Minimum CIDR**: `/24` (256 IP addresses)
- **Recommended CIDR**: `/16` or `/20` depending on scale requirements
- **Private IP ranges**: Use RFC 1918 private address spaces:
  - `10.0.0.0/8` (10.0.0.0 - 10.255.255.255)
  - `172.16.0.0/12` (172.16.0.0 - 172.31.255.255)
  - `192.168.0.0/16` (192.168.0.0 - 192.168.255.255)

### Required Subnets

You need to create separate subnets for different Microsoft Discovery components:

1. **Storage Subnet** - For Microsoft Discovery Storage resources
2. **Supercomputer Subnet** - For Supercomputer and node pools
3. **AKS Subnet** - For AKS cluster (optional, can share with supercomputer subnets)
4. **Workspace Subnet** - For Workspace resources to directly leverage data handling functions. You can use the subnet name `workspaceSubnet`

## Step-by-Step Guide

### Step 1: Create a Virtual Network

#### Using Azure Portal

1. Sign in to the [Azure Portal](https://portal.azure.com)
2. Search for "Virtual networks" and select it from the results
3. Click "Create" to start creating a new virtual network
4. Configure the basic settings:
   - **Subscription**: Select your subscription
   - **Resource Group**: Choose existing or create new (e.g., `contoso-discovery-rg`)
   - **Name**: Enter a descriptive name (e.g., `contoso-research-vnet-prod`)
   - **Region**: Choose the same region where you plan to deploy Microsoft Discovery resources

5. Configure IP addresses:
   - **IPv4 address space**: Enter your chosen CIDR block (e.g., `10.0.0.0/16`)
   - Add subnets as described in Step 2 below

6. Review and create the virtual network

#### Using Azure CLI

```azurecli
# Create resource group (if needed)
az group create --name contoso-discovery-rg --location eastus

# Create virtual network
az network vnet create \
  --resource-group contoso-discovery-rg \
  --name contoso-research-vnet-prod \
  --address-prefix 10.0.0.0/16 \
  --location eastus
```

### Step 2: Create Required Subnets

Create the following subnets within your virtual network:

#### Storage Subnet

This subnet will host Microsoft Discovery Storage resources.

**Using Azure Portal:**

1. Navigate to your virtual network in the Azure Portal
2. Select "Subnets" from the left menu
3. Click "Add subnet"
4. Configure:
   - **Name**: `contoso-research-subnet-storage`
   - **Subnet address range**: `10.0.1.0/24`
   - **Service endpoints**: Enable for `Microsoft.Storage` if using Azure Storage
   - **Subnet delegation**: Select `Microsoft.NetApp/volumes` if using Azure NetApp Files

**Using Azure CLI:**

```azurecli
az network vnet subnet create \
  --resource-group contoso-discovery-rg \
  --vnet-name contoso-research-vnet-prod \
  --name contoso-research-subnet-storage \
  --address-prefixes 10.0.1.0/24 \
  --delegations Microsoft.NetApp/volumes
  --service-endpoints Microsoft.Storage
```

#### Supercomputer Nodepools Subnet

This subnet will host Supercomputer and node pool resources.

**Using Azure Portal:**

1. Follow the same steps as above with these configurations:
   - **Name**: `contoso-research-subnet-supercomputer`
   - **Subnet address range**: `10.0.2.0/24`
   - **Service endpoints**: Enable for `Microsoft.Storage`, `Microsoft.KeyVault`

**Using Azure CLI:**

```azurecli
az network vnet subnet create \
  --resource-group contoso-discovery-rg \
  --vnet-name contoso-research-vnet-prod \
  --name contoso-research-subnet-supercomputer \
  --address-prefixes 10.0.2.0/24 \
  --service-endpoints Microsoft.Storage
```

#### AKS Subnet

Create a separate subnet for AKS resources.

**Using Azure Portal:**

- **Name**: `contoso-research-subnet-aks`
- **Subnet address range**: `10.0.3.0/24`

**Using Azure CLI:**

```azurecli
az network vnet subnet create \
  --resource-group contoso-discovery-rg \
  --vnet-name contoso-research-vnet-prod \
  --name contoso-research-subnet-aks \
  --address-prefixes 10.0.3.0/24
  --service-endpoints Microsoft.Storage
```

#### Workspace Subnet

This subnet will be used for Azure Functions used for handling data.

**Using Azure Portal:**

1. Navigate to your virtual network in the Azure Portal
2. Select "Subnets" from the left menu
3. Click "Add subnet"
4. Configure:
   - **Name**: `workspaceSubnet`
   - **Subnet address range**: `10.0.4.0/24`
   - **Service endpoints**: Enable for `Microsoft.Storage` if using Azure Storage
   - **Subnet delegation**: Select `Microsoft.App/environments` 

**Using Azure CLI:**

```azurecli
az network vnet subnet create \
  --resource-group contoso-discovery-rg \
  --vnet-name contoso-research-vnet-prod \
  --name workspaceSubnet \
  --address-prefixes 10.0.4.0/24 \
  --delegations Microsoft.App/environments
  --service-endpoints Microsoft.Storage
```

### Step 3: Configure Network Security Groups (NSGs)

Create and configure Network Security Groups to control traffic flow:

#### Create NSG for Storage Subnet

**Using Azure CLI:**

```azurecli
# Create NSG
az network nsg create \
  --resource-group contoso-discovery-rg \
  --name contoso-research-nsg-storage

# Add inbound rule for NFS (if using Azure NetApp Files)
az network nsg rule create \
  --resource-group contoso-discovery-rg \
  --nsg-name contoso-research-nsg-storage \
  --name AllowNFS \
  --protocol Tcp \
  --priority 100 \
  --source-address-prefixes 10.0.0.0/16 \
  --destination-port-ranges 2049 \
  --access Allow \
  --direction Inbound

# Associate NSG with subnet
az network vnet subnet update \
  --resource-group contoso-discovery-rg \
  --vnet-name contoso-research-vnet-prod \
  --name contoso-research-subnet-storage \
  --network-security-group contoso-research-nsg-storage
```

#### Create NSG for Supercomputer Subnet

```azurecli
# Create NSG
az network nsg create \
  --resource-group contoso-discovery-rg \
  --name contoso-research-nsg-supercomputer

# Add inbound rules for Kubernetes API server
az network nsg rule create \
  --resource-group contoso-discovery-rg \
  --nsg-name contoso-research-nsg-supercomputer \
  --name AllowKubernetesAPI \
  --protocol Tcp \
  --priority 100 \
  --source-address-prefixes 10.0.0.0/16 \
  --destination-port-ranges 443 6443 \
  --access Allow \
  --direction Inbound

# Associate NSG with subnet
az network vnet subnet update \
  --resource-group contoso-discovery-rg \
  --vnet-name contoso-research-vnet-prod \
  --name contoso-research-subnet-supercomputer \
  --network-security-group contoso-research-nsg-supercomputer
```

## Integration with Microsoft Discovery Resources

Once your virtual network and subnets are configured, you can use them when creating Microsoft Discovery resources:

### Storage Resource

- Select the **Storage subnet** during Microsoft Discovery Storage creation
- Ensure the subnet has appropriate delegation for your storage type

### Supercomputer Resource

- Select the **Supercomputer subnet** during Supercomputer creation
- Use the same subnet for associated node pools

### AKS Cluster

- Can use any subnet, but typically the **AKS subnet** or **Supercomputer subnet**

## Additional Resources

- [Azure Virtual Network Documentation](https://learn.microsoft.com/azure/virtual-network/)
- [Azure Network Security Groups](https://learn.microsoft.com/azure/virtual-network/network-security-groups-overview)
- [Azure NetApp Files Network Planning](https://learn.microsoft.com/azure/azure-netapp-files/azure-netapp-files-network-topologies)
