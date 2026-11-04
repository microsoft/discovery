# Skill Authoring Guide

> **Audience:** Anyone authoring an agent skill for the Discovery catalog. Skills package a reusable workflow — instructions plus optional scripts, templates, and references — that an agent loads on demand when a task calls for it.
>
> **Scope:** Defining and submitting a skill under `skills/<skill-name>/`. Discovery skills follow the open [Agent Skills](https://agentskills.io) standard, so the [Agent Skills specification](https://agentskills.io/specification) applies in full; this guide covers only what is specific to this repository.

For agent authoring, see [`agent-authoring-guide.md`](./agent-authoring-guide.md). For starter-kit authoring, see [`starter-kit-authoring-guide.md`](./starter-kit-authoring-guide.md).

---

## 1. Overview

An **agent** is a persona with tools. A **skill** is a capability any agent can pick up: "build an arxiv-ready paper", "estimate a token budget", "add the catalog agents to my workspace". If you find yourself walking an agent through the same multi-step workflow more than once, that workflow is a skill.

Agents discover skills progressively:

1. **Metadata** — every skill's `name` and `description` are loaded at startup (~100 tokens each).
2. **Instructions** — the full `SKILL.md` body is loaded only when the skill is activated.
3. **Resources** — files in `scripts/`, `references/`, or `assets/` are read only when the instructions point to them.

Write with that in mind: the `description` decides *whether* the skill is used; the body decides *how well*.

---

## 2. The fastest way to author a skill

Most good skills are harvested from real work, not written from scratch. In practice this loop works very well:

1. **Do the work in the Discovery app.** Chat with an agent about a topic, build the visualization, generate the artifact.
2. **Notice the repetition.** You have had this kind of conversation, built this kind of figure, or produced this kind of artifact more than once.
3. **Ask the agent to distill it.** Once you are happy with the result, say:

   > Review this session and construct a reusable agent skill that can be used by future projects.

4. **Refine and test.** Read the generated `SKILL.md` critically, trim anything session-specific, then try it in a **new** session on a **different** project. If it works without the original context, it is ready.

Results vary by model; a strong reasoning model gives the best first draft. Expect to edit — especially the `description` (§5) and anything that hard-codes paths, names, or data from the original session.

---

## 3. Folder layout

```text
skills/
└── build-research-paper/
    ├── SKILL.md              # Required
    ├── README.md             # Optional; human-facing install and usage notes
    ├── scripts/              # Optional; executable helpers the agent runs
    ├── references/           # Optional; detail loaded on demand
    └── assets/               # Optional; templates, schemas, example data
```

- The folder name must match the `name` field in `SKILL.md`.
- Only `SKILL.md` is required. Add other folders only when they earn their place.
- Reference bundled files with relative paths from the skill root (for example, `[patterns](references/patterns.md)`) and keep references one level deep.

---

## 4. `SKILL.md` frontmatter

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | 1–64 chars, lowercase `a-z`, `0-9`, and single hyphens. Must match the folder name and be unique across `skills/`. |
| `description` | Yes | 1–1024 chars. What the skill does **and** when to use it (see §5). |
| `license` | Recommended | SPDX identifier, for example `MIT`. |
| `compatibility` | Optional | ≤ 500 chars. Environment needs: required CLIs, runtimes, network access, or a specific product. |
| `metadata` | Optional | String key/value map. Recommended keys: `author`, `version`. |
| `allowed-tools` | Optional | Experimental; support varies by agent host. |

```markdown
---
name: build-research-paper
description: |
  Build arxiv-ready research paper PDFs from LaTeX or markdown plus PNG
  figures using tectonic (default) or pandoc. WHEN: write a research paper,
  arxiv submission, LaTeX paper, referee revision, publication-quality figures.
license: MIT
compatibility: Requires tectonic or pandoc on PATH; Python 3.10+ for figures.
metadata:
  author: Your Name
  version: "1.0.0"
---

# build-research-paper

## When to use
...

## Procedure
1. ...
2. ...

## Pitfalls
...
```

---

## 5. Writing a good skill

### Description

- Lead with the outcome in one sentence, then list trigger phrases a scientist would actually type (`WHEN: ...`).
- Include domain keywords (assay names, file formats, instruments, codes) so the agent can match intent.
- Say what the skill is **not** for if it is easily confused with another skill or agent.

### Body

- Keep `SKILL.md` under ~500 lines. Move long reference material into `references/`.
- Write steps the agent can execute, not essays. Numbered procedures, expected inputs and outputs, and a short "pitfalls" section work best.
- Prefer bundled scripts over asking the model to re-derive logic each time. Scripts should document their dependencies and fail with clear messages.
- Generalize. Replace project-specific paths, sample IDs, dataset names, and people with parameters or placeholders.
- Do not duplicate what frontier models already do well. A skill should add a specialized workflow, domain constraint, or hard-won lesson.

### Scientific integrity

- If the skill produces results, figures, or text, tell the agent to record provenance (inputs, versions, parameters) and to flag uncertainty rather than invent values.

---

## 6. What we accept

### Good fits

- Repeatable scientific workflows: analysis pipelines, figure and report generation, data wrangling for common formats.
- Discovery-specific workflows: working with catalog agents, starter kits, Bookshelf, or Discovery services.
- Cross-domain research practice: literature review, paper preparation, reproducibility checks.

### Not accepted

- Content that bypasses security controls, Responsible AI policies, or platform terms of service.
- Secrets, credentials, customer data, unpublished or controlled data, or personal information — including in examples.
- Skills that only restate generic model behavior with no meaningful uplift.
- Compiled binaries or large data files. Keep bundled assets small and text-based where possible.

---

## 7. Testing

Before opening a PR:

- [ ] Validate the frontmatter with the Agent Skills reference validator: `skills-ref validate skills/<skill-name>` (see [skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref)).
- [ ] Install the skill into a clean workspace and trigger it from a **new** chat using only a natural prompt — confirm the agent picks it up from the `description` alone.
- [ ] Run every bundled script at least once from a clean environment.
- [ ] Remove session leftovers: absolute paths, usernames, tenant or subscription IDs, sample data that is not yours to share.

---

## 8. Submitting a pull request

```bash
# 1. Fork https://github.com/microsoft/discovery in the GitHub UI.
git clone https://github.com/<your-org>/discovery.git
cd discovery
git remote add upstream https://github.com/microsoft/discovery.git
git fetch upstream && git merge upstream/main

# 2. Create your skill folder
git checkout -b add-my-skill
mkdir skills/my-skill
# … create SKILL.md and any optional scripts/, references/, assets/ …

# 3. Open the PR
git add skills/my-skill
git commit -m "feat: add my-skill skill"
git push origin add-my-skill
```

Open one PR per skill. In the PR description, say what the skill does, how it was produced (for example, distilled from a Discovery app session), and how you tested it.

Read the required checks and source run logs, then address findings in follow-up commits. Bundled scripts are executable content and may need maintainer or CODEOWNER review beyond the standard catalog checks. See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the general PR lifecycle.

---

## 9. Reference

| Resource | Link |
|---|---|
| Agent Skills overview | <https://agentskills.io> |
| Agent Skills specification | <https://agentskills.io/specification> |
| `skills-ref` validator | <https://github.com/agentskills/agentskills/tree/main/skills-ref> |
| Example skills in this repo | [`skills/`](../../skills/) |
