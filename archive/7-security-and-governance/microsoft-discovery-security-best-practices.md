
# Security Best Practices for Microsoft Discovery Setup

This guide provides recommended security practices for designing and operating Microsoft Discovery environments. It covers access control, identity management, network configuration, storage security, service permissions, and data governance, with prescriptive examples. Following these principles helps ensure least privilege, defense in depth, and regulatory compliance.

## 1. Role-Based Access Control (RBAC)

**Best Practice:** Enforce *least privilege* by granting only the roles necessary for each persona, workload, or service principal. Avoid assigning broad roles (e.g., Owner or User Access Administrator) except for initial setup or emergency recovery.

**Avoid:**

- Owner or User Access Administrator (UAA) roles unless absolutely necessary.
- Broad Contributor assignments at subscription scope; instead, prefer fine-grained roles scoped to a resource group or resource.

**Example:**\
If a data engineer needs to upload data into Blob Storage, assign Storage Blob Data Contributor scoped to the target container. Do not assign Storage Account Contributor or Owner, which would allow them to change configurations or reassign access.

## 2. Managed Identity Usage

**Best Practice:** Use User-Assigned Managed Identities (UAMI) for workloads requiring access to Azure resources. This eliminates credential sprawl and enforces lifecycle separation between workloads and identities.

**Recommendations:**

- Prefer UAMIs over System-Assigned MIs for long-lived workloads.
- Assign only scoped roles needed for the workload.
- Rotate and review role assignments quarterly.

**Example:**\
Instead of embedding secrets in a script that writes simulation outputs to Blob Storage, create a UAMI and assign it:

- Storage Blob Data Contributor -- scoped only to the target storage account.
- ACRPull -- read-only access to container images in an ACR

This ensures secure, auditable, and revocable access.

## 3. Network Isolation

**Best Practice:** Segregate resources into dedicated subnets and VNets, and apply NSGs and private endpoints for isolation.

**Recommendations:**

- Place compute, storage in separate subnets.
- Use Azure Private Link or Service Endpoints to connect to PaaS services securely.
- Enforce inbound/outbound traffic restrictions via NSGs and Azure Firewall.

**Example Subnet Layout:**

- StorageSubnet → Discovery Storage access that allows access to ComputeSubnet.
- NodepoolSubnet → Supercomputer node pools restricted to HPC workloads.
- AKSSubnet → used by Supercomputer service, secured with network policies.

Delegate StorageSubnet to Microsoft.NetApp/volumes to ensure optimized I/O paths and prevent cross-service interference.

## 4. Storage Access Controls

**Best Practice:** Restrict access to Blob Storage through network rules, role assignments, and CORS.

**Recommendations:**

- Use Storage Firewall to allow only trusted VNets or IP ranges.
- Require Azure AD authentication instead of shared keys.
- Configure CORS policies with explicit origins and allowed methods.

**Example:**

- Permit access only from an IP range and DiscoveryVNet.
- CORS: allow GET and PUT only, from origin https://discovery.portal.microsoft.com

This enforces precise control and reduces the attack surface.

## 5. Data Lifecycle Governance

**Best Practice:** Implement strict data classification, promotion, and
retirement processes across Discovery datasets.

**Recommendations:**

- Use PreviewData to validate datasets before publishing.
- Require PromoteOutputsToDataAssets to move validated results into production datasets.
- Use UpdateDataDescription to enforce consistent metadata tagging.
- Enforce absolute storage paths (/mnt/data/validated/) to prevent path traversal or accidental overwrite.
- Apply metadata labels such as classification: confidential, retention:
  3 years, or regulatory: HIPAA where applicable.

**Example Workflow:**

1. Simulation outputs land in /mnt/data/staging/.
2. Analysts validate using PreviewData.
3. Approved results are promoted to /mnt/data/validated/ with metadata tags.
4. Expired data is automatically deleted by lifecycle policies, reducing compliance risk.
