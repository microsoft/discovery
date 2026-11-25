# Troubleshooting

Start with the exact JSON error, effective CLI/image/runtime selection, source
revision, and whether the operation was input lint, a local solve, a model call,
or a deployed request. Do not turn an infrastructure failure into a scientific
verdict or alter the implementation/checks to make a result pass.

Keep diagnostics private until reviewed for keys, capability URLs, absolute
paths, geometry, and native session metadata. Security concerns go to
[MSRC](https://msrc.microsoft.com/create-report), not public issues; see
[SECURITY.md](../SECURITY.md).

## Installation and discovery

| Symptom | Check | Safe response |
|---|---|---|
| `discovery-physics` is not found | Was the host runtime installed, rather than only the Markdown skill? | Follow [installation](installation.md); resolve `DISCOVERY_PHYSICS_CLI`, `Get-Command`, or the default user-local executable. |
| Custom installation works in one shell, not Discovery | The app may predate the environment changes | Launch the app with the approved CLI/data-root environment; do not assume an installer changes existing process environments. |
| Skill is not discovered | Open the intended target project and check the plural skills destination below | Save the actual Markdown file, not a URL shortcut; inspect the app's normal customization discovery. Do not replace unrelated Copilot instructions. |
| Workspace installer refuses a destination | The target may be missing, or a destination already exists | Choose an existing project. Review differences; only the operator/user may authorize explicit `-Force`. |
| Source edits do not affect the CLI | Normal installation is non-editable | Reinstall the intended revision, and rebuild the image if its code changed. Use explicit development/editable mode only when intended. |
| Old image behavior appears after upgrade | Environment or local operator configuration may override defaults | Inspect effective `DISCOVERY_PHYSICS_IMAGE`, `DISCOVERY_PHYSICS_RUNTIME`, and the selected config; do not retag an unknown image as proof of compatibility. |

Required manual destination in the target project:

```text
.github/skills/phy-openfoam/SKILL.md
```

The optional companion destination is:

```text
.github/agents/phy-openfoam.agent.md
```

For a manual download before upstream merge, use the approved contribution ref,
not an assumed live `main` URL. The [compatibility wrapper](../scripts/setup.ps1)
installs the host runtime only; it does not install workspace Markdown.

## Container infrastructure

| Symptom | Meaning | Safe response |
|---|---|---|
| Engine executable/socket/image unavailable | Host setup or runtime selection failure | Report an infrastructure blocker. Operators install/start/authenticate the engine independently. |
| CPU/memory/PID enforcement refusal | Expected fail-closed behavior on an engine without working controllers | Prefer an enforcing runtime. Only an operator may authorize a disclosed exception; an agent must not set configuration or exception flags. |
| Missing `memory.max`, empty controllers, or cgroup errors on Windows/WSL | A legacy namespaced-systemd machine may lack controller propagation above the user service, even when the kernel supports it | Use the operator-controlled [native-systemd migration and real bounded probe](podman-wsl.md). Podman 6.2+ is needed for new native machines; upgrading the client alone does not migrate an old machine. Do not create the file, repeat an existing user `Delegate` override, force `cgroupfs`, or disable limits as the repair. |
| Long Podman startup or storage lock | Engine/VM or ownership-remap issue, not CFD evidence | Pause solves and ask the operator to investigate with vendor guidance. Do not add `--userns=keep-id`, reset storage, delete images, or stop/reconfigure the VM on the agent's initiative. |
| Solver module or tutorial missing | Possibly a different OpenFOAM distribution/image | Inspect `capabilities` and actual image identity. Foundation 14 is not interchangeable with OpenCFD. |
| ARM host/image mismatch | Image recipe installs an AMD64 Debian-format package | Use the qualified Windows x64 setup; ARM/emulation and Linux/macOS setup are unqualified. |
| Script has CRLF/shebang or quoted-path errors during build | Checkout/context formatting or shell invocation problem | Preserve intended LF shell scripts and quote paths. Fix the source/build context, never normalize signed historical records. |
| Run waits rather than starting | Shared solve-slot/concurrency policy | Inspect queue status and the operator cap. Do not increase concurrency to bypass the queue. |

The `--allow-unenforced-limits` flag, where exposed by benchmark tooling, is an
explicit **operator-only** exception, not a standard repair command. Inherited
operator configuration is still effective when the flag is omitted. Disclose
runtime evidence of unenforced limits; do not present an exception as measured
production enforcement. See [configuration](configuration.md).

For long campaigns with no visible chat update, see
[progress delivery and the read-only heartbeat](progress.md). A blocking call
or yielded chat turn may prevent proactive messages; use the live terminal
output instead of assuming silence means a failed solve. The observer never
changes an active run or proves liveness merely from a saved `running` label.

`capabilities` discovers Foundation modules and tutorials; it does not request
the solver's CPU/memory/PID limits. A successful image build or capability call
therefore cannot clear an enforcement blocker. Verify the selected connection,
live kernel limit values, and installed runner's sandbox separately. When using
a side-by-side runtime, check both the executable path and Podman's connection
selection; an older `podman` may remain on `PATH`.

## Input and scientific gates

- **Lint produced JSON but did not pass:** inspect `ok`, `errors`, and warnings.
  A successful command exit alone is insufficient; `lint` can return `ok: false`
  as data. Schema/type failures and other refusals normally return JSON `error`
  and `detail`, with exit code 2.
- **Unknown metric, wrong units, or uncovered objective:** inspect `schema`, the
  [metric catalog](../tools/openfoam/src/discovery_physics/openfoam/catalog.py),
  and declared function-object outputs. Add justified evidence/check coverage to
  a new bundle before solving. Do not remove the objective or weaken its
  threshold after results are seen.
- **Confirmation required:** obtain the actual user's decision. A model must
  not confirm its own `method_substitution`, edit the frozen assumption, or
  treat an operator resource exception as scientific consent.
- **Successful solver but `REJECT`/`INCONCLUSIVE`:** read failing and unknown
  checks. Process completion is not acceptance, and baseline health does not
  establish accuracy, model suitability, or grid independence.
- **Transient mass discrepancy:** compare stored mass and outward flux within
  restart segments, inspect seam continuity and monitor precision. Unequal
  inlet/outlet flux alone is not a transient conservation failure. The
  [monitor implementation](../tools/openfoam/src/discovery_physics/openfoam/monitors.py)
  manages precision; any input correction needs a new, disclosed frozen attempt.
- **Continuation or reassessment refused:** respect attempt/time/cell/budget
  bounds and existing rulings. Do not hand-edit state or use `reassess` to
  rewrite a finalized decision.

## Integrity, cancellation, and retention

If `verify` fails, stop decisions on that lineage. Confirm that the intended
data/run root and original HMAC key are selected; do not generate a new key,
change journal hashes, rewrite evidence, or remove failing records. Preserve
the failure and investigate privately. Same-user HMAC verification is not a
public signature or independent authorization proof.

Use `status` to inspect work, `cancel` for an intentional stop, and `recover`
only for the recorded missing-executor case. Lost/cancelled execution must not
be finalized as live acceptance. Runtime/VM maintenance is an operator action,
not a scientific corrective action.

Exports can omit heavy fields, ancestor/member lineages, code, and external
retention evidence. Even `--include-fields` does not automatically supply all
of those. Do not export keys to fix portability. Keep historical originals
immutable; do not compact them. Any public sanitized derivative is a new,
explicitly labeled artifact with source hashes and transformation provenance.

## Native CLIO and optional developer checks

- The [native driver](../scripts/clio_driver.py) owns runs in-process. Killing
  that driver/server kills its live work; a machine-wide historical `running`
  row alone is not proof of a surviving process.
- Select an installed CLIO executable with `--clio-executable` or
  `DISCOVERY_CLIO_EXE`. An explicit invalid override must be corrected by the
  operator, not silently replaced or worked around with a copied vendor binary.
- `DISCOVERY_CLIO_STATE_HOME` changes the model-comparison inspector's native
  session-state lookup root, not CLIO's own session-writing configuration.
- Model-comparison `collect` audits existing responses without new model calls;
  it does not authorize answer tuning, hidden retries, or rewriting prior output.
- [Path checks](../scripts/live_paths.py) and
  [fixture generation](../scripts/fixture_probe.py) default to the public
  [health-only bundle](../examples/channel-path-check.json), or accept `--bundle`.
  They do not require a historical local run. Select fresh private output roots.
- The path-check action called `cloud` exercises the service **locally**. It is
  not Azure dispatch, resource-enforcement qualification, or production sign-off.

For command references and scope distinctions, see [scripts](../scripts/README.md)
and [benchmarks](../benchmarks/README.md). Original 0.2.0 observations belong in
the [retrospective history](../benchmarks/VALIDATION-HISTORY.md), not a new
candidate-validation result.