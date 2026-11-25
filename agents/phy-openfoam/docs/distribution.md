# Source distribution and catalog review

This guide covers a **source-only** contribution to
[microsoft/discovery](https://github.com/microsoft/discovery), scoped entirely to
the `agents/phy-openfoam` entry. It does not authorize publication, create an
Azure deployment, or establish first-party status. Container publication has
additional [licensing](licensing.md) and [deployment](deployment.md) gates.

## Contribution boundary

Keep the complete agent, runtime source, scripts, tests, examples, and collateral
under this entry. Do not copy the development project's root configuration into
the upstream repository, add root workflows, modify protected files, or update
unrelated Copilot instructions. Use the upstream review process for any separately
requested repository-wide change; it is not part of this package.

This boundary applies to **curated contribution assets**, not generated user
results. Every new investigation explicitly selects the user's existing absolute
project root and initializes a marked `results-<slug>-<utc>-<suffix>/` direct
child before authoring/freezing. Never infer that root from CWD, Git or source
acquisition; ask only when the intended project is ambiguous. All generated
inputs, scripts, logs, analyses, exports, HTML and new native artifacts belong
there, never under any project `agents` directory or anywhere inside an acquired
contribution, even staged elsewhere. Runtime installation/configuration/keys stay
in private app data. Static curated examples and reviewed test fixtures remain
source assets. See [routing](configuration.md) and [reporting](reporting.md).

The catalog landing page must retain these exact review headings:

1. **Overview**
2. **Architecture**
3. **Prerequisites**
4. **Configuration**
5. **Usage**
6. **Tools**
7. **Known Limitations**
8. **Contributing**

They are present in [README.md](../README.md). The **Setup** introduction follows
**Architecture**. **Prerequisites**, **Configuration**, and **Usage** use the
level-two headings required by the public catalog; the two prompt-driven setup
steps sit between Prerequisites and Configuration.
Keep links entry-relative, or use
HTTPS links to the authoritative upstream source. Nothing in the active docs
should depend on a parent-project README or a private evidence directory.

## Public source inventory

| Area | Public purpose |
|---|---|
| [Agent](../agent.yaml) and [metadata](../metadata.yaml) | Catalog definition and review metadata |
| [Tool manifest](../tools/openfoam/tool.yaml), [Dockerfile](../tools/openfoam/Dockerfile), [package metadata](../tools/openfoam/pyproject.toml) | Action interface and independently buildable worker/host source |
| [CLI](../tools/openfoam/src/discovery_physics/cli.py), core, adapter, worker, service | Deterministic implementation; no provider credentials |
| [Skill](../skills/phy-openfoam/SKILL.md), [results helper](../skills/phy-openfoam/scripts/project_results.py), [report helper](../skills/phy-openfoam/scripts/render_report.py), [migration helper](../skills/phy-openfoam/scripts/migrate_results.py), and [optional companion](../integrations/phy-openfoam.agent.md) | Complete supplied skill folder, installed separately from the runtime; explicit required-file preflight remains instructions plus reporting/results helpers, not a third-helper gate |
| [Scripts](../scripts/README.md) | Installation and optional developer/benchmark workflows |
| [Examples](../examples/README.md) and [held-out prompts](../benchmarks/heldout/prompts.json) | Public inputs, not executed-result claims |
| [Benchmark guide](../benchmarks/README.md) and [retrospective history](../benchmarks/VALIDATION-HISTORY.md) | Reproduction routes and carefully bounded historical findings |
| [Contribution guide](../CONTRIBUTING.md), [security policy](../SECURITY.md), [changelog](../CHANGELOG.md), and these docs | Review and operating instructions |
| [Operator example](../config/operator.example.json), [deployment example](../config/deployment.example.json) | Separate public templates, never populated with private operator/deployment values |

Include the [entry MIT license](../LICENSE), [tool MIT license](../tools/openfoam/LICENSE),
[third-party notices](../tools/openfoam/THIRD_PARTY_NOTICES.md), and the complete
[GPL-3.0-or-later license text](../tools/openfoam/LICENSES/GPL-3.0-or-later.txt)
and [Gmsh's license and linking exception](../tools/openfoam/LICENSES/Gmsh-4.13-LICENSE.txt).
Review all
fixtures and embedded OpenFOAM dictionary headers: a source-only contribution
does not authorize stripping third-party attribution or relabeling third-party
material as MIT.

## Exclude private and generated material

Do **not** export the ignored workstation-only historical evidence area. Original
benchmark outputs, receipts, and native transcripts were relocated byte-for-byte
for local retention; they contain absolute paths and native session metadata and
are intentionally not public collateral. The public history is a new
retrospective summary, not a sanitized replacement for those originals.

That archive is historical retention, not a destination for fresh results.
It may be copied into marked project results under approved preservation handling;
its original scope, paths, failed attempts and byte provenance remain intact.
Do not turn this policy into a claim that private native stores or signing keys
were moved. Public docs must not link to private archives or project results.

Also exclude:

- Discovery routing/state, tasks, private notebooks, native session stores,
  host-tool capability URLs, authentication bindings, API keys, and tokens;
- HMAC keys, registry/cloud credentials, operator configuration containing private
  values, virtual environments, caches, solver run stores, and generated fields;
- project `results-*` containers, their manifests, authored campaign scripts,
  reports, snapshots, receipts, analyses, logs and exports unless a separately
  reviewed public derivative is explicitly approved;
- vendor executables, CLIO binaries, downloaded OpenFOAM packages, container
  layers, exported images, and other installed third-party runtimes;
- private deployment substitutions or unreviewed output archives.

In particular, no contents of the local Discovery state directory may be
published, even when a file looks like harmless routing metadata:

```text
.discovery/
```

Ignore rules are not a security review. Inspect the complete proposed source
inventory, including normally ignored/untracked files and binary fixtures, before
export or staging. Limit the final contribution diff to the approved entry.

## Retention and sanitized derivatives

1. Preserve original local evidence immutably, including original failures and
   post-run scoring/audit corrections. Never rewrite a signed run to remove a
   path, change a threshold, repair an audit, or make a receipt look public-safe.
2. If a bounded public derivative is needed later, create a **new artifact** in a
   separate reviewed location. Label it as derived, list source hashes, document
   redactions/normalization and transformation version, and retain the mapping
   privately when it contains sensitive identifiers.
3. Hashes identify bytes/provenance; they do not prove the correctness of omitted
   evidence, authenticate an unavailable original to the public, or recreate
   missing fields, keys, ancestors, or study members.
4. HMAC verification requires secret-key custody and is not a public signature.
   Do not publish a key to make a receipt verifiable. A CLI export archive is not
   automatically a complete externally verifiable lineage package.
5. An explicitly approved relocation of an unsigned report delivery creates
  byte-identical copies plus a results manifest recording original paths/hashes,
  source revision and native IDs. Use the supplied
  [migration helper](../skills/phy-openfoam/scripts/migrate_results.py) with required
  `--project-root`, original unsigned `--source` and `--slug`; it defaults to
  copy-only. Optional `--archive` preserves a legacy tree beneath archive, and
  `--exact` refuses a slug-folder collision. Detected journals, keys/configuration
  and links block copying. Separately approved `--remove-source` cleanup follows
  full source-inventory and every copied file's hash verification. Preserve the
  old report's relative-reference dependencies and original native references;
  do not rewrite old receipts,
  preregistrations, journals or budgets. Retain old copies unless deletion was
  explicitly approved. This is derivative delivery, not native-store/key
  migration or new scientific verification. New renditions use fresh report
  subdirectories, never overwrite individual existing report files. See
  [migration scope and receipts](reporting.md); documenting the interface is not
  a claim that migration or cleanup ran.

The current public entry promises neither publicly authenticated HMAC receipts
nor access to the private original transcripts. Independent validation requires
new runs with a documented environment and retained native evidence.

## Pre-review checklist

- [ ] Confirm scope is source-only and every proposed file is under this entry.
- [ ] Confirm the runtime/workspace installers, both config examples, license
  texts, notices, and all linked artifacts are present in the final integrated
  entry. Documentation of their contract is not a substitute for delivering them.
- [ ] Confirm the full supplied skill includes instructions, reporting/results
  helpers, the migration helper and resources. Installation refuses missing
  instructions or either explicitly required reporting/results helper before
  copying anything, without adding a third-helper gate, and keeps
  unchanged files/cache exclusions intact. Validate the integrated renderer's
  required project root, results-dir/slug exclusivity and contained fresh outputs.
- [ ] Keep all generated developer/benchmark receipts in explicitly selected
  marked project results, not source/CWD defaults; every writer needs
  `--project-root`, `--results-dir` and fresh `--out` (`--output` for builders).
  Use the documented work/input roots and preserve private runtime/key/resource/
  shared-slot policy. Source validation selects both tools/openfoam/src and the
  entry root on child-only `PYTHONPATH`, not an assumed updated non-editable install.
- [ ] Confirm `phy-openfoam`, candidate version **0.2.1**, local image
  `localhost/phy-openfoam:0.2.1`, and cloud image template
  `{name}.azurecr.io/phy-openfoam:0.2.1` agree across the relevant interfaces.
- [ ] Keep the Python distribution/module/CLI names unchanged:
  `discovery-physics-openfoam`, `discovery_physics`, `discovery-physics`.
- [ ] Review publisher identity with upstream maintainers. Existing Microsoft
  publisher metadata is pending maintainer confirmation, not evidence that the
  contribution is approved or first-party; do not infer a classification.
- [ ] Confirm all landing-page headings, entry-relative links, manual plural
  skills destination, and separate runtime/workspace installation instructions.
- [ ] Check installers do not vendor credentials/binaries, overwrite workspace
  files without explicit force, or enable unsafe resource choices.
- [ ] Run fresh tests, lint, manifest/schema checks, and supported-platform install
  checks as authorized. Record exact source/version/environment and distinguish
  unit/fixture validation from CFD and native model calls.
- [ ] Do not reuse the original 157-test count as a 0.2.1 result; keep
  [historical findings](../benchmarks/VALIDATION-HISTORY.md) retrospective.
- [ ] Complete source/license/notice and sensitive-data review of the full export.
- [ ] Keep cloud dispatch, enforcement, and production sign-off explicitly open
  until the actual deployed route has been tested and approved.

No checklist item is marked complete by this document. The documentation-only
pass does not run installers, test suites, solvers, model calls, image builds,
publication, or deployment.

For cloud/service jobs, `/output` remains the platform-managed mount. Host
publication, where actually available, materializes returned artifacts into the
explicit project's marked results; a host path is not a path inside the worker.
None of the standalone helpers becomes a new catalog action. Disclose an
unavailable publication location rather than invent a tool, silently switch routes or claim
an unmaterialized host report. Existing campaign status still uses the original
native/platform references directly without initialization, wrapper logs or HTML.

## Image redistribution is a separate release

The independent host source is MIT-licensed. The aggregate image includes
OpenFOAM/Gmsh and other dependencies with their own terms; metadata such as
`MIT AND GPL-3.0-or-later AND GPL-2.0-or-later` expresses multiple applicable licenses, **not an
MIT-or-GPL choice** for every component.

Before publishing any image, inventory exact dependencies, retain build inputs,
produce notices/SBOM, arrange the required corresponding source and build
information for redistributed GPL components, and complete compliance review.
A pinned download/checksum or a generic upstream URL alone is not a complete
corresponding-source distribution plan. See [licensing](licensing.md).

The base image digest and OpenFOAM package bytes are pinned, but apt and some
transitive dependencies float. Do not call this a fully reproducible image build
or equate a successful build with vulnerability clearance, legal approval,
publication approval, or production qualification.