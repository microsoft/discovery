# Known Limitations

This document outlines the current known limitations in Microsoft Discovery. These limitations are temporary and will be addressed in future releases.

## Investigation Chat History

Chat history within an investigation is not maintained. Each message is treated as new context. If you compute results and promote them as a data asset, in subsequent messages you must explicitly attach the data asset for context continuity.

> **Note:** This limitation will be addressed in the Discovery public preview release.

## Model Restrictions

Currently, **GPT-4o** is the only recommended model for use with Microsoft Discovery for Agents with heavy tool executions.

> **Note:** This restriction will be removed in the public preview release.

## Agent Instructions Encoding

Agent instructions must be UTF-8 compliant. Non-compliant instructions may cause unexpected behavior or failures.

> **Note:** Additional validations will be added by mid-February to block Agent creation with non-UTF-8 compliant instructions.

### Avoid Mojibake Characters

Mojibake refers to corrupted or misinterpreted characters caused by encoding mismatches. Watch out for these common issues:

| Corrupted Character | Correct Character |
|---------------------|-------------------|
| `â€™` | `'` (apostrophe) |
| `Ã©` | `é` (accented e) |
| `ï»¿` | (UTF-8 BOM issue) |

**Common causes of Mojibake:**

- UTF-8 text read as Latin-1/Windows-1252 encoding
- Copy-paste from Word, Outlook, PDF, or Microsoft Teams
- Instructions stored in one encoding but executed in another

**Best Practice:** Always verify your agent instructions are saved with UTF-8 encoding and avoid copy-pasting directly from rich-text applications.

## Direct Agent Queries

Currently, you cannot send questions directly to a specific agent. All queries must be routed through a workflow, even for simple tasks that only require a single agent's capabilities.

> **Note:** This restriction will be removed in the public preview release.

## Resource Group Deletion

Deleting an entire resource group containing Discovery resources is not currently supported. Discovery resources must be deleted individually in a specific order to avoid backreference issues.

### Resource Deletion Order

To avoid deletion failures due to backreferences, delete Discovery resources in the following order:

1. Investigations
2. Project
3. Workspace
4. Discovery Storage
5. Workflow
6. Knowledge Base
7. Bookshelf
8. Agent
9. Tools
10. Node Pool
11. Supercomputer
12. Data Asset
13. Data Container
14. Storage / VNETs

For more information on resource deletion, see the [FAQ](4-faq.md#in-what-order-should-discovery-resources-be-deleted).

## Knowledge Base Limitations

### Citations

Citations are not currently supported. 

> **Note:** This is a planned feature for future releases.

### Cross-Project Sharing

Bookshelves cannot be shared across projects. Each project must have its own dedicated Bookshelves and Knowledge Bases.

> **Note:** This is a planned feature for future releases.

### Knowledge Base Allocation

Each Bookshelf can only contain one Knowledge Base. However, Projects may contain many Bookshelves. 

> **Note:** This is a planned feature for future releases.

### Supported File Types for Indexing

PDF, CSV, TEXT, Word, PowerPoint, Excel

### Incremental Indexing

Incremental indexing is not currently supported. To update Knowledge Bases, you must delete them and re-index. 

> **Note:** This is a planned feature for future releases.

## Additional Resources

- [Troubleshooting Guide](5-troubleshooting.md)
- [FAQ](4-faq.md)
