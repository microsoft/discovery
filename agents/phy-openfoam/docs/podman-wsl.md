# Windows Podman WSL: resource enforcement

This is an **operator-controlled** setup and repair guide, not permission for a
CFD agent to change its host. The qualified local repair used Windows x64, WSL
**3.0.5**, and the official stable Podman **6.2.0** Windows client with a matching
**6.2.0** Linux server. It did not run CFD or qualify the cloud route. See
[validation](validation.md) for the measured scope.

## The legacy-machine failure

Podman WSL machines created with the legacy bootstrap start systemd inside
nested PID/mount namespaces, rather than using WSL-native systemd. Systemd can
appear as PID 1 through Podman SSH while the actual distro PID 1 is WSL init.
On the inspected host, the visible cgroup root offered CPU, memory, and PID
controllers, but its `cgroup.subtree_control` was empty. The non-systemd subtree
and every user descendant therefore received no controllers. User-service
`Delegate` was already configured; it could not repair the missing ancestors.

Consequently, a capped container failed before its command started: `crun`
could not write `memory.max`. This is not a missing file inside OpenFOAM or proof
that the kernel lacks memory-controller support. Linux exposes the limit files
when the parent enables the controllers. Other processes in an internal cgroup
also constrain domain-controller propagation; do not blindly write cgroup
controls, move PIDs, or create replacement files.

Forcing `cgroupfs` is not a rootless resource-enforcement repair. It can allow
ordinary containers and image builds without providing the required CPU,
memory, and PID limits. Likewise, `capabilities` lists Foundation modules and
tutorials; it is **not a resource-enforcement check**.

Primary references: [Podman failure analysis](https://github.com/podman-container-tools/podman/issues/29749),
[WSL process/delegation analysis](https://github.com/microsoft/WSL/issues/41492),
[native-systemd integration](https://github.com/podman-container-tools/podman/pull/29837),
[6.2 backport](https://github.com/podman-container-tools/podman/pull/30130), and the
[kernel cgroup v2 specification](https://docs.kernel.org/admin-guide/cgroup-v2.html).

## Preserve, then provision separately

Use a supported Podman **6.2 or later** release containing WSL-native systemd
support. **Existing machines are not automatically migrated by a client
upgrade.** Do not assume recreating a machine with an old client fixes it.

1. Inventory existing machines, connections, containers, and required images.
   Preserve the old machine, its configuration/default-connection information,
   and any required image in a private archive. Do not copy credentials, signing
   keys, or old run stores into source control. Exporting an image is not a
   backup of volumes, container data, or every machine setting.
2. Obtain the intended official release from the
   [Podman release page](https://github.com/podman-container-tools/podman/releases).
   Use its supported installer or checksum-verified Windows AMD64 ZIP. A
   side-by-side ZIP preserves an existing installation; retain its companion
   executables and use the explicit new executable path. The validated ZIP
   executables were not Authenticode-signed; release checksums were verified,
   not a code-signing identity. Follow organizational installation policy.
3. Use a **new machine name**, rootless execution, and the WSL provider. Initialize
   it with the newer client; do not patch the old namespace bootstrap in place.
   Choose capacity for the case budget and unchanged concurrency policy. WSL
   shares VM resources: machine memory/CPU settings are not proof of isolated
   per-container limits.
4. Before stopping any old machine, confirm it has no running work and obtain
   the operator's maintenance approval. Stop only that machine if needed, not
   every WSL distro. Do not reset storage, delete images, switch to rootful, or
   change Docker's API pipe to repair this problem.

Illustrative PowerShell variables below use operator-chosen private locations.
`$podman` must resolve to the **new** client, not an older executable still on
`PATH`. Run the migration commands only after the preservation/maintenance
checks above:

```powershell
$podman = 'C:\work-tools\podman\usr\bin\podman.exe'
$oldPodman = (Get-Command podman).Source
$oldMachine = 'podman-machine-default'
$machine = 'phy-openfoam-native'
$image = 'localhost/phy-openfoam:0.2.1'
$archive = Join-Path $env:LOCALAPPDATA 'DiscoveryPhysics\worker-backup.oci.tar'

if (Test-Path -LiteralPath $archive) { throw 'Choose a fresh backup destination.' }
& $oldPodman --connection $oldMachine save --format oci-archive --output $archive $image
if ($LASTEXITCODE -ne 0) { throw 'Image preservation failed; stop migration.' }
$oldImageId = & $oldPodman --connection $oldMachine image inspect $image --format '{{.Id}}'
if ($LASTEXITCODE -ne 0) { throw 'Cannot record original image identity.' }

& $podman machine init --provider wsl --rootful=false --cpus 7 --memory 8192 `
    --disk-size 100 --update-connection=false $machine
if ($LASTEXITCODE -ne 0) { throw 'Native machine initialization failed.' }
# Only after confirming the old machine is idle and maintenance is approved:
& $oldPodman machine stop $oldMachine
if ($LASTEXITCODE -ne 0) { throw 'Old machine did not stop cleanly.' }
& $podman machine start --update-connection=false $machine
if ($LASTEXITCODE -ne 0) { throw 'Native machine did not start.' }

& $podman --connection $machine load --input $archive
if ($LASTEXITCODE -ne 0) { throw 'Worker image transfer failed.' }
$newImageId = & $podman --connection $machine image inspect $image --format '{{.Id}}'
if ($LASTEXITCODE -ne 0 -or $newImageId -ne $oldImageId) { throw 'Worker image identity changed.' }
```

Use a fresh archive destination; do not overwrite a required backup. Images
belong to each machine's own store. A tag existing in the old machine does not
make it available in the new one. Build the matching source on the selected
machine instead if no independently verified compatible image exists.

## Verify native boot and a bounded worker

Inspect the new machine explicitly before changing the default connection:

```powershell
& $podman machine ssh $machine 'cat /proc/1/comm; cat /etc/wsl.conf'
& $podman --connection $machine info --format json
```

Require native systemd boot, the `systemd` cgroup manager, cgroup v2, rootless
execution, and delegated `cpu`, `memory`, and `pids` controllers. Machine names
and WSL distro names can differ; prefer `machine ssh` to guessing a distro name.
Do not treat the `info` labels alone as proof. Use the actual worker image for
this small non-solver probe:

```powershell
$probe = @'
import json, os
from pathlib import Path
cg = Path('/sys/fs/cgroup')
values = {name: (cg / name).read_text().strip()
          for name in ('cpu.max', 'memory.max', 'pids.max')}
print(json.dumps(values), flush=True)
quota, period = map(int, values['cpu.max'].split())
assert quota == period
assert values['memory.max'] == '536870912'
assert values['pids.max'] == '128'
assert os.getuid() == 10001
'@
& $podman --connection $machine run --rm --pull=never --network none --read-only `
    --tmpfs /tmp:rw,size=64m --cap-drop ALL --security-opt no-new-privileges `
    --cpus 1 --memory 512m --pids-limit 128 $image python -c $probe
if ($LASTEXITCODE -ne 0) { throw 'Bounded runtime preflight failed; do not solve.' }
```

Expected kernel values are a one-core CPU quota, **536,870,912 bytes** of memory,
and **128 processes**. This probe uses neither meshing nor solver execution.
Keep its output privately and rerun after an ordinary restart of the new idle
machine. An unreadable file, absent controller, ignored limit, or nonzero exit
is an infrastructure blocker, not permission to run unbounded.

The recorded repair also used separate, deliberately small timed controls to
observe actual CPU throttling, a container-local OOM kill, and PID creation
denial. Metadata readback alone is not that behavioral test, and neither test
establishes complete production isolation or a scientifically valid prediction.

## Select the tested connection and executable

Only after the checks pass, select the tested connection using Podman's supported
configuration. Changing the default affects **other Podman clients too**:

```powershell
& $podman system connection default $machine
if ($LASTEXITCODE -ne 0) { throw 'Cannot select the tested connection.' }
```

If the approved newer client is not first on `PATH`, set only `runtime` in the
private operator configuration to its **absolute executable path**. The
[existing loader and runner](configuration.md) already support this; no package
edit is required. Do not put command arguments or a machine name into `runtime`.
Preserve `image`, `allow_unenforced_limits`, the concurrency cap, and every other
operator setting. The qualified repair left unenforced limits **disabled** and
the solve cap at **two**.

Alternatively, Podman's standard `CONTAINER_CONNECTION` can select a named
connection in the environment inherited by the CLI and Discovery. It is not a
physics-config property. A terminal-only environment change does not update an
already running app. Check for inherited Podman selection overrides before
assuming the saved default is effective. Do not invent a `PODMAN_HOST` setting.
See [configuration](configuration.md) for selection and precedence details.

Recheck the installed CLI from outside the checkout: `schema`, `capabilities`,
and health-input `lint`, plus the bounded probe above against that same runtime.
The host installer saves its own runtime/image choice; review effective
selection again after reinstalling so a side-by-side path is not unintentionally
replaced by an older `podman` found on `PATH`.

## Retention and rollback

Keep the old machine stopped but intact, with its original image and private
backup/configuration records, until the operator explicitly approves retirement.
Manage the new machine with the approved newer executable. Do not replace the
system-wide installation or change global WSL settings merely for convenience.

For an authorized rollback, first stop new work and verify the new machine is
idle. Stop only the new machine, restore the saved runtime selection/default
connection, and start the old machine with its original supported client.
Do not restore an entire old connection file over unrelated subsequent changes.
Rollback restores the previous environment; it does **not** make its missing
controllers safe for CFD. Keep the fail-closed policy in place and preserve
failed receipts. Never use disabled cgroups or an unenforced-limit opt-in as the
repair, and do not rewrite old signed scientific records.