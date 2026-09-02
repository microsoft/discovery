<!-- BEGIN MICROSOFT SECURITY.MD V0.0.9 BLOCK -->

## Security

Microsoft takes the security of our software products and services seriously, which includes all source code repositories managed through our GitHub organizations, which include [Microsoft](https://github.com/Microsoft), [Azure](https://github.com/Azure), [DotNet](https://github.com/dotnet), [AspNet](https://github.com/aspnet) and [Xamarin](https://github.com/xamarin).

If you believe you have found a security vulnerability in any Microsoft-owned repository that meets [Microsoft's definition of a security vulnerability](https://aka.ms/security.md/definition), please report it to us as described below.

## Reporting Security Issues

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them to the Microsoft Security Response Center (MSRC) at [https://msrc.microsoft.com/create-report](https://aka.ms/security.md/msrc/create-report).

If you prefer to submit without logging in, send email to [secure@microsoft.com](mailto:secure@microsoft.com). If possible, encrypt your message with our PGP key; please download it from the [Microsoft Security Response Center PGP Key page](https://aka.ms/security.md/msrc/pgp).

You should receive a response within 24 hours. If for some reason you do not, please follow up via email to ensure we received your original message. Additional information can be found at [microsoft.com/msrc](https://www.microsoft.com/msrc).

Please include the requested information listed below (as much as you can provide) to help us better understand the nature and scope of the possible issue:

  * Type of issue (e.g. buffer overflow, SQL injection, cross-site scripting, etc.)
  * Full paths of source file(s) related to the manifestation of the issue
  * The location of the affected source code (tag/branch/commit or direct URL)
  * Any special configuration required to reproduce the issue
  * Step-by-step instructions to reproduce the issue
  * Proof-of-concept or exploit code (if possible)
  * Impact of the issue, including how an attacker might exploit the issue

This information will help us triage your report more quickly.

If you are reporting for a bug bounty, more complete reports can contribute to a higher bounty award. Please visit our [Microsoft Bug Bounty Program](https://aka.ms/security.md/msrc/bounty) page for more details about our active programs.

## Preferred Languages

We prefer all communications to be in English.

## Policy

Microsoft follows the principle of [Coordinated Vulnerability Disclosure](https://aka.ms/security.md/cvd).

<!-- END MICROSOFT SECURITY.MD BLOCK -->

## Repository security process

Catalog changes pass through layered automated checks and maintainer review. The
detailed rule definitions and remediation guidance are in
[`docs/validation-rules.md`](docs/validation-rules.md) and
[`CONTRIBUTING.md`](CONTRIBUTING.md).

| Layer | Policy inventory |
| --- | --- |
| Trust boundary | PR validation runs trusted base-branch code against the proposed content; PR-supplied code is not executed with a write token. Workflow permissions are minimized, and untrusted values are passed through environment variables. |
| Structure and schemas | `STR-*`, `SCH-*`, `AS-*`, and `SKT-*` validate required files, JSON/YAML schemas, names, references, and starter-kit composition. Concrete schema nodes require a type or reference plus size, count, or range bounds; semantic strings use patterns or formats, and objects are closed or use bounded extension maps. `MET-*`, `DOC-*`, and `DEP-*` validate metadata, documentation, and dependency declarations. |
| Catalog content | `POL-004` and `POL-005` enforce description and README minimums; `POL-008`, `POL-009`, `POL-010`, `POL-011`, and `POL-012` restrict binaries, validate model weights, and block hidden artifacts, generated-registry edits, and deployer scratch data; `POL-014`, `POL-015`, `POL-016`, `POL-017`, `POL-018`, and `POL-019` govern base-image provenance and pinning, file types, small Markdown-referenced image safety, reachable public webpages, and mail-capable contact domains. `SKT-POL-001` requires new starter kits to be active. |
| Classification | `TAG-001` and `TAG-002` enforce the reviewed tag vocabulary and reserve CI-computed tag namespaces. |
| Security scanning | Verified-secret findings block PRs. Unverified secret candidates, CodeQL, DevSkim, and Microsoft Application Inspector results are report-only inputs for reviewers. |
| Review and merge | CODEOWNERS and branch protection require successful checks and human approval. Agent-removal checks protect active starter-kit references; generated registries are rebuilt and schema-validated by automation. |
| After merge | The weekly deep scan reruns all rules across the full catalog, scans container base images for vulnerabilities, checks webpage strings against URLhaus and PhishTank without visiting them, and opens an issue for regressions or provider failures. |

Policy configuration is review-controlled under [`.github/policy/`](.github/policy/):
approved base images, source-file allowlists, network validation limits, and tag
taxonomy. Exceptions require an expiring CODEOWNER-approved waiver; the ratchet
baseline records legacy findings but does not permit new violations.
