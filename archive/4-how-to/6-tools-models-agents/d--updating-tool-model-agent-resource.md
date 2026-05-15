# Updating Tool, Model, and Agent Resources in Microsoft Discovery

This guide covers the updates allowed on Tools, Models, and Agents resources in Microsoft Discovery to modify their respective definitions. Understanding what can and cannot be updated helps you maintain and evolve your scientific computing resources efficiently while ensuring system stability.

## Update Overview

Microsoft Discovery allows selective updates to deployed resources to support iterative development and maintenance workflows. However, certain critical properties are immutable to ensure system stability and prevent breaking changes that could affect running workflows.

## Tool Resource Updates

This section explains how and what all updates can be made to Microsoft Discovery Tools control plane resources. These resources store configuration details that enable the deployment of containerized executables for investigations. Once deployed, these executables carry out targeted scientific or data-processing tasks. The documentation below outlines the supported update operations for Tool resources.

### Tool Updatable Properties

#### 1. Tool Definition File

User can update the content of tool definition by uploading new file when prompted on Tool update against Microsoft Discovery Tools control plane resource.

Here it the Azure portal experience to update the tools resource:

1. **Sign in to the Azure Portal**
   - Navigate to [https://portal.azure.com](https://portal.azure.com)
   - Authenticate with your Azure credentials

2. **Access Microsoft Discovery Tools**
   - In the Azure Portal search bar, type "Microsoft Discovery Tools"
   - Select **Microsoft Discovery Tools** from the search results
   - Select the specific Microsoft Discovery Tools resource you want to update

3. Click **Update** on the selected Tools pane.
   - A pane will appear on the right.
   - Click **Definition content file** and select the new file from your local computer to upload.
   - When finished, click the **Update Tool** button on the right pane to apply your changes.

#### 2. Environment Variables

Users can update the environment variables for a Tool resource by uploading a new JSON file.

To update environment variables using the Azure Portal, instead of step 3 in previous section:

1. Click **Update** on the selected Tools pane.
2. In the pane that appears on the right, select **Environment variables** and upload the new JSON file from your local computer.
3. When finished, click the **Update Tool** button to apply your changes.

**Sample Environment file content**
{
   "TEST_CAPTION": "this is a sample test caption",
   "ENDPOINT": "https://api.github.com"
}

#### 3. Tags

Users can add/update any tags on the control plane resources.

### Update Considerations for Tools

The udpates if any can be applied to any future deployment of tool container resource, which gets created during the investigation run.

1. **Container Image Updates**: When updating container images, ensure backward compatibility
2. **Compute Resource Changes**: Monitor impact on running workloads and costs
3. **Schema Modifications**: Changes to input/output schemas can break existing workflows
4. **Action Dependencies**: Consider impact on agents that rely on specific actions

## Model Resource Updates

Models are trained machine learning assets deployed from the Azure AI Model Catalog. When you deploy a Discovery Model control plane resource, the corresponding model is also deployed to your Azure Machine Learning workspace. To ensure a seamless and stable experience, updates to the Discovery Model control plane resource are restricted: only tags can be added or modified after initial deployment. All other properties are immutable.

### Model Updatable Properties

#### 1. Tags

Users can add/update any tags on the control plane resources.

#### 2. Model Definition Updates

1. **Sign in to the Azure Portal**
   - Navigate to [https://portal.azure.com](https://portal.azure.com)
   - Authenticate with your Azure credentials

2. **Access Microsoft Discovery Models**
   - In the Azure Portal search bar, type "Microsoft Discovery Models"
   - Select **Microsoft Discovery Models** from the search results
   - Select the specific Microsoft Discovery Models resource you want to update

3. Click **Definition content** in the selected Models pane.
   - A pane will appear on the right.
   - Select a new **Definition content file** and specify the new **Definition content version**.
   - When finished, click the **Update Model** button on the right pane to apply your changes.

## Agent Resource Updates

Agents are AI assistants that execute tasks using tools and models. They have the most flexible update capabilities.

### Agent Updatable Properties

This section describes the portal experience for users updating an Agent resource. It provides step-by-step guidance on how to modify existing Agent resources within the platform, ensuring users can efficiently manage and update their Agents as needed.

#### Navigate to Agent Resource to be updated

1. **Sign in to the Azure Portal**
   - Navigate to [https://portal.azure.com](https://portal.azure.com)
   - Authenticate with your Azure credentials

2. **Access Microsoft Discovery Agents**
   - In the Azure Portal search bar, type "Microsoft Discovery Agents"
   - Select **Microsoft Discovery Agents** from the search results
   - Select the specific Microsoft Discovery Agents resource you want to update

3. The sections below shows updates to each of the allowable components:

##### 1. Agent Definition content

a. Click on **Definition content** to see the pane on right which enables you to update:
    - Definition content file
    - Definition content version
b. Once the details are updated, press **Update Agent** button

Once done, the changes to Agents resource shall take into account.

> **Note:** This update will apply exclusively to newly created projects.

##### 2. Updating Tools

You can add or remove tools associated with an Agent resource using the following steps:

a. Click on **Tools** to open a new pane where you can manage the tools linked to the Agent resource.

b. To add a tool, select **+ Add**. A pane will appear on the right, allowing you to choose the Subscription, Resource Group, and the specific tool resource to associate with the Agent.

c. To remove a tool, select the tool(s) you wish to delete from the list, then click the **Remove** option at the top of the screen.

##### 3. Model

This section explains how to update the chat completion model for an Agent resource.
a. To change the model, select **Model Name** in the Agents window.

b. A pane will appear on the right, allowing you to enter the model asset ID for the new model you wish to associate with the Agent.

c. Once done, select **Update** button at the bottom of right pane.

> **Note:** With initial private preview release, its highly suggested to use **gpt-4o** model for your agents.

### Update Considerations for Agents

1. **Instruction Changes**: Can significantly alter agent behavior and capabilities
2. **Model Switching**: Different models may interpret instructions differently
3. **Tool Dependencies**: Ensure referenced tools and models are available and compatible
4. **Workflow Impact**: Changes may affect multi-agent workflows and collaborations

## Update Best Practices

This section explains the importance of reviewing all projects and investigations where a resource is utilized before making any updates. Modifying a resource may affect its functionality for other users or processes, so it is crucial to assess potential impacts prior to implementing changes.

### 1. Versioning Strategy

- **Note:** Updating definitions version is currently unavailable in the initial private preview release. This feature will be enabled in a future update, and the documentation will be revised accordingly once it becomes available.

Once the experience is enabled, its a suggestion to follow the versioning semantics as mentioned below.

```yaml
# Use semantic versioning for your definitions
version: 1.2.0 # MAJOR.MINOR.PATCH
# - MAJOR: Breaking changes
# - MINOR: New features, backward compatible
# - PATCH: Bug fixes, backward compatible
```

### 2. Testing Updates

- Test updates in a development environment first
- Validate that dependent resources still function correctly

### 3. Documentation and Change Management

- Document all changes with rationale
- Maintain changelog for each resource
- Communicate updates to dependent teams/workflows

### Update Verification

After completing updates, verify the changes through Portal.

## Next Steps

After successfully updating your resources:

- **Update Documentation**: Reflect changes in your team's documentation
- **Notify Stakeholders**: Inform users of any behavior changes
- **Plan Future Updates**: Schedule regular review cycles for resource optimization
