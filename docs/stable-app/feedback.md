# Stable app feedback

Use the [Microsoft Discovery Discussions forum](https://techcommunity.microsoft.com/category/azure/discussions/microsoft-discovery-discussions)
for questions, bugs, ideas, and shared scenarios, following the repository's
[support guidance](../../SUPPORT.md). This proposal preserves the existing support
route; it doesn't enable GitHub Issues or establish an enterprise SLA.

## Include the app channel

Start the report with:

```text
Experience: Microsoft Discovery Stable app
App version:
Operating system and architecture:
Selected model and agent, if relevant:
Goal:
Steps to reproduce:
Expected result:
Actual result and exact error:
Does it reproduce in a fresh project/session?
```

Use the version shown by the app or the installer, not the current redirect
name. For indexing problems, include file format, approximate collection size,
document count, and whether the content contains scans, tables, or images.
For tool problems, identify HTTP, stdio, or Skills Folder and the relevant
runtime requirements, without sharing secrets.

## Provide safe evidence

Use small, non-sensitive sample files where possible. Redact credentials,
authorization codes, private paths, research data, and personal information
from screenshots and logs. Review recordings before posting.

Distinguish these outcomes in the report:

- The file is attached, but its contents aren't readable.
- The bookshelf exists, but the expected document isn't retrieved.
- The tool appears in a list, but invocation fails.
- A molecular file is generated, but no preview appears.

Preview-specific `dx doctor` commands and log paths aren't established Stable
diagnostics. Don't assume they apply to this release.

For security vulnerabilities, use [SECURITY.md](../../SECURITY.md), not a public
Discussion or issue.
