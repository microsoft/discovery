# QuickStart runner — how to load it

This is the **one shared runner** linked from the
[QuickStart Scenarios](../../quickstarts/README.md) home page. The original
scenario guide remains the full source of setup, prompts and scientific checks.
You do not need to open a profile or requirements copy to use it.

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

This shared adaptation retains Joe's setup banner, phase explanations, ordered
validation and mode choices, but reads the selected full guide instead of an
embedded CoreSPI profile. [Joe's original skill](../../quickstarts/siphy/skill%201.md)
is preserved unchanged. SiPhy v1.1 supersedes conflicting older prompt,
Bookshelf and connection instructions; do not silently treat the old skill as
validated against the newer guide.

## For maintainers only

The download helper and its file-hash records are under this skill's `scripts`,
`tests` and `references` directories. They are not extra customer forms.
See [preparing downloads](references/README.md) for exact-file verification,
local bundle creation and the still-required public-upload/rights decisions.