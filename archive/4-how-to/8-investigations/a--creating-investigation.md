# Create and Run an Investigation

This guide describes how to create an investigation in Microsoft Discovery and run experiments using Ask Mode, Discovery Mode, agents, workflows, and data containers. It assumes a project has already been created following the Project Creation guide ([Project creation](../7-projects/a--creating-project.md)).

> [!NOTE]
> **Discovery Studio v2**: Microsoft Discovery Studio v2 introduces a modern, streamlined interface designed specifically for scientists and researchers. It brings richer reasoning capabilities, improved workflow transparency, and a more intuitive environment for advanced scientific discovery. This also allows users to explore a new way of interacting with the platform with added functionality and control. Please refer to [Microsoft Discovery Studio v2](10-discovery-studio-preview-experience/a--preview-experience.md) to understand the new UI changes.
.

## Prerequisites

Before creating an investigation, ensure the following are complete:

- You have a provisioned Microsoft Discovery Workspace.
- You have created at least one Project in the workspace (see [Project creation](../7-projects/a--creating-project.md)).
- The Project includes an entry workflow agent and any dependent agents required to run investigations. Refer to [](../6-tools-models-agents/agents-publishing/a--create-agent-definition.md) for more information on agents for Ask Mode and agents for Discover Mode. 
- One Azure Blob Storage data container (added to the project) exists and is accessible by the project.
- Your user account has the necessary role assignments (Contributor or Project-level access) to create and run investigations.

**Important:** Naming conventions are available [here](../2-onboarding-experience/d--resource-naming.md)

## Create an Investigation

1. Sign in to Microsoft Discovery Studio: https://studio.discovery.microsoft.com
2. In the left navigation pane, select Projects and open the Project where you want to create the investigation in the Microsoft Discovery Studio v2 experience 
3. Click "New Investigation".
4. Enter a Name and optional Description.
5. Press Enter to create the new investigation

Once created, the investigation will appear in the Project's investigation list.

> Note: A new investigation inherits the project's agents, workflow entry point, and data container selection. If you need to change agents or data containers, update the Project first.

## Start a Chat with Copilot in Ask Mode

1. Open the Project and select the investigation you created.
2. Start a new Copilot chat session from the investigation UI by selecting Ask from the drop down.
3. Provide a prompt describing your scientific goal, desired outputs, or tasks you want the agents to perform. Examples:
   - "Estimate the solubility and logP for molecule SMILES: C1=CC=CC=C1"
   - "Run a conformer generation workflow for the attached XYZ file and summarize results"
4. Copilot will use the project's workflow and agents to propose a plan or execute tasks depending on your selection and the workflow configuration.

## Start a Chat with Discovery Engine in Discover Mode
1. Open the Project and select the investigation you created.
2. Start a new Copilot chat session from the investigation UI by selecting Discover from the drop down.
3. When using Discover Mode, provide your objective as a question or goal. Include how to validate the reasoning. Discovery Engine will analyze the request, create a plan, and work through the tasks autonomously. Examples:
   - "Explain the relationship between molecular weight and boiling point. Validate your reasoning with chemical principles."
   - "What are common methods for protein structure prediction? Compare their strengths and limitations."
4. Discovery Engine creates tasks and begins working. You can view tasks in the investigation and track progress. Tasks will use the project's workflow and agent to complete tasks created by Discovery Engine. 

See [Discovery Engine](/3-concepts/engine.md), [Cognition](/3-concepts/cognition.md), and [Tasks](/3-concepts/tasks.md) for more information about Discovery Engine and Task Management.  

## Run a Computational Analysis (Investigations with Workflows and Tools)

If your investigation requires executing tools or advanced workflows, follow these steps:

1. From the Copilot chat in Ask Mode, request the analysis or trigger a tool execution with a prompt.
2. Confirm any prompts if the project is configured to require plan confirmation.
3. Monitor the run status in the investigation UI. The run will typically progress through workflow states (Planning → Execution → Summary).
4. View logs and intermediate outputs from the investigation run in the Studio UI.

## Data Handling and Outputs

### Ask Mode
- Output files from tools and workflows will be stored in the project's configured data container (the container added during Project creation).
- Promoted outputs are visible to end users in the investigation outputs section as data assets. Only validated and promoted files should appear there.

### Best practices for Ask Mode:
- Preview outputs before promoting them to final assets.
- Keep descriptive metadata for promoted outputs so users can identify results easily.
- Ensure all data paths for tools are absolute paths as required by the data handling guidelines.
- If multiple data assets are attached to a message, clearly prompt Copilot and describe the purpose of each data asset so agents and tools can select and use the correct asset.

### Discover Mode
- Discovery Mode does not support processing data assets provided to the chat and does not present output files created by tools or workflows. This will get addressed in a future release. 

## Monitoring and Troubleshooting

- Use the investigation UI to view run status, agent logs.
- If a run fails, check the agent messages and tool error logs to determine whether the failure is due to model input, tool configuration, or resource limits.
- Verify that the project's data container has correct access and CORS settings if you cannot access outputs from Studio. See the Quickstart section "1e. Create an Azure Blob Storage Account" for details: [Create an Azure Blob Storage Account](../../2-getting-started/quickstart.md#1e-create-an-azure-blob-storage-account)
- Confirm the UAMI and service principals have required role assignments (Storage Blob Data Contributor, etc.) when storage access issues occur.


## Related topics

- [Quickstart](../../2-getting-started/quickstart.md)
- [Project creation](../7-projects/a--creating-project.md)
- [Data containers](../../2-getting-started/quickstart.md#7-create-your-data-containers)
- [Agents and workflows](../../2-getting-started/quickstart.md#5-create-an-agent-and-a-workflow)


