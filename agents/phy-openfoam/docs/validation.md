# 0.2.1 source-candidate validation — 2026-11-23

## Initial public contribution check — 2026-11-24

The initial source-only catalog submission was checked in a separate checkout
against public Discovery commit `1d4dd93c3c6a710ee8846cfdc9c54e26491f3429`.
Only the agent entry is submitted; project results, native run stores, private
application state and installed binaries are excluded.

- The complete software suite passed **433 tests**, with **one skipped** because
  this host identity cannot create symlinks. Simulated reparse-point controls
  passed; no host permission policy was changed.
- All three manifests passed the target revision's schemas. Ruff `F`, source
  syntax, contained Markdown links and bounded sensitive-pattern checks passed.
- Tests preserve the user's concise scientific copy fields and expanded download
  context, enforce the public catalog's level-two README headings, and distinguish
  a mesh/solve allowance and post-run output assessment from stronger hard caps.
- The first full run had **seven Windows path-length failures**, with **426
  passing tests and one skip**. Its receipt was retained. A fresh run using
  extended-length paths for disposable scratch passed without skipping failures
  or changing the tested source, scientific checks, runtime or host policy.

These are source/fixture/installer checks, not new CFD, model calls, cloud
deployment, security certification or approval of a physical result. The
earlier development-validation history below remains retrospective; it is not
additional initial-release changelog history or public access to private receipts.

This is a new, bounded validation summary for the renamed self-contained entry.
It is not a relabeling of the [original 0.2.0 findings](../benchmarks/VALIDATION-HISTORY.md),
a public signature over private receipts, or a new CFD/model campaign. Raw local
test and installation receipts remain outside the public source entry because
they contain workstation paths. No commit, publication, or deployment was made.

## Checks performed

| Check | Observed result | Boundary |
|---|---|---|
| Complete deterministic/fixture/installer suite | **251 passed** after README follow-up (previously 247) | Synthetic gates and supplied native text; no new solver/model calls |
| Clean source-only mirror with a separate data root | **251 passed** after README follow-up (previously 247) | Mirror contains only public entry source; no local evidence archive or original run store |
| Non-editable host runtime installation in a new private location | Passed | Actual installer with `-SkipImage -Development`; original runtime not overwritten |
| Installed package identity and dependencies | Version **0.2.1**, import from installed site-packages, dependency check passed | Host installation only, not worker readiness |
| Installed license assets | MIT, notices, GPL version 3, and complete Gmsh license/exception present byte-for-byte | Inspected actual installed distribution, not just package configuration |
| Upstream license text comparison | Full GPL and Gmsh reference texts match after line-ending normalization | Not legal approval of a future image distribution |
| Three Discovery manifests | Passed supplied public schemas | Schema revision below; not action dispatch or catalog CI |
| Python syntax, JSON, YAML, TOML, Markdown local links | Passed bounded source checks | Links stay within the entry or point to external resources |
| Ruff `F` and PowerShell parsing | Passed | No claim that all configured legacy style rules pass |
| Public source extensions and metadata tags | Matched the inspected public catalog policies | Policy inspection is not the complete upstream CI/security suite |
| Workstation-path/known-secret-pattern and Unicode census | No findings in the bounded public-source scan | Not comprehensive DLP, verified-secret scanning, or security certification |

The original development environment and the clean installation used Python
3.12 on Windows x64. The clean dependency resolution selected NumPy **2.5.5**,
pydantic **2.14.3**, pytest **9.2.0**, and PyYAML **6.0.3**. These are observed
host versions, not a fully locked dependency set or the worker image's pinned
direct dependency versions.

Schema validation used the public Discovery schemas at commit
`298615100204c0dfe81a11598346ab8977ee2da6`. Public file/tag policy inspection used
the available upstream policies on 2026-11-23. Revalidate against the actual
target revision before submission. Run the entry's
[source checker](../scripts/check_release.py), [manifest validator](../scripts/validate_manifests.py),
and [test instructions](../CONTRIBUTING.md) to reproduce these layers.

## Failed intermediate checks were retained

Initial checks exposed an indentation error in a native-receipt helper, malformed
agent YAML, unsupported generic JSON-Schema keywords/oversized bounds in the tool
manifest, deep Windows test paths, and a fallback test that failed to clear an
explicit data-root override. These were corrected and the complete suite rerun.
The license comparison also caught and corrected a two-line wrapping difference
in the Gmsh license. Failed intermediate local receipts were retained separately;
they were not overwritten as successful results or confused with CFD failures.

No scientific acceptance thresholds, old signed runs, or original model judgments
were changed to obtain these passes. The original 64 benchmark collateral files
were checked byte-for-byte at relocation and retained in an ignored local archive.

## README follow-up review

The README now uses the user-facing **Scientific Researcher** capability name;
this does not relabel earlier native-runtime calls as tests of that engine path.
Its family-scope comparison was checked against Sections 2.1, 5.3, and 6 of the
[CFD Forge paper](https://arxiv.org/html/2610.14104v1): nozzle and forward-facing
step are routable families, whereas the cube study is supporting offline evidence.

Four added [documentation/diagnostic regression tests](../tests/test_readme.py)
cover the naming, comparison limits, and native output settings used by the two
advanced prompts. Foundation 14's
[surface-field implementation](https://github.com/OpenFOAM/OpenFOAM-14/tree/master/src/functionObjects/field/fieldValues/surfaceFieldValue)
supports flux-weighted `average` through `weightField`; the adapter permits that
setting and individual/combined force patches. These checks do **not** execute
the thermal design or tandem-cylinder studies, establish their accuracy, or
qualify Scientific Researcher integration. Both remain illustrative workflows.

Presentation checks also exercised Markdown-first rendering with Markdown-it
14.1.0 and strict KaTeX 0.16.22: all 17 inline expressions rendered without a
KaTeX error. Percentages now use prose units outside math, and named spacing
commands avoid Markdown consuming punctuation escapes before KaTeX sees them.
The [editable architecture SVG](../media/architecture.svg) was previewed in the
README and directly in a browser. Regression checks cover its local image
reference, XML structure, accessibility labels, size limit, and absence of
scripts or external resources. No runtime or scientific criteria changed.

The subsequent Setup reorganization retains Prerequisites, Configuration, and
Usage as subsections and adds two URL-based copy-and-paste prompts in the
requested order. Regression checks cover their heading hierarchy, complete-entry
acquisition, publication caveat, installed skill/agent destinations, and distinct
installation versus live-test scope. Those prompts were not executed as part of
the documentation change; no remote acquisition, installation, or smoke test is
implied by their presence in the README.

## Local runtime installation and WSL repair follow-up

On 2026-11-23 local time (2026-11-24 UTC), a separately authorized installation
used the complete local entry, copied the exact skill/prepared companion, and
installed the normal non-editable **0.2.1** host runtime. It built the matching
worker image locally; all **37** installed host/container package Python files
matched their source bytes. Dependencies, Foundation **14** package **20260724**,
and the image's non-root user were inspected. No meshing or solver was invoked.

A bounded metadata probe then exposed a host-infrastructure blocker on Podman
**5.8.10** client / **5.8.5** server with WSL **3.0.5**: legacy nested systemd sat
in a non-systemd subtree without propagated controllers. The kernel supported
CPU/memory/PID controls and user-service delegation already existed; forcing
`cgroupfs` did not restore rootless per-container enforcement. The failure and
its read-only diagnostic receipts were retained, not reclassified as CFD output.

The operator then authorized the [separate-machine repair](podman-wsl.md):

| Check | Observed result | Boundary |
|---|---|---|
| New vendor runtime | Official stable Podman **6.2.0** Windows AMD64 ZIP, release digest and checksum-file match; server **6.2.0** | Side-by-side install; the ZIP executables were not Authenticode-signed, so no signing-identity claim |
| Machine isolation/preservation | New rootless WSL machine; old idle machine stopped but retained with its image/configuration and a private image archive | No machine reset/removal, global WSL shutdown, rootful switch, or Docker API-pipe change |
| Native boot/delegation | Actual distro PID 1 is systemd; WSL-native boot enabled; cgroup v2 with `systemd` manager and delegated CPU, memory, PID, and I/O controllers | Observed startup state, not inferred from client version |
| Worker transfer | Image ID unchanged, beginning `33b27e3ccd1a`; user **10001:10001** | Same worker bytes, not a rebuilt or substituted solver |
| Previously failing capped-container probe | One-core CPU quota, **536,870,912-byte** memory limit, **128-process** limit; zero effective capabilities | Values read from actual kernel cgroup files, not only container metadata |
| CPU behavioral control | Half-core quota; **21** throttled periods and **1,096,162 microseconds** throttled in the short control | Tiny diagnostic processes, not a solver performance benchmark |
| Memory behavioral control | **64 MiB**, swap disabled; a child requesting **96 MiB** was killed and the cgroup OOM-kill counter increased | Deliberately bounded diagnostic; not a host OOM or CFD failure |
| PID behavioral control | Limit **16**; **15** children started, further creation denied, PID-limit event counter increased | Separate capped diagnostic container; children cleaned up |
| Persistence and installed sandbox | Normal new-machine stop/start passed; installed runner's read-only input/root and writable output mounts worked with one CPU, **512 MiB**, and its **4096-PID** limit | No prepared scientific run, worker solve, or journal created |
| Installed selection/policy | Private config selects the explicit newer executable; default Podman connection selects the tested machine; unenforced limits remain **false**, solve cap **2**, queue timeout **21600 seconds** | Default-connection change also affects other Podman clients; old executable remains installed |
| Installed CLI outside the checkout | **25** modules, **260** tutorials; health-input lint passed **10** checks without warnings | Capability discovery and lint are not resource-enforcement tests or scientific validation |

Private receipts include failed intermediate diagnostic attempts: a direct WSL
probe initially used the machine label rather than its prefixed distro name,
and an in-memory sandbox probe had a quoting error before execution. Corrected
probes passed; the failed receipts were not erased. Neither failure required a
solver/image change. No scientific checks, thresholds, or signed historical
records were edited, and no unenforced-limit exception was enabled.

After the documentation/test follow-up, the complete deterministic, fixture,
and installer suite passed **253 tests** (previously 251); the focused
documentation/runtime-selection subset passed **14 tests**. Two added checks
cover the migration/readiness guidance and existing absolute-executable lookup.
The naming assertion now preserves the user's explicit dropdown alias rather
than rejecting that approved README edit. Python AST, Ruff `F`, and bounded
source/link/privacy checks passed. These checks do not invoke CFD.

This establishes a working local capped runtime for the tested configuration,
not complete production isolation. Scientific Researcher dispatch, CFD smoke
execution, and the advanced studies remain separate, unexecuted qualifications.

## Progress-reporting follow-up

The subsequent reporting update added a passive
[terminal observer](../scripts/watch_campaign.py) and bounded one-minute
progress instructions to the skill, companion, and catalog prompt. The complete
suite passed **276 tests** (previously 253); the new observer tests use a fake
clock, not real-time sleeps or solver calls. AST, Ruff `F`, bounded source/link/
privacy checks, and editor diagnostics passed. Installed skill/companion bytes
match the updated source, and a live Discovery registry read returned the new
progress guidance. Registration is not evidence of background chat delivery.

A read-only observer was attached separately to an already authorized running
campaign. Successive flushed stdout lines approximately one minute apart were
observed with advancing iteration hints. The running campaign's registered
inputs/coordinators/decision rules, installed numerical files, and operator
configuration were independently checked unchanged. The observer log resides
outside signed artifacts. It does not import the numerical package, load keys,
invoke a runtime, solve, cancel, retry or control scientific work.

These observations qualify local **terminal** heartbeats for that process,
not proactive messages into an inactive chat. Host scheduler/notification
integration remains unqualified. The separate campaign's ongoing results are
not new acceptance or physical-validation evidence for this reporting change;
see [progress scope and limitations](progress.md).

## Copyable prompts and final HTML reporting — 2026-11-24

The two [bounded CFD examples](../README.md) now have ASCII plain-text copy
blocks and matching downloadable text. They scope work to one thermal-channel
screen targeting 5–10 minutes, or two isolated-cylinder resolutions targeting
about one hour. The installation/workflow setup prompts also have plain-text
copy fields. These targets exclude cold setup and approval delays, are not
convergence guarantees, and **were not newly benchmarked** during this update.
No additional pilot, grid/domain campaign or automatic retry is authorized by
the example wording.

The skill, companion and catalog instructions now require an illustrated,
self-contained final HTML report for accepted, rejected, inconclusive and blocked
outcomes. The bundled [presentation helper](../skills/phy-openfoam/scripts/render_report.py)
uses only existing records and native `status`, `verify` and `study-status`.
It is outside the numerical package and cannot change a scientific verdict.
See [reporting boundaries](reporting.md).

| Check | Observed result | Boundary |
|---|---|---|
| Full deterministic/fixture/installer suite | **303 passed**, no skips or failures in the final run | No new CFD, model or cloud job; earlier 301-test pass preceded two additional report-authority tests |
| Report regression coverage | Escaped HTML, embedded PNGs, input schematics, final/live/verification gates, conflicting separate analysis, missing cost, path/size limits and read-only native-command allowlist passed | Synthetic tests are not CFD acceptance evidence |
| Prompt copying and scope | Copy blocks equal supplied ASCII text; two-grid versus three-grid claims, approval gates, run counts and hard caps checked | Not a measurement of the new prompts' actual runtime |
| Complete skill installation | Helper, skill and prepared companion installed; all three match supplied bytes | Six unrelated workspace customizations preserved; no runtime installation/image rebuild |
| Source and manifest checks | Python 3.11 syntax compatibility, AST, Ruff `F`, three pinned public schemas, PowerShell installer tests and bounded source/privacy/link checks passed | Not full catalog CI or security certification |
| Existing-evidence HTML demonstration | Four finalized native measurement contracts freshly verified; report opens with summary and two labeled field images, retains the separate failed baseline gate | No new solver, continuation, study assessment or acceptance-policy mutation |
| Browser checks | Offline summary inspected; ten embedded PNGs decoded after loading collapsed diagnostics; no remote assets, scripts or horizontal overflow in the inspected viewport | Presentation QA, not solver/image scientific validation |
| Preservation | All 37 installed numerical source files still match canonical source; operator configuration, preregistered campaign inputs and 52 inspected native run/study records unchanged | Report files are new private derivatives outside signed stores |

The first full-suite attempt used an unnecessarily deep Windows scratch path:
three existing CLIO discovery fixtures failed with `WinError 206`, while 298
tests passed. The failed XML was preserved. A fresh shorter scratch path yielded
the complete 301-test pass without editing those tests or Windows policy; the
final suite with two more report checks then passed 303 tests. No scientific
threshold was changed to obtain these software-test passes.

The final HTML demonstration deliberately retains **baseline analysis FAIL**
even though its individual measurement contracts and registered grid study
passed. This checks presentation of distinct evidence scopes, not a new physics
qualification. Reports and QA receipts remain private; the runtime package,
worker image, signed evidence and earlier rejected pilot were not rewritten.

## Project-root results and verified migration — 2026-11-24

The subsequent approved storage update makes the user project, contribution
source and private runtime data distinct. New investigation inputs, generated
scripts, logs, analyses, native runs/studies, exports and reports belong in a
marked `results-<slug>` direct child of the explicitly selected project root.
Neither CWD nor source staging identifies that project. The installed skill now
includes the [results initializer/router](../skills/phy-openfoam/scripts/project_results.py),
[HTML renderer](../skills/phy-openfoam/scripts/render_report.py), and
[unsigned-artifact migration helper](../skills/phy-openfoam/scripts/migrate_results.py).

| Check | Observed result | Boundary |
|---|---|---|
| Complete software suite | **432 passed, 1 skipped**, no failures or errors in the final 433-test receipt | No new CFD, geometry solve, native model request or cloud job |
| Skipped test | Creating a real symlink was unavailable to this host identity | Traversal, resolved containment and simulated Windows reparse/junction checks passed separately; no host permission change |
| Routing regression coverage | Explicit project identity, marked direct-child folders, safe slugs, collisions, source/acquired-entry refusal, nested native-store protection, native option ordering and blocked-report containment passed | Agent/helper/developer interfaces are covered; arbitrary direct invocations of an older installed CLI are not retroactively sandboxed |
| Developer writers | Builders, campaign/comparison/report modules and optional harness CLIs require explicit routed destinations; source-relative output defaults removed | Developer benchmark changes tested from candidate source, not patched into the existing non-editable installed package |
| Workspace installation | Instructions, prepared companion and all three helpers match supplied source; six unrelated customizations preserved | Workspace-only update, no runtime package reinstall or worker rebuild |
| Installed helper integration | Child-scoped native schema inspection and a fresh report from an original historical run succeeded within selected project results | Schema/report inspection only; no scientific execution or assessment mutation |
| Unsigned migration | **80 files / 3,758,592 bytes** copied and SHA-256 verified: three report sets plus 71 retained legacy artifacts; only verified source copies removed | Per-destination migration manifests preserve original paths/hashes and unchanged HTML/receipt bytes |
| Historical preservation | **279 protected file hashes** remained unchanged; original accepted/rejected native records freshly verified in their original stores | Signing keys were not read/copied/replaced; only key file metadata was compared |
| Report preview | Migrated heated-channel report opens from project results, with both summary field images loaded; no scripts, remote assets or horizontal overflow in the inspected viewport | Presentation/migration QA, not new physical validation |
| Publication boundary | Bounded source/link/privacy checks and all three pinned manifest schemas passed; no generated result/report metadata remains in the contribution | Curated static examples and reviewed fixtures remain source assets; source check is not full upstream CI/security certification |

Failure receipts were retained instead of overwritten. Windows initially refused
removal of an already emptied unsigned report directory with its read-only
attribute set. The destination bytes were fully verified; cleanup resumed only
after a narrow, tested empty-directory attribute correction, with no ACL/owner
change, recursive force deletion or native-record edit. A full-suite attempt also
used an incorrectly constructed extended-path prefix; the corrected run exposed
PowerShell `-File` rejecting that prefix for copied installer fixtures. The test
launcher now removes only that prefix from the actual script argument, retaining
the same file, real installer execution and execution policy. The final complete
suite then passed as recorded above.

The operator configuration, installed numerical package, worker image and
original signed campaigns were not reconfigured, reinstalled or relocated.
Source developer benchmark edits are intentionally separate from that preserved
installation. New results stay outside the contribution, and migration is not
permission to rewrite old frozen inputs, budgets, source hashes or references.

## Still not executed or established

- No fresh 0.2.1 solver execution, mesh study, geometry run, or native CLIO/model
  request was made during this packaging/install/repair follow-up.
- The earlier clean host installation used `-SkipImage`; the subsequent image
  build and local resource checks above do not establish end-to-end skill or
  Scientific Researcher dispatch, physical accuracy, or mesh independence.
- No Azure action dispatch, cloud-study integration, authenticated multi-user
  confirmation authority, durable cloud signing service, or production sign-off.
- No image publication, corresponding-source compliance approval, vulnerability
  clearance, maintainer publisher approval, or complete public catalog CI run.

See [deployment readiness](deployment.md), [licensing](licensing.md), and
[source-distribution guidance](distribution.md) for the remaining release gates.