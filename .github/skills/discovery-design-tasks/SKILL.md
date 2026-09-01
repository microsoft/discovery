
​---
name: discovery-design-tasks
description: "Generate a Microsoft Discovery task design (markdown only) for a user-specified local-app or cloud-service Foundry agent set using one (or all) of the three advanced investigation patterns: Deterministic, Guided Exploration, and Autonomous Research. For cloud-service task design or task creation, first look for a Discovery MCP server or Discovery proxy to resolve cloud workspaces, projects, agents, investigations, and tasks; if none is available, try Azure CLI before asking the user for another access route. Use when asked to plan a Discovery investigation, draft task trees, or choose an investigation pattern for an existing agent set."
argument-hint: "Optional: --target local|cloud  --agents all|select  --pattern deterministic|guided|autonomous|all  --out <folder>"
user-invocable: true
---

# Discovery Task Design

> **This skill produces a markdown task design file and must never overwrite an existing `task-design.md`.**

## What This Skill Does

Generates a `task-design.md` document that describes a Discovery investigation using one or all of the three patterns from the [Microsoft Discovery advanced investigation patterns](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-advanced-investigation-patterns) documentation:

- **Deterministic Investigation** — fully specified parent + numbered subtasks with explicit agents and dependencies.
- **Guided Exploration** — high-level phases with broad validation; cognition picks agents inside each phase.
- **Autonomous Research** — single root-task prompt with validation requirements only.

The full canonical markdown example is embedded in **Appendix A** at the bottom of this file — use it as the byte-for-byte structural reference.

## Inputs to Collect

Before generating anything, gather these inputs (use the ask-questions tool if any are missing or ambiguous — do NOT guess). Reuse values already present in the conversation or active editor when possible. Collect the Discovery target first by itself; if the user chooses **Discovery cloud service**, ask the cloud workspace, project, and investigation name in the next question before asking for the objective, pattern, or output folder.

| Input | Required | Notes |
|---|---|---|
| **Discovery target** | Yes | Ask whether the task design is for the **Discovery local app** or the **Discovery cloud service**. |
| **Cloud access route** | Conditional | Required only when **Discovery target** is cloud service. Look for an available Discovery MCP server or Discovery proxy before resolving cloud workspaces, projects, agents, investigations, or tasks. If none is available, try Azure CLI (`az`) before asking the user to connect/provide another route. |
| **Cloud workspace/project/investigation** | Conditional | Required only when **Discovery target** is cloud service. Ask for the workspace name, project name, and investigation name. Use the workspace/project to resolve Foundry agents; use the investigation name as the task destination. |
| **Agent selection mode** | Yes | After resolving the available agents for the chosen target, choose the best-fit agents for the user's objective. Ask for manual selection only if the user explicitly requests it or if the objective is too ambiguous to choose responsibly. This applies to both Discovery local app and Discovery cloud service, and to both task designs and task creation. |
| **Agent set** | Yes | Name + one-line role for each best-fit or user-selected agent. For cloud-service designs and task creation, derive the available list from the Foundry agents in the specified workspace/project. Do not use the local catalog, local `.github/agents`, or an investigation-scoped list as the cloud task-design source. Always exclude any agent whose exact name is `Discovery`. |
| **Investigation objective** | Yes | The scientific goal, target molecules, therapeutic area, dataset, or open-ended question. |
| **Pattern(s)** | Yes | `deterministic`, `guided`, `autonomous`, or `all`. Default to `all` if the user just asks for "a task design". |
| **Task creation pattern** | Conditional | Required when creating tasks from an existing `task-design.md` that contains more than one pattern example. Inspect the design first, list the available patterns found, and ask the user to choose exactly one before creating any tasks. Do not default to deterministic in this case. |
| **Output folder** | Yes | Where to write the task design. Default: `tasks` in the current workspace. If `task-design.md` already exists in that folder, preserve it and write a timestamped sibling file named `task-design-YYYYMMDD-HHMMSS.md` instead. |

## Agent Source Resolution

Always resolve the Discovery target before resolving the agent set:

- **Discovery local app** — look for available agents in the workspace's `.github/agents` folder. Read the `.agent.md` files there to identify agent names and one-line roles. If the folder is missing or no matching agents are present, surface the mismatch before generating tasks.
- **Discovery cloud service** — ask the user for the cloud workspace name, project name, and investigation name. Before making any cloud lookup or mutation, look for a connected Discovery MCP server or Discovery proxy that can list workspaces/projects, Foundry agents, investigations, and tasks. Prefer that MCP/proxy for all cloud-service resolution and task creation. If no Discovery MCP server/proxy is available, check whether Azure CLI (`az`) is installed and authenticated, then try to resolve the same cloud resources through Azure CLI commands before asking the user for another route. Resolve the available agent list from the **Foundry agents in that cloud workspace/project**, not from the local catalog, local `.github/agents`, or an investigation-scoped list. Then look up the named investigation in the project: if it exists, create the task design for that existing investigation; if it does not exist, create a new investigation with that exact name before creating tasks. If neither a Discovery MCP/proxy nor Azure CLI can resolve the service, report what is missing and ask the user to connect a Discovery MCP server/proxy, sign in/configure Azure CLI, provide proxy details, or switch to **Discovery local app**. If the user has not supplied the workspace, project, and investigation name, ask before generating tasks.
- If the user explicitly provides an agent list, still ask for the Discovery target so the generated design is grounded in the correct runtime context, then verify the requested agents against the resolved available list for that target.
- In every target mode and source path, remove any agent whose exact name is `Discovery` from the resolved available list and from any user-provided selection before writing task designs or creating tasks. Never list `Discovery` in **Available Agents**, assign it to a deterministic task, mention it as a selectable agent for guided/autonomous work, or create a cloud task assigned to it.
- After the available list is resolved and filtered, select only the best-fit agents for the user's objective. Use the agents whose tools, data sources, or reasoning capabilities directly contribute to evidence retrieval, computation, validation, synthesis, or reporting for the stated investigation. Do not include broad catalog capacity in **Available Agents** just because it exists.
- If the user explicitly asks to use all agents, force every selected agent into the design only when the objective can support meaningful task assignments for each one; otherwise explain the mismatch and ask whether to broaden the objective or proceed with the best-fit subset.
- If the user explicitly asks to select specific agents, present the filtered available agents by name and role using a multi-select question or allow typed names. Validate exact names against the filtered available list and surface any mismatch before generating tasks.
- If the objective is too ambiguous to identify best-fit agents, ask one focused clarification question about the scientific goal before generating tasks.

## Cloud MCP / Proxy / Azure CLI Resolution

For **Discovery cloud service** targets, always establish the service access route before designing or creating cloud tasks. Prefer a Discovery MCP server/proxy; use Azure CLI as the fallback route when no MCP/proxy is available.

The canonical Discovery MCP endpoint is `https://mcp.discovery.azure.com/mcp`. For scripted runs in this workspace, use the local stdio proxy pattern from `.vscode/discovery-mcp-proxy.ps1` before trying Azure CLI. The proxy mints an Entra token for `https://discovery.azure.com`, forwards JSON-RPC requests to `https://mcp.discovery.azure.com/mcp`, preserves the `Mcp-Session-Id`, and avoids waiting for VS Code to surface deferred `mcp_microsoft-dis_*` tools mid-session.

1. Search the available tool catalog / MCP registry for a callable Discovery MCP server or Discovery proxy. Use likely names and keywords such as `discovery`, `microsoft discovery`, `foundry`, `workspace`, `project`, `investigation`, `tasks`, `mcp`, and `proxy`. Also check whether `.vscode/discovery-mcp-proxy.ps1` exists; if it does, invoke `https://mcp.discovery.azure.com/mcp` through that proxy directly rather than waiting for VS Code MCP tools to appear.
2. If more than one candidate is available, choose the one that explicitly exposes Discovery cloud workspaces/projects, Foundry agents, investigations, and task creation APIs. If the capabilities are ambiguous, ask the user which Discovery MCP/proxy to use.
3. Use the selected MCP/proxy to resolve the cloud workspace and project, list the project's Foundry agents, resolve or create the target investigation, and create cloud tasks when task creation is requested. When using the scripted proxy path, send MCP `initialize`, `notifications/initialized`, then `tools/list` to discover the exact task and investigation tool names before calling `tools/call`.
4. If no Discovery MCP/proxy is available, try Azure CLI before stopping:
    - Check for `az` with `Get-Command az` or equivalent.
    - Check authentication and selected tenant/subscription with `az account show`.
    - If needed and non-interactive account context is unavailable, ask the user which subscription, resource group, workspace, or project values to use. Do not request secrets.
    - Use installed Azure CLI commands or extensions that can list Discovery/Foundry workspaces, projects, agents, investigations, and tasks. If the required command group or extension is missing, try `az extension list-available` / `az extension add` only when the extension name is known from Azure CLI output or official command discovery; otherwise ask the user for the expected CLI extension or proxy route.
    - Use Azure CLI output only when it confirms the cloud workspace/project, Foundry agent list, and investigation destination. Do not infer missing cloud objects from local files.
5. Do not fall back to the local `discovery_catalog`, local `.github/agents`, cached examples, or guessed agent names for cloud-service designs unless the user explicitly switches the target to **Discovery local app**.
6. If neither a Discovery MCP/proxy nor Azure CLI can resolve the service, stop before generating the cloud task design and tell the user what is missing. The user can connect a Discovery MCP server/proxy, sign in/configure Azure CLI, provide proxy details, or switch the target to **Discovery local app**.

## Cloud Task Creation Protocol

When the user asks to create cloud tasks from a task design, use the Discovery MCP `CreateOrUpdateInvestigation`, `CreateTask`, `UpdateTask`, `ListTasks`, and optionally `AddTaskComment` tools through the selected MCP/proxy. Do **not** use the local `tasks` tool for cloud-service task creation.

Before creating cloud tasks from an existing `task-design.md`, inspect the file for pattern sections. If it contains more than one pattern example, such as **Pattern 1: Deterministic Investigation**, **Pattern 2: Guided Exploration**, and **Pattern 3: Autonomous Research**, ask the user which single pattern to instantiate. The user must choose before any investigation or task mutation occurs. Do not infer the pattern from the first section and do not default to deterministic unless the design contains only the deterministic pattern or the user explicitly chose it.

After the pattern is selected, create tasks according to that selected section only:

- **Deterministic Investigation** — create the parent container and numbered subtasks with explicit assignees and dependencies.
- **Guided Exploration** — create the phases as tasks with phase dependencies and validation requirements; assign agents only when the selected design explicitly locks an agent for a phase.
- **Autonomous Research** — create one root task from the root prompt and validation requirements; do not expand it into deterministic subtasks unless the user asks for decomposition.

Cloud task creation must use the same best-fit or user-selected agent set resolved for the design. Never assign a task to an agent outside that selected set.

For **Deterministic Investigation** task creation, use this order to avoid corrupt parent dependencies:

1. Create or update the target investigation first. If the user supplied an investigation display name containing spaces, derive a service-safe investigation name by lowercasing and replacing spaces with hyphens, for example `synthesize ibuprofen` -> `synthesize-ibuprofen`; keep the original as `displayName`.
2. Create the parent task as a pure container. The parent `CreateTask` call must include only title, description, priority, and validation requirements. It must **not** include `dependsOnJson`, `relatedToJson`, `parentId`, or an assignee.
3. Capture every MCP-created task's service `name` from the raw MCP text payload. Do not rely on local variables populated through `Get-DiscoveryMcpText` unless the parsed object is verified non-null; raw MCP responses often place JSON inside `result.content[0].text`.
4. Create subtasks with assignees and validation requirements. Prefer dependency edges on subtasks, not on the parent. If a `CreateTask` call containing both `parentId` and `dependsOnJson` fails, retry by creating the subtask without `parentId`, then set `parentId` with `UpdateTask` after dependencies are created.
5. Never use parent `dependsOnJson` to represent child ordering. Parent dependencies make the parent depend on children and can cause misleading or stale dependencies if a child task is later removed and recreated. If a parent task ever has a non-empty `dependsOn` list after child creation, immediately clear it with `UpdateTask` and `dependsOnJson='[]'`.
6. If a child dependency edge fails with an opaque MCP error, retry once using `UpdateTask` after the child has been created and parented. If it still fails, add an `AddTaskComment` entry to the child that records the intended dependency order. Do **not** move the failed dependency to the parent as a workaround.
7. If a task was created incorrectly, use `UpdateTask` with `status='Removed'` rather than creating a second active copy with the same title. When a replacement is required, mark the incorrect task `Removed` first, create the replacement, then verify that only one active task exists for each subtask title.
8. Finish with `ListTasks` for the investigation. Verify all of the following before reporting deterministic task-creation success: the parent has `parentId=null`, the parent has `dependsOn=[]`, each active child has `parentId=<parent task name>`, every active child has the intended assignee, removed attempts are explicitly identified if any exist, and every dependency edge is either present on the child or documented in a child comment.

## Procedure

1. Resolve the Discovery target first. Ask only whether the user wants to design tasks for the **Discovery local app** or the **Discovery cloud service**; do not batch this with the remaining inputs.
2. If the target is **Discovery cloud service**, immediately ask for the cloud workspace name, project name, and investigation name in a follow-up question. Do not ask for the objective, pattern, or output folder until all three values are known.
3. If the target is **Discovery cloud service**, look for a Discovery MCP server or Discovery proxy and select the best available candidate before resolving agents, investigations, or cloud tasks. If none is available, try Azure CLI (`az`) as the fallback cloud route. Stop only if neither MCP/proxy nor Azure CLI can resolve the workspace/project, Foundry agents, and investigation destination.
4. Resolve the available agent source:
  - For **Discovery local app**, inspect `.github/agents` and derive the available agent list from the `.agent.md` files.
  - For **Discovery cloud service**, use the selected Discovery MCP/proxy or Azure CLI plus the workspace and project to list the project's Foundry agents. If the user supplied requested agents, verify that each requested agent appears in the project's Foundry agents before generating tasks.
  - Remove any agent whose exact name is `Discovery` from the resolved available list and from any user-provided selection. If this leaves no usable agents, surface that mismatch before generating tasks.
5. For **Discovery cloud service**, use the selected Discovery MCP/proxy or Azure CLI to resolve the investigation destination by name inside the specified project. Use an existing investigation when the name already exists; otherwise create a new investigation with that exact name before creating tasks. The investigation name does not constrain the agent inventory.
6. Resolve the agent set:
  - If the user has not already chosen specific agents, choose only the best-fit agents for the objective from the filtered available list.
  - Include only those best-fit or user-selected agents in **Available Agents**.
  - If the user asks to use all available agents, include all filtered agents only when every one has a meaningful role in the objective; otherwise ask whether to broaden the objective or proceed with the best-fit subset.
  - If the user asks to select specific agents, show the filtered available agents with names and one-line roles and collect a multi-select or typed list. Validate every selected name against the filtered available list before continuing.
7. Resolve the remaining inputs above.
8. Create the output folder if it does not exist.
9. Choose the output file path without overwriting existing work:
  - If `<output folder>/task-design.md` does not exist, write `<output folder>/task-design.md`.
  - If `<output folder>/task-design.md` already exists, do not modify or replace it. Write a new sibling file named `task-design-YYYYMMDD-HHMMSS.md`, using the current local timestamp.
  - Never delete, truncate, rename, or overwrite an existing `task-design.md` as part of this skill.
10. Write the selected task design file with this structure (omit any pattern section the user did not request):

    ````
    # <Topic> Task Design

    Task designs for the <agent-set-label> agents using the three advanced
    investigation patterns defined in the [Microsoft Discovery advanced
    investigation patterns](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-advanced-investigation-patterns) documentation.

    ## Available Agents
    | Agent | Role |
    |---|---|
    | `<AgentName>` | <one-line role> |
    ...

    ## Pattern 1: Deterministic Investigation
    <when-to-use sentence tailored to the objective>
    ```
    Parent: Parent task : <parent title>
        Description: <parent description>
        Validation: <validation summary>

      Task 1: Subtask 1: <title>
        Agent: <AgentName>
        Description: "<quoted description>"
        Depends on: (none) | Task N[, Task M]
        Validation: "<comma-separated requirements>"
      ...
    ```
    ### Notes
    - <2–4 bullets tailored to the objective>

    ## Pattern 2: Guided Exploration
    <when-to-use>
    ```
    Phase 1: "<phase title>"
      Depends on: (none) | Phase N
      Validation: "<requirement 1>"
                 "<requirement 2>"
    ...
    ```
    ### Notes
    - <bullets>

    ## Pattern 3: Autonomous Research
    <when-to-use>
    ```
    Root task:

    <root prompt referencing the objective>
    ---
    Validation: <inline summary>
    ---
    - <bulleted validation requirement>
    - ...
    ```
    ### Notes
    - <bullets>

    ## Choosing the Right Pattern
    | | Deterministic | Guided Exploration | Autonomous Research |
    |---|---|---|---|
    | You know the exact steps | Yes | Partially | No |
    | Who selects agents | You (explicit assignment) | You guide phases, cognition selects within them | Cognition selects for all tasks |
    | Upfront setup effort | High | Medium | Low |
    | Cognition autonomy | Low (execute and validate) | Medium (decompose within phases) | High (plan and execute everything) |
    | Reproducibility | High | Medium | Lower |
    | Best for | Known screening pipelines, repeatable protocols | Phased <domain> with known direction | Exploratory <domain> investigation |

    ### Mixing Patterns

    You can combine patterns within a single investigation. For example:

    - Use **Deterministic** for the data preparation phase (strict validation on known inputs).
    - Switch to **Guided Exploration** for the analysis phase (letting cognition decide between alternative workflows).
    - Use **Autonomous Research** for a follow-up investigation where cognition evaluates unexpected results discovered during analysis.
    ````

11. Authoring rules for the patterns:
  - **Deterministic** — produce a parent + as many numbered subtasks as the objective requires for a complete, executable investigation. Do not impose a fixed maximum such as 6 tasks. Prefer one coherent task per distinct work product, dependency boundary, specialized agent handoff, or validation gate. Prefix the parent task title with `Parent task : ` and each subtask title with its matching `Subtask N: ` prefix inside the title text. Each subtask must name exactly one agent from the selected agent set, list explicit `Depends on:` lines, and give 1 to 4 comma-separated `Validation:` requirements. If the user selected specific agents, make sure every selected agent appears in at least one task unless the user said otherwise. Never assign a task to an agent named exactly `Discovery`.
    - **Guided Exploration** — produce 2 to 4 phases. Phase titles must reference the objective. Validation requirements (2 to 4 per phase) must be measurable but not name specific agents unless the user wants to lock one in (mention this option in the Notes).
    - **Autonomous Research** — produce a single, detailed root-task prompt that names the objective, the workflow style if known (single-step vs. multi-step, etc.), the criteria to weigh, and the form of the expected recommendation. Follow it with both an inline `Validation:` line and a bulleted list of validation requirements (matching the template's twin format).
12. Open the generated task design file in the editor so the user can review it. End your turn after the markdown is written.

## Creating Tasks From an Existing Design

When the user asks to create local or cloud tasks from an existing `task-design.md`, inspect the design before creating or updating any tasks:

1. Identify which pattern sections are present by heading: **Pattern 1: Deterministic Investigation**, **Pattern 2: Guided Exploration**, and/or **Pattern 3: Autonomous Research**.
2. If more than one pattern section is present, ask the user to choose exactly one pattern to instantiate. Use options for the patterns actually present in the file. Do not create tasks, create investigations, or mutate existing tasks until the user answers.
3. If exactly one pattern section is present, use that pattern without asking again unless the user's request is ambiguous in another way.
4. Create tasks only from the selected section. Ignore the other pattern examples in the file for that task-creation run.
5. If the selected pattern is **Guided Exploration** or **Autonomous Research**, preserve its intended autonomy level when creating tasks; do not silently convert it into the deterministic task tree.

## Files

- This skill: [SKILL.md](./SKILL.md)

## Notes

- The skill **never** assigns more than one agent to a single deterministic task.
- The skill **never** overwrites an existing `task-design.md`; when that file already exists in the output folder, write `task-design-YYYYMMDD-HHMMSS.md` instead.
- The skill must always ask whether the task design is for the Discovery local app or the Discovery cloud service before resolving agents.
- If the user chooses Discovery cloud service, the very next question must collect the cloud workspace name, project name, and investigation name. Do not batch this target question with other inputs.
- For local-app designs, `.github/agents` is the default agent source.
- For cloud-service designs, the workspace name and project name are required before looking up agents.
- For both local-app and cloud-service designs or task creation, resolve the full available agent list first, then choose the best-fit agents for the objective unless the user explicitly requests manual agent selection.
- When creating tasks from an existing `task-design.md` with more than one pattern example, always ask the user which single pattern to instantiate before any task or investigation mutation. Do not default to deterministic.
- For cloud-service designs or task creation, first look for and use a Discovery MCP server or Discovery proxy. If none is available, try Azure CLI before asking the user for another route. Do not perform cloud lookups, investigation resolution, or task creation from local catalog files.
- For cloud-service task creation, the parent task is a pure container: never put `dependsOnJson` on the parent and never use parent dependencies to represent child execution order.
- If multiple Discovery MCP/proxy candidates are available and their capabilities are ambiguous, ask the user which one to use.
- If no Discovery MCP/proxy is available and Azure CLI cannot resolve the service, stop before generating cloud tasks and ask the user to connect/provide a MCP/proxy, sign in/configure Azure CLI, or switch to the local-app target.
- For cloud-service designs, the included agents must come from the Foundry agents available in the resolved workspace/project.
- Exclude any agent whose exact name is `Discovery` from all local-app and cloud-service task designs and task creation, even if it appears in `.github/agents`, the Foundry agent list, or the user's requested agent list.
- For cloud-service designs, the investigation name is required as the destination for task creation. Use the existing project investigation when present; otherwise create a new investigation with the provided name.
- If the user does not specify a pattern, default to generating all three in the markdown so they can compare side-by-side.
- If the user lists an agent that does not appear in the resolved local folder or cloud workspace/project Foundry agent list, surface the mismatch before generating tasks.
- Include only the best-fit or explicitly user-selected agents in **Available Agents**. Do not list every available agent unless the user explicitly requests all agents and the objective can support meaningful roles for all of them.
- Do not invent agent names. If the agent set is unknown, ask.

---

## Appendix A — Canonical Markdown Design (verbatim)

This is the canonical `task-design.md` (the Discovery-Retro example). Use it as the byte-for-byte structural reference for the file you generate. Replace the topic, agent names, objectives, and validation text with the user's inputs; preserve the headings, code-fence layout, table column order, separators (`---`), and the twin (inline + bulleted) validation format inside Pattern 3.

````markdown
# Retro Task Design

Task designs for the Discovery-Retro agents using the three advanced investigation patterns defined in the [Microsoft Discovery advanced investigation patterns](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-advanced-investigation-patterns) documentation.

## Available Agents

| Agent | Role |
|---|---|
| `Retro-Help` | Provides guidance and example prompts for using retrosynthesis agents |
| `Retro-PubChem` | Retrieves molecule properties, SMILES, CID, 2D depictions, and 3D conformers from PubChem |
| `Retro-RetroChimera` | Synthesizes target molecules using single-step or multi-step retrosynthesis |
| `Retro-ScienceQA` | Answers general science questions using pre-trained knowledge |
| `Retro-Summary` | Summarizes plan execution results and promotes generated data assets |

---

## Pattern 1: Deterministic Investigation

Use this pattern when the retrosynthesis protocol is known and reproducible — for example, screening a fixed set of candidate molecules through a standard pipeline. You define every task, assign agents explicitly, set dependencies, and write detailed validation requirements.

```
Parent: Parent task : Synthesize 3 candidate drug molecules and rank by feasibility
    Description: Synthesizes target molecule CN1C=NC2=C1C(=O)N(C(=O)N2C)C, get the properties and 3D structure of the target and all reactants, and writes a summary of the results.
    Validation: Summary covers the recommended target and reactsnts based upon RetroChimera results and other details and also includes the 3D structure of targets and reactants.

  Task 1: Subtask 1: Retrieve SMILES and molecular properties for all target molecules
    Agent: Retro-PubChem
    Description: "Query PubChem for each target molecule by name or identifier to obtain its canonical SMILES string, CID, molecular formula, and molecular weight. Save all retrieved data for use in downstream retrosynthesis tasks."
    Depends on: (none)
    Validation: "SMILES notation retrieved for target molecule(s), Molecular formula and weight and CID returned for each"

  Task 2: Subtask 2: Run single-step retrosynthesis for all target molecules
    Agent: Retro-RetroChimera
    Description: "Submit the SMILES strings retrieved in Task 1 to the RetroChimera model using the single-step workflow. Collect all predicted reaction pathways, reactant SMILES, and associated probability scores for each target molecule."
    Depends on: Task 1
    Validation: "Retrosynthesis completed for each SMILES string from Task 1, At least 3 reaction pathways returned per molecule, Probability scores included for each predicted reaction"

  Task 3: Subtask 3: Retrieve 3D conformers for all reactants from predicted reactions
    Agent: Retro-PubChem
    Description: "Extract the unique reactant SMILES strings from the RetroChimera output in Task 2 and query PubChem to retrieve the 3D conformer SDF file for each reactant. Save all SDF files to the outputs directory."
    Depends on: Task 2
    Validation: "3D SDF files retrieved for each unique reactant identified in Task 2, Files saved to outputs directory"

  Task 4: Subtask 4: Summarize retrosynthesis results and rank pathways
    Agent: Retro-Summary
    Description: "Review the retrosynthesis results from Task 2 and the 3D conformer data from Task 3. Produce a detailed summary covering each predicted reaction pathway, its reactants, probability scores, functional group analysis, and green chemistry assessment. Rank pathways by feasibility and promote all generated data assets to the user."
    Depends on: Task 2, Task 3
    Validation: "Summary includes target product and reaction count and reactants for each pathway, Each pathway analyzed for functional groups and reaction transformation, Greenest reaction pathway identified, Ranking considers reaction probability and feasibility, All data assets promoted to user"
```

### Notes
- Tasks 2 and 3 have a strict dependency chain; Task 3 cannot run without valid SMILES output from Task 2.
- This pattern is well-suited for batch screening of known molecule lists or repeating the same pipeline across multiple investigations.
- Consider saving the task structure as a template for regular retrosynthesis screening runs.

---

## Pattern 2: Guided Exploration

Use this pattern when the research direction is known but the specific methods within each phase are flexible. Define major phases with broad validation requirements and let cognition decompose the details within each phase.

```
Phase 1: "Identify and characterize target molecules for [therapeutic area]"
  Depends on: (none)
  Validation: "At least 3 candidate molecules identified"
             "Each candidate includes SMILES notation, CID, molecular formula, and weight"
             "Supporting scientific context provided for each candidate selection"

Phase 2: "Perform retrosynthesis analysis on all candidates"
  Depends on: Phase 1
  Validation: "Retrosynthesis completed for all candidates identified in Phase 1"
             "Both single-step and multi-step pathways explored where applicable"
             "Reaction probabilities and reactant structures included for each pathway"

Phase 3: "Evaluate and recommend optimal synthesis pathways"
  Depends on: Phase 2
  Validation: "Recommendation narrows to 1-2 preferred synthesis pathways per candidate"
             "Analysis covers reaction feasibility, reagent availability, and green chemistry considerations"
             "All generated data assets and 3D structures included in the final summary"
```

### Notes
- Cognition selects between `Retro-PubChem`, `Retro-RetroChimera`, `Retro-ScienceQA`, and `Retro-Summary` within each phase based on agent capabilities.
- Add a comment to Phase 2 specifying `Retro-RetroChimera` if you need to enforce consistent use of that model.
- Phase-level validation should be specific enough to evaluate outcomes, but flexible enough to allow different approaches (e.g., single-step vs. multi-step workflows).

---

## Pattern 3: Autonomous Research

Use this pattern for open-ended retrosynthesis investigations where the approach is not predetermined. Provide a single high-level objective and let cognition plan, decompose, and execute the full investigation.

```
Root task: 

Investigate viable synthesis pathways for CN1C=NC2=C1C(=O)N(C(=O)N2C)C using a single-step workflow, considering synthetic accessibility, reactant availability, reaction probability, and green chemistry principles. Provide a ranked recommendation of the most feasible pathways with supporting rationale.
---
Synthesize c1cnccc1CNc2cc(C(F)(F)F)cc(C(=O)NCCC1CC1)c2 using the multi-step workflow, get the 3D structures of the target molecule and all reactants in the response, and provide summary analysis of the results.
---
Validation: Investigation covers at least 3 distinct synthesis pathways, Retrosynthesis performed using RetroChimera for all viable candidates, Each pathway assessed for reaction probability and reactant accessibility and environmental impact, 3D conformer structures retrieved for key reactants in top-ranked pathways, Final recommendation identifies the most feasible pathway with a clear scientific rationale, All data assets generated during investigation are promoted to the user
---
- Investigation covers at least 3 distinct synthesis pathways.
- Retrosynthesis performed using RetroChimera for all viable candidates.
- Each pathway assessed for reaction probability and reactant accessibility and environmental impact.
- 3D conformer structures retrieved for target product molecule and key reactants in top-ranked pathways.
- Final recommendation identifies the most feasible pathway with a clear scientific rationale.
- All data assets generated during investigation are promoted to the user.

```

### Notes
- Cognition has full autonomy to use `Retro-ScienceQA` for background research, `Retro-PubChem` for data retrieval, `Retro-RetroChimera` for retrosynthesis, and `Retro-Summary` for synthesis.
- Check in periodically to review the task tree cognition builds and add comments to steer toward specific directions if needed.
- The quality of the root task description and validation requirements strongly influences the quality of outcomes. Vague objectives produce vague results.
- `Retro-Help` is typically not invoked by cognition in this pattern but can be referenced manually to explore example prompts before starting.

---

## Choosing the Right Pattern

| | Deterministic | Guided Exploration | Autonomous Research |
|---|---|---|---|
| You know the exact steps | Yes | Partially | No |
| Who selects agents | You (explicit assignment) | You guide phases, cognition selects within them | Cognition selects for all tasks |
| Upfront setup effort | High | Medium | Low |
| Cognition autonomy | Low (execute and validate) | Medium (decompose within phases) | High (plan and execute everything) |
| Reproducibility | High | Medium | Lower |
| Best for | Known screening pipelines, repeatable protocols | Phased drug discovery with known direction | Exploratory compound investigation |

### Mixing Patterns

You can combine patterns within a single investigation. For example:

- Use **Deterministic** for the data preparation phase (retrieving SMILES and properties from PubChem with strict validation).
- Switch to **Guided Exploration** for the retrosynthesis analysis phase (letting cognition decide between single-step and multi-step workflows).
- Use **Autonomous Research** for a follow-up investigation where cognition evaluates unexpected intermediates discovered during retrosynthesis.
````
