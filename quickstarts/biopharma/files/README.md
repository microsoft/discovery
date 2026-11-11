# BioPharma files

Use these **original files with the full [v0.11 guide](../Quick-Start-BioPharma%20LeadGen%20v0.11.md)**.
Download the six runtime files into the same new local folder as the guide.
They are copied unchanged from the prepared CDK handoff, not reconstructed
from an inventory. Do not substitute the earlier timed snapshot.

| Original filename | Purpose | Repository download |
| --- | --- | --- |
| `cdk_operational_bundle_v1.zip` | Small launcher bundle, 50,301 bytes | [Download](cdk_operational_bundle_v1.zip) |
| `cdk_operational_bundle_v1.sha256` | Exact checksum for the small ZIP | [Download](cdk_operational_bundle_v1.sha256) |
| `cdk_operational_bundle_v1_manifest.csv` | Original member paths, sizes and hashes | [Download](cdk_operational_bundle_v1_manifest.csv) |
| `cdk_operational_bundle_v1_validation.json` | Original handoff verification record | [Download](cdk_operational_bundle_v1_validation.json) |
| `cdk_non_md_deliverables.zip` | Exact frozen scientific snapshot, 168,396,900 bytes | **Local copy staged; public release download not published yet** |
| `cdk_non_md_deliverables.sha256` | Exact checksum for the large ZIP | [Download](cdk_non_md_deliverables.sha256) |

The large ZIP's SHA-256 is
`bfc939735a574ccc2375ae9808e9242fb79efc545d5b3f314cc38e5d0cefa076`.
Its 168,396,900 bytes exceed GitHub's 100 MiB limit for a normal Git file;
this is a repository storage limit, not a download-length limit. The exact ZIP
can be offered as a versioned repository-release download once publication is
approved. There is no fabricated link while that upload is pending.

## What is inside the small ZIP?

The original `workflow.py`, `profile.json`, `launch.ps1`, `acceptance.py`,
offline guard, tests, manifest and **validation folder**. Reference receipts
and stage logs in that validation folder remain inside the exact archive.
Unpacking it makes those files appear, just as in the local CDK-demo project.
Nothing inside the ZIP was edited, and the large ZIP is not unpacked by this README.

## Distribution status

These small files and guide are prepared as repository content. Exact large
files and an all-in-one author review download are staged locally. Public
archive publication and the new end-to-end test are still outstanding. The
source snapshot contains MIT campaign-code and source-specific data notices;
retain them all. Do not infer rights for unrelated papers or private logs.