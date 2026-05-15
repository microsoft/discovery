# Resource Naming Guidelines for Microsoft Discovery

## Introduction

Microsoft Discovery platform has various resource types and some of them have dependencies with resources in other resource providers. Understanding resource naming constraints is essential to foster clarity, prevent conflicts, enable easier automation, and support governance and security.

This document provides a detailed specification of the resource naming gudielines applicable to all resource types within the Microsoft Discovery so you can make an informed decision while naming your resources to avoid deployment errors.

---

## General Naming Guidelines and Best Practices

- **Uniqueness:** Resource names must be unique within their scope (subscription, or resource group).
- **Predictability:** Naming patterns should be consistent, facilitating automation and integration.
- **Character Set:** Names must only use alphanumerical characters and shouldn’t start with a number.
- **Case Sensitivity:** Unless otherwise stated, resource names are case-insensitive but must be entered and stored in lower case for consistency.
- **Length Constraints:** Each resource type defines its own minimum and maximum length; exceeding those constraints will result in errors.
- **No Spaces or Special Characters:** Resource names cannot include whitespaces and special characters except `-` (hyphen) unless stated otherwise.
- **No Consecutive Separators:** Multiple dashes, underscores, or other separators must not appear consecutively.

---

## Resource naming convention for Managed Resource Groups (MRGs)

When certain Discovery resources are created, corresponding Managed Resource Groups (MRGs) are automatically provisioned. These MRGs host the service components required to support the functionality of those resources. The following naming conventions apply to these Managed Resource Groups:

| Resource Type | Naming Convention | Example |
| --- | --- | --- |
| Microsoft Discovery Workspace | mrg-dwsp-<customer-provided-name>-<random-generated-sequence (6 chars)> | mrg-dwsp-testWorkspace-abcdef |
| Microsoft Discovery Storage | mrg-dstr-<customer-provided-name>-<random-generated-sequence (6 chars)> | mrg-dstr-testStorage-acegik |
| Microsoft Discovery Bookshelf | mrg-dbksf-<customer-provided-name>-<random-generated-sequence (6 chars)> | mrg-dbksp-testBookshelf-lmnopqr |
| Microsoft Discovery Supercomputer | mrg-dscmp-<customer-provided-name>-<random-generated-sequence (6 chars)> | mrg-dscmp-testSC-abcxyz |

---

## Resource Specific Limits

### Workspace (also used as workspace endpoint sub-domain name)
- Permitted Characters: Lowercase letters (a-z), digits (0-9), hyphens (-)
- Length Requirements: 3 to 24 characters
- Pattern: Must start with a letter, may include digits, hyphens, and underscores, and must conclude with a letter or digit
- Examples: `workspace01`, `workspace-main`

### Project
- Permitted Characters: Lowercase letters, digits, and hyphens
- Length Requirements: 3 to 12 characters
- Pattern: Must start with a letter; dashes can be applied as word separators
- Examples: `ai-project`, `adhesives01`

### Storage
- Permitted Characters: Lowercase letters (a-z), digits (0-9), hyphens (-)
- Length Requirements: 3 to 24 characters
- Pattern: Must begin with a letter, may contain digits, dashes, and must end with a letter or digit
- Examples: `storage01`, `contoso-storage`

### Supercomputer
- Permitted Characters: Lowercase letters, digits, and dashes
- Length Requirements: 3 to 24 characters
- Pattern: Must start with a letter; dashes are allowed as separators, must end with a letter or digit
- Examples: `quantum-supercomputer`, `supercomputer01`

### NodePool
- Permitted Characters: Lowercase letters (a-z), digits (0-9), dashes (-)
- Length Requirements: 3 to 12 characters
- Pattern: Must start with a letter, may incorporate digits, dashes, and underscores, and must finish with a letter or digit
- Examples: `nodepool01`, `gpu-nodepool`

### Tool
- Permitted Characters: Uppercase or Lowercase letters, digits, and dashes
- Length Requirements: 3 to 24 characters
- Pattern: Names must begin with a letter; dashes are utilized as separators, must end with a letter or digit
- Examples: `adft-tool`, `mol-toolkit`

### Model
- Permitted Characters: Uppercase or Lowercase letters (a-z), digits (0-9), and dashes (-)
- Length Requirements: 3 to 24 characters
- Pattern: Must start with a letter, allow for digits, dashes, and end with a letter or digit
- Examples: `retrochimera-v2`, `syntheseus-model`

### Agent
- Permitted Characters: Uppercase or Lowercase letters, digits, and dashes
- Length Requirements: 3 to 24 characters
- Pattern: Must start and end with a letter; dashes can separate words
- Examples: `search-agent`, `crawler-agent`

### Workflow
- Permitted Characters: Uppercase or Lowercase letters (a-z), digits (0-9), dashes (-)
- Length Requirements: 3 to 24 characters
- Pattern: Must begin with a letter, can include digits, dashes, and end with a letter or digit
- Examples: `chemistry-workflow`, `etlWorkflow`

### Data Container
- Permitted Characters: Lowercase letters, digits, and dashes
- Length Requirements: 3 to 24 characters
- Pattern: Start and end with a letter, using dashes as optional word dividers
- Examples: `contoso-datacontainer`, `archivecontainer`

### Data Asset
- Permitted Characters: Lowercase letters (a-z), digits (0-9), dashes (-)
- Length Requirements: 3 to 24 characters
- Pattern: Commence with a letter, may include digits, dashes, and must conclude with a letter or digit
- Examples: `input-molecules-01`, `outputData`

### Investigation
- Permitted Characters: Lowercase letters, digits, and dashes
- Length Requirements: 1 to 20 characters
- Pattern: Must start and end with a letter; dashes serve as word separators
- Examples: `chemistry-investigation`, `anomaly-investigation`

---

## Internationalization and Localization

Resource names should use English terms and ASCII characters for maximum compatibility across systems and global regions. If localization is necessary, use a mapping table or metadata field rather than encoding localized names directly in the resource name.

---

## Compliance and Validation

All resource names must pass validation before creation or modification. Validation is performed via:
- Syntax checking (length, allowed characters, no consecutive separators, etc.)
- Uniqueness checking within the appropriate scope

Resource creation in Azure Portal or Studio will return explicit error messages in real-time when naming constraints are violated, please correct the input according to the specification.

---