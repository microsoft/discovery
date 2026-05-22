# Feedback Guide

Use [**Discussions**](https://github.com/microsoft/discovery/discussions) to file bugs, ideas, questions, and to share what you've built. Pick the matching category.

## At a glance

| What you have | Where to post it |
| --- | --- |
| A **question** about how to do something | [Discussions → Q&A](https://github.com/microsoft/discovery/discussions/categories/q-a) |
| A **bug** or unexpected behavior | [Discussions → Bugs](https://github.com/microsoft/discovery/discussions/categories/bugs) (use the Bug template) |
| A **feature idea** or improvement | [Discussions → Ideas](https://github.com/microsoft/discovery/discussions/categories/ideas) |
| A **plugin, agent, skill, MCP tool, or use case** you built | [Discussions → Show and tell](https://github.com/microsoft/discovery/discussions/categories/show-and-tell) (and a PR if you want to land it) |
| A **security vulnerability** | [MSRC](https://aka.ms/security.md/msrc/create-report) — see [SECURITY.md](../../SECURITY.md). **Do not** post in public Discussions. |

## How to file a useful bug

A great bug post makes the difference between "we need more info" and "shipping a fix." The Bug template prompts you for each of these:

1. **Microsoft Discovery version.** Either `Help → About` in the Microsoft Discovery app, or the file name of the installer you ran (`DiscoveryExpressSetup-0.13.41.exe` → version `0.13.41`).
2. **OS version** (`winver`).
3. **What you were trying to do** in one sentence.
4. **Exact steps to reproduce.** Numbered. Including any commands you typed in the `dx` CLI or in Copilot Chat.
5. **What you expected** vs **what actually happened.**
6. **Logs.**
   - Open the **Output** panel in VS Code (`Ctrl+Shift+U`) and select the **Microsoft Discovery** channel; copy the relevant tail.
   - Attach `.discovery/logs/` files from your workspace if any are present.
7. **`dx doctor` output.** From your workspace folder:

   ```powershell
   dx doctor --workspace .
   ```

8. **Screenshots or a short screen recording**, if the bug is visual.

## How to share an idea

Open a **Discussion** in the **Ideas** category. Use the structure the template suggests:

- **Problem** — what user pain are you solving? Be specific.
- **Proposal** — what you'd like to see. A sketch is fine; a full design is not required.
- **Who benefits** — what kinds of users get value from this.
- **Alternatives considered** — including "do nothing."

Ideas with clear problem statements get traction fastest.

## How to share something you've built

Open a [Discussion in **Show and tell**](https://github.com/microsoft/discovery/discussions/categories/show-and-tell) describing what you built and what it's for — workflows, prompts, notebooks, or anything you've put together on top of Microsoft Discovery.

If you'd like to land your work in the catalog, see [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the PR workflow and the per-content authoring guides.
