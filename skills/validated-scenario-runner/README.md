# Validated Scenario runner — how to load it

Start at [Validated Scenarios](../../validated-scenarios/README.md) and select a scenario.

The [SKILL.md](SKILL.md) file tells the assistant how to follow the full guide
you supply: check what is missing, request the right approvals, explain each
phase, follow the documented steps and inspect the outputs. It is not a Python
program, an app installer or a background engine. The full scenario Markdown
still specifies the inputs, model, scientific procedure and success criteria.

Use **this shared skill and the selected full guide**. Scenario-specific
requirements and acceptance criteria come from the guide.

## Use in a fresh project

1. Obtain the selected full guide and every input listed in its scenario README.
2. Put them in a fresh local folder. Open/create a Discovery project there.
3. Use the host's supported project-skill loading route for this folder, with
   `SKILL.md` at `.github/skills/validated-scenario-runner/SKILL.md` where supported.
   A file copy alone does not prove the host activated it: verify the available
   skills in a **new session**.
4. Attach the full scenario guide and send that scenario README's starting
   instruction. Let the assistant check prerequisites before installation.

If skill discovery is not available, attach this [SKILL.md](SKILL.md) explicitly
along with the guide and ask the assistant to follow both. Record **manual
skill loading** when using this fallback.

## Version and compatibility

This guide-driven runner is version **0.2.0**. Fresh-project automatic activation
and end-to-end behavior have not been validated for this version. Manual loading
must be distinguished from automatic discovery when recording a run.

## For maintainers only

See [preparing downloads](references/README.md) for exact-file verification and
local bundle creation. These utilities do not install dependencies, publish
downloads, or execute scenarios.