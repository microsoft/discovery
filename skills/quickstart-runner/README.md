# QuickStart runner — how to load it

**Looking to run a scenario? Start at [QuickStart Scenarios](../../quickstarts/README.md)
and select its README. This folder is the shared skill source, not a separate
scientific workflow.**

The [SKILL.md](SKILL.md) file tells the assistant how to follow the full guide
you supply: check what is missing, request the right approvals, explain each
phase, follow the documented steps and inspect the outputs. It is not a Python
program, an app installer or a background engine. The full scenario Markdown
still specifies the inputs, model, scientific procedure and success criteria.

## Why this folder exists

The repository keeps reusable skills under `skills/<skill-name>/`. This one
copy can support several QuickStart Scenarios without duplicating setup rules
inside every scenario. Links from the QuickStart home page and scenario READMEs
bring customers here directly; its storage location does not mean they should
know to browse the skills catalog first.

For the guided route, use **this shared skill and the selected full guide**.
The original SiPhy skill is a separately retained reference/variant, not another
mandatory step. File presence alone does not register the shared skill or prove
it has run successfully. No extra profile or requirements copy is needed.

## Use in a fresh project

1. Obtain the selected full guide and every input named on its files page.
2. Put them in a fresh local folder. Open/create a Discovery project there.
3. Use the host's supported project-skill loading route for this folder, with
   `SKILL.md` at `.github/skills/quickstart-runner/SKILL.md` where supported.
   A file copy alone does not prove the host activated it: verify the available
   skills in a **new session**.
4. Attach the full scenario guide and send that scenario README's starting
   instruction. Let the assistant check prerequisites before installation.

If skill discovery is not available, attach this [SKILL.md](SKILL.md) explicitly
along with the guide and ask the assistant to follow both. Record **manual
skill loading**, not a passed automatic-discovery test. The route must work
without a skill already in the contributor's personal profile.

The author-prepared local review downloads include the project-scoped skill
file and a visible copy with the instructions. They do not create a project,
install Python/packages, index a corpus or start scientific work for you.

## Which version?

This shared adaptation retains the original runner's setup banner, phase
explanations, ordered validation and mode choices, but reads the selected full
guide instead of an embedded CoreSPI profile. [The original scenario skill](../../quickstarts/siphy/skill%201.md)
is preserved unchanged. SiPhy v1.1 supersedes conflicting older prompt,
Bookshelf and connection instructions; do not silently treat the old skill as
validated against the newer guide.

## For maintainers only

The download helper and its file-hash records are under this skill's `scripts`,
`tests` and `references` directories. They are not extra customer forms.
See [preparing downloads](references/README.md) for exact-file verification,
local bundle creation and the still-required public-upload/rights decisions.