# Microsoft Discovery — Data Encryption at Rest



# Purpose
Microsoft Discovery protects customer and system data by encrypting all data at rest using Azure platform's native encryption capabilities. This control helps safeguard data against unauthorized access and supports Microsoft security, privacy, and Product Launch Readiness (PLR) requirements.

## Data Encrypted at Rest
Data persisted by Microsoft Discovery is encrypted prior to being written to storage. Encryption at rest is applied automatically and transparently, requiring no customer action or configuration. This includes both customer-provided data and system-generated metadata stored by the service.

## Key Management

- **Default:** Keys are managed and rotated by Azure key management infrastructure
- **Controls:** Protected by Azure‑managed hardware and software security controls

## Access Controls & Isolation

- Encryption keys are not accessible to service operators, engineers, or support
- Access to encrypted data is governed by:
  - Azure Active Directory authentication
  - Role‑based access control (RBAC)
  - Managed identities for service‑to‑service communication

Design follows least‑privilege and separation‑of‑duties principles.

## Customer Transparency

- Encryption at rest is enabled by default for all Microsoft Discovery tenants
- No customer configuration is required

## Shared Responsibility & Limitations
Encryption at rest does not mitigate risks from:

- Compromised credentials
- Misconfigured access controls
- Application‑level vulnerabilities

Customers remain responsible for identity, access governance, and securing client‑side data before ingestion.