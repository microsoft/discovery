# QuickStart Scenarios runner

This proposed shared skill guides an already selected, versioned scenario.
It is **not a tested turnkey release** and is not Engineering's test harness.
The four packages are listed in [QuickStart Scenarios](../../quickstarts/README.md).

## Source and changes

Joe's supplied `quickstart-siphy-spec2rtl-1` is the starting design: setup
banners, phase cards, sequential validation, mode choices and failure reports.
This adaptation removes its embedded CoreSPI profile and report dependency,
keeps scenario rules in four separate profiles, supports declared local-command
steps, and separates asset/setup/compute approvals. It fixes the prototype's
conflicting generic retry rule, output-root rule and install-before-unpack
ordering. Owner review of this adaptation is still needed.

## Getting started

Follow the [getting-started guide](../../quickstarts/GETTING-STARTED.md).
The canonical skill source is here, not a contributor's personal installation.
The staging helper creates a project-scoped activation shim and copies the
canonical runner and selected-scenario record into a fresh folder.

Opening that folder is not proof the App loaded the skill. Verify the runtime
catalog in a new chat. If automatic discovery is unavailable, explicitly attach
the canonical skill and scenario guide and record that manual-loading route.
No product-native scenario picker, automatic registry integration or successful
App activation is claimed by this skeleton.

## Offline helper

[`package_scenario.py`](scripts/package_scenario.py) uses only Python 3.10+
standard library. It has no network calls or scientific subprocesses.

From a repository checkout:

```console
python skills/quickstart-runner/scripts/package_scenario.py validate
python skills/quickstart-runner/scripts/package_scenario.py validate --release
python skills/quickstart-runner/scripts/package_scenario.py stage --scenario biopharma --destination ../quickstart-review --allow-draft
```

The first command validates packaging. The second must remain blocked while
release requirements are incomplete. Staging is a dry-run until `--apply` is
added; the destination must not already exist. `--allow-draft` means author
inspection only. It never authorizes installation, indexing or computation.

For pre-acquired input files, `verify-assets --scenario <id> --source <folder>`
checks sizes and SHA-256 without extracting archives or loading models.
Asset URLs and licence evidence are inventoried; this helper does not download
or approve redistribution. Preserve required asset filenames in the source
folder. Included text manifests are checked in their scenario folder.

## Testing and limits

```console
python -B -m unittest discover -s skills/quickstart-runner/tests -v
```

Tests exercise temporary fixtures and real copy/hash behavior, not mock model
claims. They do not prove runtime skill activation, authenticated tools,
scientific completion or a clean OS installation. Symlink tests may skip where
the host lacks permission. Link checks verify local targets, not remote
availability or Markdown heading anchors. A worktree is not a security sandbox.

The proposed top-level package and this executable helper require maintainer
review; no trusted workflow, registry or policy is changed by this PR.