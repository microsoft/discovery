# Getting started with QuickStart Scenarios

**Author preview only.** The current four packages have explicit release
blockers. You can inspect and stage them without installing scientific tools.
Do not promise an external customer a successful run until the selected
scenario's required inputs, setup and validation are complete.

## 1. Obtain the source

Obtain the repository revision containing these files, by checkout or its
repository archive. This proposal is not a released scenario catalog entry.
Do not point customers at a nonexistent GitHub release. Compare the selected
revision with the scenario's component pins; changing pins needs revalidation.

The repository's [Discovery install guide](https://github.com/microsoft/discovery/blob/88a2a1cd1664b7d609659dc86c65f7f632686715/docs/discovery-app/install.md)
documents Windows x64, Windows ARM64, macOS ARM and RHEL x64 app distribution.
That does **not** validate the scientific stack of each scenario on each
platform. Record the App build, model, OS, CPU architecture and interpreter.
Any sign-in/MFA is completed by the user in their external browser; never put
credentials in chat or transfer browser cookies.

## 2. Select a scenario and inspect its requirements

Choose [SiPhy](siphy/README.md), [BioPharma](biopharma/README.md),
[CMS](cms/README.md), or [Bookshelf](bookshelf/README.md). Read its current
status and asset/component inventory before any installation. The public SCLC
Bookshelf is a separate scenario, not a replacement for the CMS or SiPhy corpus
or an internal leukemia benchmark.

## 3. Stage a new author-review folder

The packaging helper needs Python 3.10+ only; this is **not** a scientific
runtime pin. If Python is absent, obtain an approved Python runtime using the
publisher's instructions before using this offline helper. That bootstrap step
is currently manual and is not a validated no-Python customer experience.

From the repository root, using an available Python executable:

```console
python skills/quickstart-runner/scripts/package_scenario.py validate
python skills/quickstart-runner/scripts/package_scenario.py stage --scenario biopharma --destination ../biopharma-review --allow-draft
```

The second command is a no-write plan. After reviewing it, add `--apply` to
create that new folder. Use a short path, never an old campaign, and never a
destination inside this checkout. Change the scenario and destination for
another package. Existing folders are rejected rather than overwritten.

The staged folder includes the guides, inventories, canonical runner and a
project-scoped skill shim. It does **not** contain installed software, a
Discovery project, sessions, old results or downloaded scientific assets.
It keeps all four guide folders for working navigation, with exactly one
selection record. Available canonical agents/tools remain pinned references,
not hidden copies from an author's environment.

## 4. Create/open a fresh Discovery project

In Discovery, choose the supported new/local-project action for your App
build and select the staged folder. A folder picker normally hides files;
an empty listing does not mean the folder is empty. If prompted to initialize
the folder as a project, review and approve that action. UI wording varies by
build; no automation of project creation is claimed here.

Start a new chat, select the model required by the scenario, and confirm the
project-scoped `quickstart-runner` is in the host's available skills. Reading
a file or copying it is not evidence that the host activated it. The skill
shim points to the bundled canonical runner; it never uses a personal skills
folder.

If the host does not discover the shim, attach/read the bundled canonical
runner and selected scenario guide explicitly, then record **manual loading**.
Do not claim this fallback proves automatic skill discovery. Missing local
file/command or required agent/tool capability is a blocker, not permission to
invent a runtime interface or change grants.

## 5. Use one starting instruction

Attach the selected guide, then send:

> Use the bundled quickstart-runner to inspect the selected QuickStart
> Scenario. Report readiness and blockers first. Do not install, index or run
> anything without the separate approvals required by the guide.

For this draft, expect an honest blocker report. Once the approved scenario
inputs and release conditions are satisfied, the same runner handles its
fixed setup/execute/check sequence. One-shot means one entry point and no
undocumented engineering work, not automatic agreement to cost or data actions.

Review each file/terminal permission prompt; approve only the disclosed action
within the intended scope. Do not click Allow indiscriminately. Dependencies,
installation, indexing and scientific execution remain distinct decisions.

## 6. Observe and validate

Keep the original prompt, assets and version choices fixed. Verify actual
tool results, native artifacts and citations against the owner's criteria.
If a required tool route fails, a fallback does not make that check pass.
Historical results are comparison evidence, not outputs of your new run.
Record setup/indexing/run/validation time separately, including user wait time.

On failure, preserve logs and partial outputs and stop at the documented gate.
No automatic environment removal, runtime downgrade, retry, deployment or
lock deletion is authorized. See each profile for recovery and exclusions.

## 7. Author checks before external release

```console
python skills/quickstart-runner/scripts/package_scenario.py validate --release
python -B -m unittest discover -s skills/quickstart-runner/tests -v
```

Release validation must remain blocked for incomplete scenarios. No automated
check can grant redistribution rights or turn a proposed prompt into owner
approval. Complete the genuine fresh-project run and required scientific review
before publishing a ready designation. See [Authoring](AUTHORING.md).