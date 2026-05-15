# Microsoft Discovery Resource Provider Registration

This guide provides comprehensive instructions for registering the Microsoft Discovery Resource Provider (`Microsoft.Discovery`) in your Azure subscription. Resource provider registration is a prerequisite for using Microsoft Discovery services and creating Microsoft Discovery resources.

## What is a Resource Provider?

An Azure resource provider is a set of REST operations that support functionality for a specific Azure service. The Microsoft Discovery service consists of a resource provider named `Microsoft.Discovery`. This resource provider defines REST operations for managing Discovery workspaces, storages, supercomputers, and other Discovery resources.

The resource provider defines the Azure resources you can deploy to your account. Resource types in Microsoft Discovery follow the format: `Microsoft.Discovery/{resource-type}`, such as:

- `Microsoft.Discovery/workspaces`
- `Microsoft.Discovery/storages`
- `Microsoft.Discovery/supercomputers`
- `Microsoft.Discovery/bookshelves`

## Prerequisites

Before registering the Microsoft Discovery resource provider, ensure you have:

- An active [Azure subscription](https://portal.azure.com/)
- The Azure subscription has been **enabled by the Microsoft Discovery team** to use the Microsoft.Discovery resource provider
- Sufficient permissions to register resource providers in your Azure subscription
- One of the following roles assigned to your account:
  - **Contributor** role (or higher) on the subscription
  - **Owner** role on the subscription
  - Custom role with `/register/action` operation permissions for resource providers

> **Important**: Registration configures your subscription to work with the Microsoft Discovery resource provider. Only register resource providers when you're ready to use them to maintain least privileges within your subscription.

## Registration Methods

You can register the Microsoft Discovery resource provider using any of the following methods:

### Method 1: Azure Portal

#### Step-by-step Instructions

1. **Sign in to the Azure Portal**
   - Navigate to [https://portal.azure.com](https://portal.azure.com)
   - Sign in with your Azure account credentials

2. **Navigate to Subscriptions**
   - In the Azure portal menu, search for "Subscriptions"
   - Select **Subscriptions** from the available options

3. **Select Your Subscription**
   - From the list of subscriptions, select the subscription where you want to register Microsoft Discovery
   - Ensure this is the subscription that has been enabled by the Microsoft Discovery team

4. **Access Resource Providers**
   - In the left-hand menu under **Settings**, select **Resource providers**

5. **Find Microsoft Discovery Resource Provider**
   - In the search box, type "Microsoft.Discovery"
   - Locate `Microsoft.Discovery` in the list of resource providers

6. **Register the Resource Provider**
   - Select the `Microsoft.Discovery` resource provider
   - Click the **Register** button
   - The registration status will change from "Not Registered" to "Registering" and then to "Registered"

> **Note**: Registration may take a few minutes to complete. The process is done individually for each supported region. You don't need to wait for all regions to complete before creating resources.

This process needs to be repeated for all these resource providers:

1. `Microsoft.Network`
1. `Microsoft.Compute`
1. `Microsoft.Storage`
1. `Microsoft.ManagedIdentity`
1. `Microsoft.AlertsManagement`
1. `Microsoft.Authorization`
1. `Microsoft.CognitiveServices`
1. `Microsoft.ContainerInstance`
1. `Microsoft.ContainerRegistry`
1. `Microsoft.ContainerService`
1. `Microsoft.DocumentDB`
1. `Microsoft.Features`
1. `Microsoft.KeyVault`
1. `Microsoft.MachineLearningServices`
1. `Microsoft.NetApp`
1. `Microsoft.OperationalInsights`
1. `Microsoft.ResourceGraph`
1. `Microsoft.Search`
1. `Microsoft.Web`
1. `Microsoft.insights`
1. `Microsoft.Resources`

#### Verification

- Refresh the resource providers page
- Confirm that `Microsoft.Discovery` shows a status of **Registered**

### Method 2: Azure CLI

If you prefer using the command line, you can register the resource provider using Azure CLI:

#### CLI Prerequisites

- Azure CLI installed ([Installation guide](https://learn.microsoft.com/cli/azure/install-azure-cli))
- Authenticated to Azure CLI (`az login`)

#### Command

```azurecli
az provider register --namespace Microsoft.Discovery
```

#### Verify Registration

```azurecli
az provider show --namespace Microsoft.Discovery --query "registrationState"
```

This command should return `"Registered"` once the registration is complete.

#### List All Resource Providers

To see all resource providers and their registration status:

```azurecli
az provider list --query "[].{Provider:namespace, Status:registrationState}" --out table
```

### Method 3: Azure PowerShell

You can also use Azure PowerShell to register the resource provider:

#### PowerShell Prerequisites

- Azure PowerShell module installed
- Authenticated to Azure PowerShell (`Connect-AzAccount`)

#### PowerShell Command

```powershell
Register-AzResourceProvider -ProviderNamespace Microsoft.Discovery
```

#### PowerShell Verify Registration

```powershell
Get-AzResourceProvider -ProviderNamespace Microsoft.Discovery
```

### Method 4: REST API

For programmatic registration, you can use the Azure REST API:

#### API Endpoint

```http
POST https://management.azure.com/subscriptions/{subscription-id}/providers/Microsoft.Discovery/register?api-version=2021-04-01
```

#### Headers

- `Authorization: Bearer {access-token}`
- `Content-Type: application/json`

## Post-Registration Steps

After successfully registering the Microsoft Discovery resource provider:

1. **Verify Registration Status**
   - Confirm the registration status shows as "Registered" in the Azure portal
   - Or use CLI/PowerShell commands to verify

2. **Check Available Resource Types**
   - Review the available Microsoft Discovery resource types in your subscription
   - Go to top "Search bar" and type "Microsoft Discovery", you should be able to see all Microsoft Discovery Resource types

3. **Proceed with Resource Creation**
   - You can now create Microsoft Discovery resources such as:
     - Microsoft Discovery Workspaces
     - Microsoft Discovery Projects
     - Microsoft Discovery Supercomputers
     - Microsoft Discovery Bookshelves
     - Microsoft Discovery Data Containers
     - Microsoft Discovery Storages
     - Microsoft Discovery Tools
     - Microsoft Discovery Models
     - Microsoft Discovery Agents
     - Microsoft Discovery Workflows

## Related Resources

- [Azure Resource Providers and Types](https://learn.microsoft.com/azure/azure-resource-manager/management/resource-providers-and-types)
- [Microsoft Discovery Quickstart Guide](../../2-getting-started/quickstart.md)
