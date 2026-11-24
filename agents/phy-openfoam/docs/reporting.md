# Final HTML reporting

Every completed investigation must create and link a **professional,
self-contained HTML final report**, including rejected, inconclusive,
correction-needed, blocked, refused and unexecuted outcomes. A report is an
evidence presentation, not a new scientific decision. Do not invent a native
verdict when no native run exists. An explicit report-packaging blocker is not
a completely reported investigation.

The opening section gives a concise conclusion and attractive, labeled native
field images already available from the recorded run. If no solution image
exists, show a clearly labeled **input geometry schematic, not simulated flow**.
If neither can be produced safely, state that no visual is available. Do not
fabricate fields, silently substitute a different geometry, or add CFD or late
diagnostics solely to obtain an image.

## Install the complete skill

The standalone stdlib [report helper](../skills/phy-openfoam/scripts/render_report.py)
and [results helper](../skills/phy-openfoam/scripts/project_results.py), plus the
[unsigned-migration helper](../skills/phy-openfoam/scripts/migrate_results.py), are
bundled beside the [skill instructions](../skills/phy-openfoam/SKILL.md), not inside
the `discovery_physics` package. The workspace installer copies the **whole supplied
skill folder**, including the migration helper and resources, while excluding
caches and Python bytecode. Its explicit required-file preflight remains the
instructions plus reporting and results helpers; it does not add a third required
helper gate. See [installation](installation.md) for collision preflight and
manual copying. Copying the Markdown alone omits the supplied scripts/resources.

Any existing Python 3.11+ interpreter can run the helper; no pip install,
container rebuild, image update, plotting dependency, browser dependency or
network service is needed. Native inspection still requires the actual installed
physics CLI and the campaign's original authorized verification context. The
blocked/no-run form needs neither the physics runtime nor a run store.

## Project-owned destination

Select the current user's existing **absolute project root** explicitly. Never
infer it from the shell CWD, Git, runtime installation or source acquisition.
In a multi-root workspace, ask only when the intended user project is ambiguous.
All new user-generated work belongs in a marked direct child of that project,
never under any project `agents` directory or anywhere inside the acquired
contribution source, even if staged elsewhere. Source examples and reviewed
fixtures remain contribution assets, not report destinations.

For a new campaign, initialize results **before authoring or freezing**, not just
when rendering HTML. The results helper's `init --project-root <absoluteproject>
--slug <slug>` creates a unique `results-<slug>-<utc>-<suffix>/` with
`results-manifest.json` and `inputs/`, `analysis/`, `logs/`, `exports/`, `runs/`,
`studies/`. Slugs use lowercase letters/digits separated by single hyphens.
`--exact` requests `results-<slug>` and refuses collisions. Its `check` action is
read-only; `run` invokes an explicitly requested installed native command with
child-only `DISCOVERY_PHYSICS_RUNS=<results>/runs`, CWD at results and CLI logs
under results. It does not automatically solve, propose or confirm. See
[routing and unchanged runtime policy](configuration.md).

The renderer can use that **existing marked container**, even though its input
and native directories already exist. Fresh report files default to its top
level. For a report-only delivery from existing/legacy evidence, `--slug` can
create a new marked container instead; do not use that as a reason to relocate
the original campaign. Optional `--out` stays inside the same selected container,
outside signed stores, and never overwrites an individual report file. For a
rerender, choose a fresh `reports/v2` subdirectory, not the existing report files.
`--out` requires `--results-dir`: combining it with `--slug` is refused. Initialize
a new container first when selecting a custom report subdirectory.
Keep HOME, operator configuration, signing keys, resource caps and shared solve
slots unchanged. Results metadata does not belong in the runtime config model.

## Interface

These are invocation templates, not evidence that a report or solve has run.
Replace placeholders with the actual installed skill path, explicitly selected
absolute user project, marked results, original recorded store and native IDs.
Do not create a replacement store or key to make an old run verify.

```text
python <skill>/scripts/render_report.py --project-root <absoluteproject> --results-dir <existingmarkedresults> --runs-root <originalrecordedstore> --run <native_run_id>
python <skill>/scripts/render_report.py --project-root <absoluteproject> --slug <newslug> --runs-root <originalrecordedstore> --study <native_study_id>
python <skill>/scripts/render_report.py --project-root <absoluteproject> --results-dir <existingmarkedresults> --runs-root <originalrecordedstore> --run <native_run_id> --out <results>/reports/v2
python <skill>/scripts/render_report.py --project-root <absoluteproject> --slug <newslug> --blocked-reason <reason> [--bundle <existinginputbundle>]
```

| Option | Meaning |
|---|---|
| `--project-root` | Required existing absolute user project root; never CWD, a guessed Git root, `agents` or acquired contribution source |
| `--results-dir` | Existing marked direct-child results container belonging to that project; mutually exclusive with `--slug` |
| `--slug` | Create a unique new marked project-results container; supply exactly one of this or `--results-dir` |
| `--runs-root` | Existing campaign run store read at its recorded location, including a legacy external store; never an output or relocation request |
| `--run` | Existing native run ID; repeat to select multiple runs |
| `--study` | Existing native study ID; repeat or combine with `--run`; automatically includes current leaf members |
| `--out` | Optional report destination inside the selected results container and outside signed run/study stores; defaults to the marked root. Requires `--results-dir`, not `--slug`. Existing containers are allowed, existing report files are not overwritten. |
| `--title` | Optional report title; imported text is escaped |
| `--analysis` | Optional existing JSON object containing a separately recorded analysis; displayed as a non-native derivative |
| `--cli` | Optional actual `discovery-physics` executable, not the container engine or a catalog action |
| `--blocked-reason` | Explicit blocked/refused/no-run explanation; still requires project root and results selection, but omits run/study selection and needs no CLI |
| `--bundle` | Optional existing input bundle for a no-run schematic; it is read, never prepared or executed |

The helper resolves the physics CLI from `--cli`, then
`DISCOVERY_PHYSICS_CLI`, then PATH, then the operator's DiscoveryPhysics home.
Invalid explicit selections fail rather than silently switching runtime. Use
the original campaign's store and key context; custom roots must be visible to
the process. A local shell helper is **not** a new cloud/catalog action. If only
returned service evidence is available, package that evidence without silently
changing routes or pretending local native IDs exist.

For example, after resolving `$py` to an existing Python and `$dp` to the actual
physics CLI, select the user project explicitly. For a **new** campaign this
initialization precedes all generated inputs and native preparation:

```powershell
$project = Read-Host 'Existing absolute user project root (not acquired source)'
if (-not [IO.Path]::IsPathFullyQualified($project)) { throw 'Select an absolute project path.' }
$project = (Resolve-Path -LiteralPath $project -ErrorAction Stop).Path
$skill = Join-Path $project '.github/skills/phy-openfoam'
$layout = & $py (Join-Path $skill 'scripts/project_results.py') init `
  --project-root $project --slug flow-investigation | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Results initialization failed.' }
$results = $layout.results_root
# Author/approve/run separately using this results container; rendering never solves.
# When the selected outcome exists, use its actual recorded native store and ID:
$runId = Read-Host 'Actual existing native run ID from the selected campaign'
& $py (Join-Path $skill 'scripts/render_report.py') --project-root $project `
  --results-dir $results --runs-root (Join-Path $results 'runs') --run $runId `
  --title 'Flow investigation: evidence and limitations' --cli $dp
```

Replace the placeholder ID and use the actual store: legacy evidence may live
elsewhere and stays there. The initialized container already exists; its three
report files must not. To package a runtime blocker in a **new** results
container without invoking any native command, use an existing Python:

```powershell
$project = Read-Host 'Existing absolute user project root (not acquired source)'
if (-not [IO.Path]::IsPathFullyQualified($project)) { throw 'Select an absolute project path.' }
$project = (Resolve-Path -LiteralPath $project -ErrorAction Stop).Path
$reporter = Join-Path $project '.github/skills/phy-openfoam/scripts/render_report.py'
python $reporter --project-root $project --slug blocked-investigation `
  --blocked-reason 'Required runtime is unavailable; no CFD was executed.'
```

If the campaign already has a marked container, substitute `--results-dir` for
`--slug`; select a fresh results-contained `--out` when previous report files exist.
Add `--bundle` only if a relevant input bundle already exists. Do not prepare a
case just to decorate a refusal. Always open/check the resulting HTML and link
it in the final answer; a successful process exit alone is not delivery.

## Outputs and authority

The selected marked results root (or its explicit report subdirectory) contains:

- `report.html`: offline, responsive HTML with inline styles and embedded visuals;
- `evidence-snapshot.json`: the collected native observations and presentation
  provenance, with image hashes instead of duplicate base64 payloads;
- `report-receipt.json`: report/snapshot/renderer hashes and presentation-only,
  no-solver metadata. This is not a new signed native scientific receipt.

Keep the results manifest with the delivery and record source revision, original
native paths, run/study IDs and derivative provenance there. It is not a signing
key, a new native verdict, or proof that historical stores were moved.

The helper's native command allowlist is **`status`, `verify`, `study-status`
only**. It reads existing bundles, plans, figures and recorded study assessments.
It does not call `prepare`, `execute`, `finalize`, `propose`, `study-assess`,
continuation, recovery or a solver. A missing/stale study assessment remains
unassessed; report packaging does not regrade it. Failed verification is reported
as uncertainty, never as acceptance. A failed native inspection can block
packaging; retain the failure and use a truthful blocked report or disclose the
packaging blocker, not a new solve or a different verification key.

Keep these scopes separate in both summary and detailed sections:

| Evidence | What it can support, when its registered checks pass |
|---|---|
| Native run contract | Only its frozen objectives, possibly numerical health/settling or a bounded reference screen |
| Registered grid study | Only its frozen cross-run/discretization criteria, not automatic physical validation |
| Domain-sensitivity comparison | Only the registered measured comparison; not a certified infinite-domain bound |
| Reference/validation evidence | Its applicable normalization, uncertainty and preregistered tolerance; a healthy solve cannot cancel a reference failure |
| Design decision | The registered feasibility/ranking and uncertainty criteria; accepted measurement members alone do not establish a winner |

Native `ACCEPT` requires the final native verdict, `live_acceptance: true` and
successful integrity verification in the actual context. HTML styling, images,
a passed check count, renderer exit status or a separate analysis cannot upgrade
`REJECT`/`INCONCLUSIVE`, conceal unknown checks, or create campaign acceptance.
The full final report retains failed/unknown checks, measured values and their
recorded units, assumptions, limitations, run/study IDs and verification state.

## Images, offline behavior and security

- Existing native field PNGs are labeled by source/run. Captions must distinguish
  field images from convergence plots and from input schematics. State recorded
  field/time/units when available; otherwise say unavailable rather than infer
  them. Images are illustrative, **not acceptance evidence**.
- The fallback schematic draws literal supported input mesh-block coordinates,
  including supported circular arcs. It is not a simulated field, reconstructed
  solution, validated mesh or independent CAD interpretation; aspect may be
  adjusted. Unsupported expressions/directives or missing geometry are not
  evaluated to obtain a picture.
- The helper escapes imported text, embeds bounded raster PNGs and its own inert
  geometry SVG, and refuses traversing asset paths. Arbitrary imported active
  SVG/HTML is not embedded as an image. Inputs have bounded JSON/image reads;
  refused or oversized imagery is disclosed rather than replaced by invented flow.
- HTML has no JavaScript, CDN, remote fonts, external assets or third-party
  dependencies. Inline CSS, embedded data and a restrictive content-security
  policy support offline viewing. No network request is needed to view the result.
- Keep output inside the selected marked project results and outside signed
  run/study stores, never under `agents` or acquired source. Do not edit journals, evidence,
  bundles, frozen budgets or verdict code. Native verification can use the
  original local key; it does not export that key into the report.
- Reports/snapshots can contain geometry, assumptions, paths and local IDs.
  Review before sharing. Content hashes and same-user HMAC verification are not
  independent authorization, public authentication or publication approval.

If only the raw skill Markdown was copied, or packaging fails, the agent must
create equivalent **escaped, self-contained HTML** with inline CSS, safe embedded
existing PNGs or an explicitly labeled input schematic, the evidence provenance,
and the same outcome/authority boundaries in a validated marked project-results
destination. A missing results helper is not permission to guess a root or write
into source: obtain the complete skill or disclose the blocker.
No new dependencies or scientific work
are authorized by that fallback. If it cannot do so, disclose a report-packaging
blocker and never claim the investigation is completely reported without HTML.

## Separate analyses and cost

`--analysis` displays an **existing recorded derivative**, hashes that JSON and
explicitly does **not** independently verify it or treat it as a native verdict.
Use the already preregistered analysis for any preregistered campaign decision;
retain its original inputs, code/version, tolerances, failed/pending criteria and
provenance. A post-hoc interpretation must be labeled post-hoc/exploratory, not
preregistered. The helper does not execute analysis, authenticate preregistration,
add native checks or reassess a study. Separate validation failure remains a
failure even if every native health contract is accepted.

Disclose actual recorded elapsed cost and what it includes. The helper's
displayed-run wall-time sum covers selected **leaf runs**, not necessarily all
restart ancestors, attempts, meshing/setup outside that measure, CPU-hours,
image acquisition or human effort. An existing separate analysis may provide
broader totals with explicit provenance and scope; label them as derivative,
not native-verified accounting. Missing measurements remain unavailable, not
zero-cost claims. Targets, generic estimates and hard caps are not measured cost
or a convergence guarantee; see [bounded examples](../examples/README.md).

## Status requests stay lightweight

**On-demand by default:** a status/progress question gets one fresh read-only
snapshot in chat using the original recorded native path directly, including
legacy external stores. Do not initialize results, invoke the results run wrapper,
write wrapper logs or generate a final report. It does not regrade/reassess,
finalize, control a run, change supervision/scheduling, add timers or start a
polling loop. Periodic monitoring remains opt-in. An explicit request to package
an existing outcome can create HTML without new CFD or a new decision. Follow
the [status procedure](progress.md).

## Explicit unsigned-delivery and archive migration

The supplied [migration helper](../skills/phy-openfoam/scripts/migrate_results.py)
copies an explicitly selected original **unsigned directory** into a new marked
results container. It uses existing stdlib Python and the adjacent results guard;
no runtime installation, image update, native CLI command or CFD is involved.
This is a separately approved preservation operation, never an automatic report
or status side effect. These are templates, not a claim that migration ran:

```text
python <skill>/scripts/migrate_results.py --project-root <absoluteproject> --source <originalabsoluteunsigneddirectory> --slug <slug> [--exact] [--archive] [--remove-source]
```

| Option | Meaning |
|---|---|
| `--project-root` | Required existing absolute user project; the same source/output exclusions and root marker policy apply. |
| `--source` | Required original unsigned directory to inventory and copy, not a rewritten derivative or signed store. Select its actual absolute path explicitly. |
| `--slug` | Required slug for a new marked results container; no `--results-dir`, `--out` or action subcommand is accepted. |
| `--exact` | Optional exact slug-folder name; refuses an existing destination rather than overwriting. |
| `--archive` | Preserve the complete legacy relative tree beneath archive inside the new container instead of placing delivery files at its root. |
| `--remove-source` | Optional **separately approved** cleanup of only the verified original files and empty directories after copying; omission is copy-only. |

Without `--archive`, report/snapshot/receipt files retain their relative names at
the marked root. For a separately approved legacy evidence archive, use
`--archive` after confirming its inventory contains no native journals or other
refused state; any detected journal blocks the whole selected tree. Each report
set/archive gets its own fresh marked container. The helper refuses signed-record
ancestry, detected journals, known key/configuration names and key extensions,
and linked/reparse sources or entries. This is not a generic secret sanitizer;
review all archive contents and keep private session/receipt material private.

Copying preserves every file's bytes, old receipt/renderer hashes and historical
embedded paths. The original source inventory is checked after copying; every
destination is hashed and size-checked. A new migration manifest records source
directory, relative destination mapping, hashes, byte counts and cleanup
authorization, with a separate cleanup receipt and the results marker. Before
optional cleanup, the helper checks the whole source inventory again and verifies
every copied file hash; a change stops cleanup. Cleanup removes only enumerated
matching originals and empty directories, not an unreviewed recursive tree.
Retain failures/manifests and inspect remaining originals if cleanup is interrupted.

Preserve old relative-reference dependencies and the native paths the reports
cite; copying does not rewrite receipts/preregistrations, move signed history or
keys, reauthenticate the science, or authorize new simulations. Default copy-only
retains originals. Source removal needs actual explicit authorization and
`--remove-source`, not merely an archive/copy request. An archived tree retains
its old scope and failure history and is never a destination for fresh results.

## Platform output

For a cloud/service route, `/output` remains the platform-managed worker mount.
An absolute host project path is not a container path, and none of these helpers
is a new catalog action. Use actual available host/platform publication to materialize
returned artifacts into the selected project's results container; if unavailable,
disclose the publication-location blocker and retain original platform references.
Do not invent an action, claim an unmaterialized host report, or silently switch
the execution route to satisfy the delivery policy.