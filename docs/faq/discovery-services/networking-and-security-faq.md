[← Microsoft Discovery services FAQ](README.md)

# Microsoft Discovery networking and security FAQ

This article answers common questions about the Microsoft Discovery networking and security model, including how services are secured with private endpoints and the Network Security Perimeter (NSP), what networking the customer must provide, and how the portal and backend endpoints are exposed.

## Endpoint exposure

### Are services exposed publicly or privately?

Most services are private and use private endpoints (PEP), a Network Security Perimeter (NSP), and virtual network (VNet) injection. The current exception is AKS, which exposes a public IP today; a fix is in progress to support user-defined routes (UDRs) and remove that public exposure.

### Is the Discovery Studio portal UI public or private?

The Discovery Studio portal UI is publicly accessible over the internet, similar to the Azure portal, and is secured with Microsoft Entra ID authentication. Backend data is not exposed through public endpoints.

### Are workspace or backend endpoints public?

No. All backend resources in the managed resource groups (MRGs) are private and aren't directly accessible from outside the environment.

### Is inbound access from Microsoft into the environment required?

No explicit inbound access is required. All interactions occur within Container Apps, private endpoints, and internal Azure services.

### Do I need internal or external DNS entries for the Discovery Studio portal URL?

No. The Microsoft Discovery Studio portal URL is publicly available, so no internal or external DNS entries are required for it.

## Network Security Perimeter (NSP) and private endpoints

### Does the NSP cover all child services, or only those not secured by private endpoints?

The NSP covers the public-endpoint PaaS resources—such as Storage, Azure Cosmos DB, AI Foundry, SQL Server, Log Analytics, and AI Search—and is auto-associated through a DeployIfNotExists policy. It does not cover every MRG resource. Resources that are PEP-secured or that aren't NSP-capable are excluded. Many resources are secured by *both* NSP and a private endpoint (for example, the Agent Cosmos DB, Workspace Storage Account, Bookshelf SQL, and AI Search).

### How is Azure Key Vault secured if it doesn't use a private endpoint?

Key Vault is secured by the NSP perimeter plus the Key Vault firewall IP allow-list (deny-by-default), with Microsoft Entra ID / managed-identity authentication over TLS on the Azure backbone.

### Can Service Endpoints be used for Key Vault and other services that don't support private endpoints?

These services are protected through the NSP perimeter combined with resource firewalls and managed-identity authentication rather than Service Endpoints. Key Vault, for example, relies on NSP plus its firewall IP allow-list and Entra ID auth.

## Networking configuration the customer provides

### Who creates the networking resources?

The customer pre-creates the networking and supporting resources in the primary resource group, including the VNet, subnets, storage accounts, and a user-assigned managed identity (UAMI). A Bicep template is available to assist with this setup.

### What subnet structure is required?

The customer creates a VNet and multiple subnets (typically six), each dedicated to a Discovery component—for example, workspace, agent, search, private endpoint, supercomputer node pool, and AKS subnets.

### How is subnet sizing determined?

Sizing is driven by compute scale. Smaller workloads can use a smaller subnet (for example, /26), while larger workloads need a larger subnet (for example, /24 or larger). All supercomputer node pools share a single supercomputer-node-pool subnet, so plan additional capacity if you expect large or multiple node pools. See the [infrastructure and deployment FAQ](infrastructure-and-deployment-faq.md) for compute SKU and node-pool sizing details.

## Managed resource group topology

### Why is a separate MRG required for the internal load balancers?

The internal load balancers are auto-created and owned by the underlying platform services, so they live in their own platform-managed resource groups—`ME_` for the Container Apps managed environment and `MC_` for the AKS managed cluster.

## Customer policy compliance

### What happens if customer security policies block deployment?

Some environments enforce strict policies on public endpoints or storage account access. If a deployment fails because of such a policy, the Discovery team investigates and provides a fix where possible, or requests a policy change when necessary. The service aims to comply with customer security requirements, avoiding insecure access keys and adapting to policy constraints. Validate policies early to avoid late-stage failures.

## Related content

- [Microsoft Discovery infrastructure and deployment FAQ](infrastructure-and-deployment-faq.md)
- [Microsoft Discovery knowledge retrieval FAQ (Bookshelf, GraphRAG, and Azure AI Search)](bookshelf-and-knowledge-retrieval-faq.md)
