# SiPhy — start here

Run **[QuickStart-Spec-to-RTL.md](QuickStart-Spec-to-RTL.md)**.
This is the complete v1.1 guide, with personal owner/contact identifiers
removed for publication. Its filename is made descriptive; scientific
instructions, prompts, results and checklist items are unchanged.

## 1. Get the supplied files

- The full QuickStart Markdown above.
- [Original scenario skill](skill%201.md), **unchanged**.
- The original [ship.tar](files/ship.tar), with its contents and checksum
  described under [Supporting files](#supporting-files) below.

All three supplied files are available on this branch. Download them into a
new short local folder, preserving their names. The complete tar is included
directly, not replaced by an asset inventory. Its presence does not complete
the remaining setup, reference-evidence or fresh-project validation work below.

## 2. Create a fresh Discovery project

Open/create a local project in that folder and start a new session. The v1.1
guide records parent model **`gpt-6.1-sol`**, not BioPharma's model. Verify current
availability; never silently substitute a model or assert all specialists share
the parent's effective settings.

Load the [shared runner](../../skills/quickstart-runner/README.md), attach the
full SiPhy guide and send:

> Use the quickstart-runner skill to follow the attached SiPhy v1.1 QuickStart
> from the supplied tar package. Treat the full guide as authoritative over
> older archive and skill instructions. Check readiness and obtain the required
> setup and execution decisions before running the four chip specialists.

If you explicitly test the original scenario skill instead, supply both original
files and require it to stop on a conflict. The older skill/README assumed
mandatory Bookshelf use and contained an automatic Recommended instruction.
The supplied v1.1 guide supersedes those assumptions. The original skill is
kept for review, not silently patched or advertised as a validated v1.1 runner.

## 3. Follow the full guide's setup

With permission, unpack the tar into a new staging folder and use its supplied
agents, skills and tool build contexts. Preserve `dot-github` transport layout
and follow the guide's destination instructions. Verify actual activation and
grants, Docker's Linux engine, the three reviewed images, Python >=3.10 for
report-gen (owner tested 3.13.17) and the actual Microchip Catalog connection.
Nothing in this README installs Python via pip or bypasses an access prompt.

The current Catalog endpoint/authentication/source binding was not captured
in the owner run; do not reuse a stale endpoint just because it appears in the
tar. Resolve that setup before promising a repeatable customer path. Existing
published agents should be referenced rather than duplicated; the exact four
SiPhy definitions are supplied in this tar and still need canonical publication.

## 4. Run the exact predefined prompt

After setup and explicit execution approval, use the prompt in **section 6 of
the full guide**, verbatim. It does not include the older automatic Recommended
phrase. Follow its sequence: spec agent, **parent-prepared contract**, design,
default lint/format, independent verification, then parent-owned reporting.

Bookshelf is a **separate, unvalidated optional variant** in v1.1. The current
owner run reported two successful Catalog calls and passed native engineering
gates. It reused an existing authorized contract/prior RTL; fresh-contract
creation remains unvalidated. Obtain explicit decisions for new behavior gaps
and run/repair bounds instead of inventing a contract or copying historical state.

## 5. Check evidence and limitations

Use actual native design/lint/simulation evidence on the identical final RTL,
plus report-gen outputs and the owner's full acceptance table. The reported
39,753 comparisons are historical observations, not an identical-count target.
Required coverage caveats, unavailable Bookshelf use and derived invocation
records stay explicit. No vendor-equivalence or physical/timing signoff is claimed.

The owner's Markdown has **five links to reference run files not supplied in
the tar**. They are preserved exactly, not repaired with fake evidence. They
refer to the retrieval record, results, dispatch history, final report and
requirements matrix. Those need their own delivery before evidence review;
do not confuse a missing historical link with an executed failed new run.

## Supporting files

Download **[ship.tar](files/ship.tar)**, unchanged: **40,992,256 bytes**,
SHA-256 `f06834009e5e28b0c2cb18f3b7ff5227d1cb8ee2ecbd84f41eda157f8907159c`.
The complete archive is included directly in this repository. Open the file
link and select **Download raw file**, or obtain it in a checkout of this
branch. It is the original supplied file, not a code-only replacement or a
pointer to a private location.

Use it with the full [QuickStart-Spec-to-RTL.md](QuickStart-Spec-to-RTL.md)
and [original skill 1.md](skill%201.md). The v1.1 guide is authoritative when
the older tar README or original skill conflicts with it.

### Original archive contents

- Setup README with the original setup procedure.
- Four agent definitions in `ship/dot-github/agents/`.
- Supplied report-gen and installation skills in `ship/dot-github/skills/`.
- Three chip-tool build contexts in `ship/discovery_catalog/`.
- Forty research PDFs and their README/manifest in `ship/knowledge/bs_data/`.

These files remain **inside the exact tar**; they were not replaced by our
own summaries or copied into new catalog-agent definitions. The contributor
confirmed permission to publish the complete archive, including its bundled
papers, on 2026-11-11. This records that confirmation, not an independent rights
audit. Original source notices, including the older manifest's caution, are
preserved unchanged; this publication does not relicense third-party content
or establish a successful fresh-project run.

### Not in the archive

The current reference-run artifacts linked by the completed QuickStart are
absent: retrieval record, results summary, dispatch history, final HTML,
requirements matrix, native CDE/logs, final RTL/testbench/VCD and reused contract.
Do not claim those are included just because the guide links to them.