[← Microsoft Discovery services FAQ](README.md)

# Microsoft Discovery infrastructure and deployment FAQ

This article answers common questions about deploying Microsoft Discovery infrastructure into a customer subscription, including the resource model, compute and node-pool CPU families, identity and storage, supported regions, cost, availability, and how to enable a subscription.

## Deployment architecture and resource model

### What resources are deployed when Microsoft Discovery is provisioned?

Provisioning a Discovery workspace automatically creates multiple resources across several managed resource groups (MRGs), including compute (AKS), storage, Azure Cosmos DB, and Azure Container Apps. Separate MRGs are created for the workspace, the Bookshelf, and the supercomputer. Additional system-created MRGs may also appear (for example, for AKS and Container Apps).

### Where are these resources deployed?

All resources are deployed within the *customer subscription*, not a Microsoft-managed subscription. You'll see a primary resource group (the control plane) and multiple managed resource groups (the data plane).

### Do customers have access to the managed resource groups?

Customers have read-only (reader) visibility into the MRGs. Once deny assignments are enforced, write and modify operations on the managed resources are blocked. This model is similar to Azure Databricks.

### Is Azure Container Registry (ACR) required?

No—ACR is optional. Storage accounts are already included in the deployment templates. ACR is only needed when you bring your own tools (container images) to run on the supercomputer.

### Do I need Azure Machine Learning, Azure AI Search, and the Supercomputer together?

Not necessarily—the combination depends on the workload. Each serves a distinct role: Azure ML for model workflows, Azure AI Search for retrieval, and the Supercomputer for containerized tool execution. Use only the components your scenario requires.

## Compute and the supercomputer

### What is the "supercomputer" abstraction?

The supercomputer is currently implemented using AKS, where AKS clusters and their node pools (including VMSS, load balancers, and public IPs) are deployed into dedicated MRGs. It's abstracted conceptually so other compute backends can be supported in the future.

### How are tools executed?

Tools are not persistent resources. They are instantiated dynamically on the supercomputer when needed.

### Which node-pool CPU families are available for production deployments?

There's no small fixed list. A supercomputer is an AKS cluster whose node pools accept any region-available, quota-approved Azure VM CPU family. For the **system** node pool the requirement is limited (for example, `Standard_D4s_v6`, or a v5-family equivalent). For the **compute** node pool you can use any CPU family available in the region you plan to deploy in.

### How do I check that I have enough quota for the system node pool CPU family (Standard_D4s_v5 / Standard_D4s_v6) before deploying the Supercomputer?

The Supercomputer's system node pool requires capacity for the DSv5/DSv6 CPU family so ensure you have appropriate quota using the steps below:

1. In the Azure portal, go to your **Subscription**.
2. In the left navigation, select **Settings → Usage + quotas**.
3. Search for **"Standard DSv"**—this returns the **DSv5** and **DSv6** CPU family entries, which cover `Standard_D4s_v5` and `Standard_D4s_v6`.
4. Confirm the available vCPU quota is sufficient, and request an increase if needed.

Make sure you check quota for the **specific region** you plan to deploy in, since quota is allocated per region.

### Are there GPU or specialty compute SKUs to consider?

GPU SKU requirements depend on the tool you intend to run. You can use any GPU SKU that's available in your region and well tested with your tools.

### Do the chosen CPU families affect subnet sizing or IP requirements?

All node pools share a single supercomputer-node-pool subnet. A /24 is a common starting point, but you may need more subnet capacity depending on your compute capacity and the number or size of node pools. See the [networking and security FAQ](networking-and-security-faq.md) for the full subnet structure.

## Identity and access

### What type of managed identity is used?

The customer provides a user-assigned managed identity (UAMI). The service also creates internal identities inside the MRGs for internal operations.

## Data storage and access

### How is storage accessed—keys or identity?

Storage uses service-managed access patterns within the MRG. The service aims to comply with customer security requirements and avoid insecure access keys, adapting to policy constraints through platform changes when required.

## Azure service dependencies and allow-listing

### Are the services Generally Available, or are any in preview?

All services used by Discovery are Generally Available (GA).

### Which dependencies must be allow-listed?

Most required Azure services are typically already permitted. **Azure Container Apps is a mandatory dependency and must be allow-listed**—it can't be replaced with AKS. In restricted environments, both Container Apps and AKS must be allow-listed. Container Apps is the core runtime for workspace services, Bookshelf indexing, and query execution.

## Regions and availability

### Which regions are supported?

The control plane is currently limited to East US, Sweden Central, and UK South.

### Can the data plane be deployed in other regions?

Yes. MRG resources can be deployed in regions other than the control plane region. If the customer restricts the allowed regions, plan cross-region deployment and watch for potential quota limitations.

### I have sufficient quota, but East US has no DSv-family nodes available in any size. What should I do?

Checking quota and capacity for the required CPU and model families should be one of the first steps when planning a Discovery deployment. If a required VM family isn't available in your preferred region, use Discovery's **cross-region deployment** support. In this case, the control plane resources are created in one of the supported Discovery regions (East US, Sweden Central, or UK South), while the underlying managed resource group (MRG) resources can be deployed in a different region that has the capacity you need.

This feature is still under test. If blocked, please reach out to the Product Group for the exact steps on how to enable this experience.

### Does cross-region deployment cause latency?

Cross-region deployment doesn't add significantly noticeable latency, because workflow execution times dominate the overall response time.

### Does Microsoft Discovery provide built-in backup or disaster recovery?

Microsoft strives to keep Azure services available, but unplanned outages can occur. Microsoft Discovery does not currently provide built-in automatic failover or disaster recovery. Customers who require higher availability and resiliency should deploy Microsoft Discovery across multiple regions and ensure that any stateful resources are appropriately replicated and/or backed up to meet their disaster-recovery requirements.

## Cost

### Who pays for the infrastructure?

The customer pays for all Azure infrastructure, because it's deployed in their subscription.

### What is the cost per interaction?

Messaging costs approximately $0.20 per message. This is small compared to the infrastructure cost, which is the primary expense.

## Deployment, demo, and enablement

### How do customers get access?

Access requires allow-listing the subscription through the internal approval process. Coordinate with the Discovery team to raise the allow-listing request so the subscription is tracked for future updates.

### Are templates and documentation available?

Yes. Bicep templates and quickstarts are available on Microsoft Learn, and Discovery is open source at [github.com/microsoft/discovery](https://github.com/microsoft/discovery).

### Do I need to redeploy the workspace to enable new features?

Some capabilities (for example, GitHub Copilot and agentic search features) require redeploying the workspace. Performing the redeployment before creating new projects shouldn't disrupt existing projects. See the [agents, models, and Foundry FAQ](agents-models-and-foundry-faq.md) for feature-enablement details.

## Related content

- [Microsoft Discovery networking and security FAQ](networking-and-security-faq.md)
- [Microsoft Discovery agents, models, and Foundry FAQ](agents-models-and-foundry-faq.md)
