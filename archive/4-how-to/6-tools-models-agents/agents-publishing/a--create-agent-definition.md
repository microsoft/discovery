# Agent Definition Guide

This comprehensive guide covers the complete agent definition specification for Microsoft Discovery. 

---

## Table of Contents

1. [Agent Definition Specification](#agent-definition)
   - [YAML Schema for Agent Definition](#yaml-schema-for-agent-definition)
   - [System Pre-Integrated Tools](#system-pre-integrated-tools)
   - [How Variables Work in Agent Definitions](#how-variables-work-in-agent-definitions)
   - [Available Variables Reference](#available-variables-reference)
   - [Variable Usage Examples](#variable-usage-examples)
   - [Agent Definition Examples](#agent-definition-examples)
2. [Workflow Agent Definition Specification](#workflow-agent-definition-specification)
   - [YAML Schema for Workflow Agent Definition](#yaml-schema-for-workflow-agent-definition)
   - [Workflow Agent Definition Examples](#workflow-agent-definition-examples)
3. [Variable Types in Workflow Agents](#variable-types-in-workflow-agents)
   - [Thread Variables](#thread-variables)
   - [Message Variables](#message-variables)
4. [Summary](#summary)

## Agent Definition

Microsoft Discovery supports two types of agents: **standard agents** and **workflow agents**. Standard agents perform individual tasks, while workflow agents orchestrate multiple agents to complete complex multi-step processes.

### YAML Schema for Agent Definition

> **⚠️ Important - Avoid Unicode Encoding:** When writing agent definitions, **do not use unicode characters** in your `instructions`, `description`, variable `value` fields, or any other YAML string values. Common problematic characters include:
> - **Smart/curly quotes** (`“` `”` `‘` `’`) — use straight quotes (`"` `'`) instead
> - **Em dashes** (`—`) or **en dashes** (`–`) — use regular hyphens (`-`) or double hyphens (`--`) instead
> - **Right arrows** (`→`) — use `->` instead
> - **Ellipsis characters** (`…`) — use `...` instead
> - **Non-breaking spaces** (U+00A0) — use regular spaces instead
>
> Unicode characters in agent definitions can cause parsing errors, unexpected behavior during agent execution, or silent failures when the platform processes your YAML. Always use plain ASCII characters in your agent and workflow definitions.

Standard agents use the following YAML structure:

```yaml
agent:
  name: string                    # Name of the agent
  description: string             # Description of the agent's purpose
  model: string                   # The AI model to use (e.g., gpt-4o)
  instructions: string            # Natural language instructions defining the agent's behavior
                                  # IMPORTANT: Instructions must be less than 32,000 characters
                                  # Can include context variables:
                                  # {{nodePoolContext}} - Provides hints for supercomputer/node pool selection
                                  # {{dataHandlingContext}} - Provides data context handling hints
  top_p: number                   # Controls diversity of model responses, Range: 0 (least diversity) to 1 (maximum diversity)
  temperature: number             # Controls randomness of model responses (0-2), Range: 0 (least randomness more deterministic) to 2 (maximum randomness)
  response_format: string         # Response format (auto, json_object, etc.)

extension:
  events:                         # Events for workflow agents
    - name: string
      type: string                # Event type (llm, tool)
      condition: string           # When this event should be triggered
  inputs: []                      # Input parameters
  outputs: []                     # Output parameters  
  system_prompts: {}              # System prompt configurations

discovery_extensions:             # Discovery-specific extensions for enhanced agent behavior
  plan_confirmation: boolean      # Whether to require user confirmation before executing plans (true/false)
  tool_confirmations:             # List of tool resource IDs that require user confirmation before execution
    - <tool resource id>          # Tool resource ID (e.g., /subscriptions/1015baa8-b5cd-40de-96e5-xxxxxxxxxxxx/resourceGroups/discovery-rg-001/providers/Microsoft.Discovery/tools/RetroChimera-Tool)
```

### System Pre-Integrated Tools

Microsoft Discovery provides agents with access to several pre-integrated system tools that enhance their data handling and workflow capabilities. These tools are automatically available to all agents without requiring explicit configuration.

#### Core Data Management Tools

**Get Data Context**
- **Purpose**: Allows agents to access data context attached to a message
- **Functionality**: Retrieves metadata and information about data assets linked to the current message
- **Scope**: Only accesses data assets that are specifically linked to the message, not all available data assets
- **Usage**: Essential for understanding what data is available for processing in the current workflow context

**Preview Data**
- **Purpose**: Enables agents to preview and inspect data assets
- **Functionality**: Runs simple preview commands (such as `cat`, `head`, or `ls`) on data assets to examine their content
- **Use Cases**: 
  - Validating data format and structure
  - Checking file contents before processing
  - Understanding data organization and layout
- **Benefits**: Allows agents to make informed decisions about data processing steps

**Promote to Outputs**
- **Purpose**: Converts system-created data assets into user-accessible data assets
- **Functionality**: Automatically generates appropriate names and metadata for data assets using Azure function logic
- **Automation**: Naming and organization are handled automatically by the platform

**Save file Tool**
- **Purpose**: Enables agents to save generated content directly as data assets without requiring custom tools
- **Functionality**: Saves text content, code, or any generated output as a data asset that can be accessed and managed
- **Use Cases**:
  - Saving generated code files (Python, scripts, etc.)
  - Storing analysis results or reports
  - Creating configuration files or documentation
  - Preserving intermediate workflow outputs
- **Benefits**: Simplifies data asset creation by eliminating the need for custom file-saving tools
- **Example Usage**: When asked "Write a simple Python code that implements the Fibonacci sequence using recursion and save the result", the agent can generate the code and directly save it as a data asset using the SaveFile tool.

**Disabling Data Handling Tools**

By default, all agents have access to system data handling tools. For agents that don't need to run tools and generate data assets, you can disable these capabilities by adding the following configuration to the `discovery_extensions` section of your agent definition:

```yaml
discovery_extensions: 
  disable_data_handling_tools: true
```

When data handling tools are disabled:
- The agent will not have access to system tools including Get Data Context, Preview Data, Promote to Outputs, Save File, and other data asset creation tools
- The agent will not be able to create or manage data assets
- You should remove the `{{dataHandlingContext}}` variable from your agent instructions:

```yaml
instructions: |-
  You are an AI agent that performs specific tasks.
  
  # Remove this line when data handling tools are disabled:
  # Data handling context: {{dataHandlingContext}}
```

**When to Disable Data Handling Tools:**
- Agents that only perform text-based reasoning or Q&A
- Agents that don't interact with data assets or generate outputs that need to be saved
- Specialized agents with custom data handling tools
- Pure coordination or routing agents that delegate work without data manipulation


#### Best Practices for System Tools

- **Always preview data** before performing operations to ensure compatibility
- **Use Get Data Context** at the beginning of workflows to understand available data
- **Promote outputs strategically** - only final, validated results should be promoted to user-accessible assets
- **Leverage automatic naming** for consistency across workflows and users

These system tools are integrated into the `dataHandlingContext` variable and are referenced in agent instructions to guide proper data management workflows.

### How Variables Work in Agent Definitions

Variables in Microsoft Discovery agents serve to provide runtime context and information that enriches agent reasoning and decision-making. Understanding how variables work is crucial for creating effective agents.

#### Variable Acceptance in Standard Agents

In standard agent definitions, user-defined variables that can be accepted by agents are defined in the `inputs` section of the `extension` block:

```yaml
extension:
  inputs: 
    - name: userGoal
      type: llm
      description: The user request for which the plan needs to be generated
    - name: agentTeam
      type: llm
      description: The team of agents available in the workflow
    # Note: Automatic variables (dataHandlingContext, messageId, nodePoolContext) 
    # are NOT defined here - they are automatically available
  outputs: []
```

#### Automatically Available Variables

Three variables are automatically added to every agent by the Microsoft Discovery platform:

- **`dataHandlingContext`**: Provides comprehensive data handling guidelines and capabilities
- **`messageId`**: Unique identifier for tracking conversation context and debugging
- **`nodePoolContext`**: Information about computational resources and supercomputer node pools

**Important Behavior:**
- **In Agent Definitions**: These automatic variables do NOT need to be defined in the `inputs` section. The Discovery service will populate them automatically.
- **In Workflow Definitions**: These variables MUST be explicitly mapped as inputs when configuring actors in workflow states.
- These automatic variables are always available for use in agent instructions.

#### Variable Usage in Instructions

Variables are used in agent instructions to enrich the context for agent reasoning. They are referenced using double curly brace syntax:

```yaml
instructions: |-
  You are an AI agent with access to the following context:
  
  User Goal: {{userGoal}}
  Agent Team: {{agentTeam}}
  Node Pool Context: {{nodePoolContext}}
  Data Handling Context: {{dataHandlingContext}}
  Message ID: {{messageId}}
  
  Use this context to make informed decisions and provide relevant responses.
```

#### Workflow Requirements for Variables

**Important**: When using agents in workflows, variables must be handled differently based on their type:

```yaml
# In workflow agent definition
actors:
  - agent: MyAgent
    inputs:
      # Automatic variables (must be mapped in workflows, NOT in agent definition inputs)
      dataHandlingContext: dataHandlingContext
      messageId: messageId
      nodePoolContext: nodePoolContext
      # User-defined variables (must be defined in both agent inputs AND workflow variables)
      userGoal: userGoal
      agentTeam: agentTeam
      workflowContext: workflowContext
```

#### Variable Types and Sources

The following table summarizes all variable types and their requirements in agent and workflow definitions:

| Variable Type / Name | Provided by Platform? | Agent Definition: Declare in `inputs`? | Workflow Definition: Declare in `variables:`? | Workflow Definition: Map in `actors[].inputs`? | Notes |
|---------------------|----------------------|---------------------------------------|---------------------------------------------|---------------------------------------------|-------|
| **Automatic Variables** | | | | | |
| `dataHandlingContext` | ✅ Yes | ❌ No | ✅ Yes | ✅ Yes | Always available. Provides data handling guidelines and capabilities. |
| `messageId` | ✅ Yes | ❌ No | ✅ Yes | ✅ Yes | Always available. Unique identifier for tracking conversation context. |
| `nodePoolContext` | ✅ Yes | ❌ No | ✅ Yes | ✅ Yes | Always available. Information about computational resources and supercomputer node pools. |
| **User-Defined Variables** | | | | | |
| `userGoal` | ❌ No | ✅ Yes (if needed) | ✅ Yes (if needed) | ✅ Yes (if needed) | The original user request. **Required** for entry agent (first agent) in workflow. |
| `agentTeam` | ❌ No | ✅ Yes (if needed) | ✅ Yes (if needed) | ✅ Yes (if needed) | 🐛 Currently required due to bug. Will be **optional** after fix. Descriptions of all agents for coordination. |
| `workflowContext` | ❌ No | ✅ Yes (if needed) | ✅ Yes (if needed) | ✅ Yes (if needed) | 🐛 Currently required due to bug. Will be **optional** after fix. Workflow-specific guidance for multi-agent coordination. |
| Custom variables | ❌ No | ✅ Yes (if needed) | ✅ Yes (if needed) | ✅ Yes (if needed) | Define any custom variables your agent needs. |
| **Thread Variables** | | | | | |
| Thread names | ❌ No | ❌ No | ✅ Yes | Reference in `thread` field | Special variables for conversation continuity. Defined with `Type: thread`. |

**Key Points**:
- **Automatic variables** are provided by the platform and should NOT be declared in agent inputs, but MUST be mapped in workflow actor inputs
- **User-defined variables** must be declared in both agent inputs AND workflow variables when you need them for your agent
- **Bug notice**: `agentTeam` and `workflowContext` currently require explicit definition due to a bug. After the fix, they will be optional - you can choose whether to include them based on your requirements. They will NOT be automatically provided by the platform.
- All examples in this document demonstrate the correct way to define variables

#### Available Variables Reference

**Automatic Variables** (provided by the platform):
- **`{{dataHandlingContext}}`**: Provides comprehensive data handling guidelines and capabilities
- **`{{messageId}}`**: Unique identifier for tracking conversation context and debugging
- **`{{nodePoolContext}}`**: Information about computational resources and supercomputer node pools

**User-Defined Variables**:
- **`{{userGoal}}`**: The original user request or goal that initiated the workflow (**Required** for entry agent)
- **`{{agentTeam}}`**: Descriptions of all agents in the team for coordination and task delegation
- **`{{workflowContext}}`**: Workflow-specific context and guidance for multi-agent coordination
- **Custom variables**: Define any variables your agent needs for specific use cases

> **📝 Refer to the table above** for detailed requirements on where to declare and map each variable type.

#### Variable Usage Examples

**Complete Context Usage Example:**
```yaml
instructions: |-
  You are a molecular dynamics simulation agent. Coordinate computational resources and data processing.
  
  Agent team:
  {{agentTeam}}

  Node pool context: 
  {{nodePoolContext}}
  
  Data handling context: 
  {{dataHandlingContext}}
  
  Workflow context:
  {{workflowContext}}
  
  User goal: {{userGoal}}
  Message ID: {{messageId}}
  
  Use all contexts to optimize resource allocation, workflow coordination, and data pipeline configuration.
```

### Agent Definition Examples

#### Example 1: Router Agent

```yaml
agent:
  name: RouterAgent
  description: You goal is to perform routing decision based on the plan and current progress.
  model: azureml://registries/azure-openai/models/gpt-4o/versions/2024-11-20
  instructions: |-
    You are an AI agent responsible for routing decisions in a molecular science task.
    Your primary goal is to analyze plan which is precomputed and based on the current progress of the conversation, 
    determine which specialized agent should be assigned next to assist with the task.
    You should not replan or perform any computations yourself. Instead, you will delegate the task to the appropriate agent 
    based on the user's request and the context of the conversation.

    Guidelines for making Routing Decisions:
    - You will consider the entire conversation history to ensure that the routing decision is appropriate and relevant to the user's needs.
    - You will not perform any actions or computations yourself, but rather delegate the task to the appropriate agent based on the user's request and the context of the conversation.
    - You are not expected to create any plan or perform any computations. Your role is solely to make routing decisions based on the user's request and the context of the conversation.

    Ensure you only output one response at a time in below json format:
    {
      "NextAgent": "<name of the next agent>", 
      "Response": "<your comments as reason to choice made. What to perform next>"
    }

    Agent team:
    {{agentTeam}}

    Node pool context: 
    {{nodePoolContext}}

    Data handling context: 
    {{dataHandlingContext}}
  top_p: 0
  temperature: 0
  response_format: auto

extension:
  events:
    - name: RunCorePythonTools
      type: llm
      condition: When step in the plan requires the corepython agent for tasks such as Python code execution with chemistry libraries or python code execution in general, converting SMILES to xyz, generating conformers, or analyzing molecular structures.
    - name: RunAdft
      type: llm
      condition: When step in the plan requires perform scientific computations that are apart of the ADFT agent and you have xyz properties for the molecule.
    - name: RunRetroChimera
      type: llm
      condition: When step in the plan requires retrosynthesis prediction or reaction planning to determine how to synthesize a target molecule.
    - name: GenerateSummary
      type: llm
      condition: When NextAgent is Summarizer and you have all the information you need to summarize the final response for the user once the plan is executed.
  inputs:
    - name: agentTeam
      type: llm
      description: The team of agents available in the workflow
  outputs: []
  system_prompts: {}
```

#### Example 2: Planner Agent

```yaml
agent:
  name: PlannerAgent
  description: You are the coordinator agent which receives user requests and responds back with a high level plan to achieve the user goal
  model: azureml://registries/azure-openai/models/gpt-4o/versions/2024-11-20
  instructions: |-
    You are the coordinator agent which receives user requests and responds back with a high level plan to achieve the user goal.
    If the user goal is simply research, you may utilize any of the knowledge base tools available to you in order to achieve the user goal of collecting information.

    You will receive the user request and prepare just the plan for user goal based on tools and agents you have.
    Note: If the user goal is something to do with data handling, you can use the tools available to handle data, but you should not perform any computation by yourself.

    Note: You may have access to tools which allow you to interact with knowledge bases that have special domain expertise, so you can use it to retrieve information if needed.
    Do not use knowledge base tools unless their description is relevant to the user goal.

    The user goal is:
    {{userGoal}}

    Agent team:
    {{agentTeam}}

    Node pool context:
    {{nodePoolContext}}

    Data handling context:
    {{dataHandlingContext}}
  top_p: 0
  temperature: 0
  response_format: auto

extension:
  events: []
  inputs: 
    - name: userGoal
      type: llm
      description: The user request for which the plan needs to be generated.
    - name: agentTeam
      type: llm
      description: The team of agents available in the workflow
  outputs: []
  system_prompts: {}
```

## Workflow Agent Definition Specification

Workflow agents are a specialized type of agent that orchestrate multiple agents to complete complex tasks. They use the standard agent structure with additional workflow-specific properties that define states, transitions, and variables for multi-agent coordination.

### YAML Schema for Workflow Agent Definition

Workflow agents extend the standard agent definition with workflow orchestration capabilities:

```yaml
name: string                      # Name of the workflow
states:                           # Workflow states
- name: string                  # State name
  actors:                       # Agents in this state
    - agent: string             # Reference to agent definition
      inputs: {}                # Input mappings for the agent
                                # Can include context variables:
                                # nodePoolContext: nodePoolContext
                                # dataHandlingContext: dataHandlingContext
                                # agentTeam: agentTeam
                                # workflowContext: workflowContext
      thread: string            # Thread to use
      humanInLoopMode: string   # Human intervention mode (never, always, onNoMessage, etc.)
                                # Note: Set to "onNoMessage" if you have single Agent in your workflow to allow the agent accessing the historical messages in the investigation.
      streamOutput: boolean     # Whether to stream output, Propose to set it as true for the Final state in the workflow
      maxTurn: number           # Maximum turns for this actor (optional, default varies)
      maxTransientErrorRetries: number  # Maximum retries for transient errors (optional)
      maxRateLimitRetries: number       # Maximum retries for rate limit errors (optional)
  isFinal: boolean              # Whether this is a final state

transitions:                      # State transitions
- from: string                  # Source state
  to: string                    # Target state
  event: string                 # Event that triggers transition (optional)
  condition: string             # Optional condition, Transition can also be based on data condition of the message variables. Allowed data conditions on the message variable are IsEmpty(), IsNotEmpty(), Contains(), and NotContains(). 

variables:                        # Workflow variables
- Type: string                  # Variable type (thread, userDefined, etc.)
  name: string                  # Variable name
  value: string                 # Optional default value
                                # Common context variables:
                                # nodePoolContext, dataHandlingContext, agentTeam, workflowContext

startstate: string                # Initial state of the workflow
id: string                        # Optional workflow identifier
```

### Workflow Agent Definition Examples

The following examples demonstrate workflow agents that orchestrate multiple individual agents to complete complex tasks:

#### Example 1: Science Workflow Agent

```yaml
name: ScienceWorkflow
states:
- name: Planning
  actors:
    - agent: plannerAgent
      inputs:
        userGoal: userGoal
        dataHandlingContext: dataHandlingContext
        messageId: messageId
        nodePoolContext: nodePoolContext
        agentTeam: agentTeam
        workflowContext: workflowContext
      thread: MainThread
      humanInLoopMode: onNoMessage
      streamOutput: false
      maxTurn: 10
      maxTransientErrorRetries: 3
      maxRateLimitRetries: 3
  isFinal: false
- name: AgentRouter
  actors:
    - agent: routerAgent
      inputs:
        dataHandlingContext: dataHandlingContext
        messageId: messageId
        nodePoolContext: nodePoolContext
        agentTeam: agentTeam
        workflowContext: workflowContext
      thread: MainThread
      humanInLoopMode: never
      streamOutput: false
      maxTurn: 1
      maxTransientErrorRetries: 3
      maxRateLimitRetries: 3
  isFinal: false
- name: CorePython
  actors:
    - agent: pythonAgent
      inputs:
        nodePoolContext: nodePoolContext
        messageId: messageId
        dataHandlingContext: dataHandlingContext
        agentTeam: agentTeam
        workflowContext: workflowContext
      thread: MainThread
      humanInLoopMode: never
      streamOutput: false
      maxTurn: 10
      maxTransientErrorRetries: 3
      maxRateLimitRetries: 3
  isFinal: false
- name: Summary
  actors:
    - agent: summaryAgent
      inputs:
        messageId: messageId
        dataHandlingContext: dataHandlingContext
        nodePoolContext: nodePoolContext
        agentTeam: agentTeam
        workflowContext: workflowContext
        userGoal: userGoal
      thread: MainThread
      humanInLoopMode: never
      streamOutput: true
      maxTurn: 10
      maxTransientErrorRetries: 3
      maxRateLimitRetries: 3
  isFinal: false
- name: End
  actors: []
  isFinal: true

transitions:
- from: Planning
  to: AgentRouter
- from: AgentRouter
  to: CorePython
  event: RunCorePythonTools
- from: AgentRouter
  to: Summary
  event: GenerateSummary
- from: CorePython
  to: AgentRouter
- from: Summary
  to: End

variables:
- Type: thread
  name: MainThread
- Type: userDefined
  name: dataHandlingContext
  value: "
    GUIDELINES:
    
    **Definitions**
    - **Virtual path**: System-assigned absolute namespace for passing data between steps (e.g., `/step0/app/outputs`). Not the container's real filesystem path.
    - **Container path**: Absolute path inside the tool container (e.g., `/app/outputs`). Used only in `outputMounts` and `inputMountPath`.
    - **Mapping**: Tool reads/writes container (mount) path -> system maps to virtual path. Pass **virtual path** downstream, not container path.
    - **Implicit extension**: If `/step0/app/outputs` exists, `/step0/app/outputs/reports` is valid (assuming 'reports' exists in the data pointed to by `/step0/app/outputs`.  Make extension explicit by giving the implicit path a description.
    -**No shortening virtual paths**: Implied 'shortening' is disallowed (So if you had `/step0/app/outputs/reports` as the only item in the context, shortening it to just `/step0/app/outputs` would not be valid).
    ---
    
    **Global Rules**
    1. ALL paths must be ABSOLUTE. Never use relative paths.
    2. Retrieve current data context before any action.
    3. Preview data before updating descriptions.
    4. Update virtualPath description **before** promoting to data asset (or description won't propagate).
    5. Remember to promote data asset after updating description.
    
    ---
    
    **Tool Mount Rules**
    - `outputMounts` = absolute container path where tool stores outputs.  Only directories are permitted.
    - `inputMounts` = array of `{ virtualPath: <virtual path>, inputMountPath: <absolute container path> }`. Files or directories are permitted. The mount path will be of the type (file/directory) that is keyed by the virtual path given.
    
      ---
      
      **Example Flow**
      1. Tool writes `molecule.txt` to `/app/outputs` (container path).
      2. System maps to virtual path `/step0/app/outputs`.
      3. Update description for `/step0/app/outputs`.
      4. Next tool mounts `/step0/app/outputs` as `virtualPath`; `inputMountPath = /app/inputs`.
      ```json
      inputMounts: [ { virtualPath: /step0/app/outputs, inputMountPath: /app/inputs } ]
      ```
      5. Tool produces `step1/app/outputs`
      6. Update description of `step1/app/outputs`
      7. Promote `step1/app/outputs` as data asset"
- Type: userDefined
  name: messageId
- Type: userDefined
  name: nodePoolContext
- Type: userDefined
  name: userGoal
- Type: userDefined
  name: agentTeam
  value: |-
    Here are the list of agents and their description:
    1. plannerAgent - Agent for planning and orchestrating science workflows
    2. routerAgent - Agent for routing tasks to appropriate agents based on the plan
    3. pythonAgent - Agent for comprehensive computational tasks
    4. summaryAgent - Agent for summarizing the results of the workflow
- Type: userDefined
  name: workflowContext
  value: "You are apart of a team of AI agents working together to perform molecular computations using various tools and techniques. You will receive a plan that comes from the planner agent with steps to execute in order to achieve the user goal, you should look through the plan as well as the steps that have already been executed by other agents and decide what to do next based on the plan and the steps that have already been executed. IMPORTANT* You should only perform actions which have been assigned to you in the plan."

startstate: Planning
id: science_workflow
```

## Available AI Models

Microsoft Discovery supports multiple AI models for agent creation. The following table shows the currently available models with their specifications:

| Model Name | Version | Model ID |
|------------|---------|----------|
| GPT-4o | 2024-11-20 | `azureml://registries/azure-openai/models/gpt-4o/versions/2024-11-20` |
| GPT-4.1 | 2025-04-14 | `azureml://registries/azure-openai/models/gpt-4.1/versions/2025-04-14` |

### Model Selection Guidelines

When choosing a model for your agent, consider the primary function your agent will perform:

#### **GPT-4o** (Recommended for Tool-Heavy Agents)
- **Best for:** Agents that execute tools extensively and frequently
- **Strengths:** Reliable and efficient tool execution, balanced performance across various tasks
- **Use Cases:** Agents that interact with computational tools, data processing tools, or APIs
- **Example:** Molecular property prediction agents, data analysis agents, simulation orchestration agents

#### **GPT-4.1** (Recommended for Reasoning and Content Generation)
- **Best for:** Agents focused on reasoning, analysis, and content creation
- **Strengths:** Enhanced reasoning capabilities, superior content generation, improved instruction following
- **Restrictions:** ⚠️ Limited tool execution reliability - not recommended for tool-heavy workflows
- **Use Cases:** Planning agents, summarization agents, literature review agents, report generation agents
- **Example:** Workflow planners, research synthesizers, documentation generators
- **Note:** GPT-4.1 excels at content generation, reasoning tasks, and analysis but may show inconsistent behavior when executing tools. For agents that require frequent or complex tool invocations, prefer GPT-4o.

> **💡 Quick Selection Guide:**
> - Choose **GPT-4o** if your agent will primarily **use tools** to accomplish tasks
> - Choose **GPT-4.1** if your agent will primarily **reason and generate content**
> - For multi-agent workflows, you can use different models for different agents based on their specific roles

The model ID should be specified in the `model` field of your agent definition:

```yaml
agent:
  name: MyAgent
  model: azureml://registries/azure-openai/models/gpt-4o/versions/2024-11-20
  # ... rest of agent definition
```

## Variable Types in Workflow Agents

### Thread Variables
Used to determine which thread is used to activate an agent turn. Enables sharing threads between agents for message continuity.

```yaml
variables:
  - Type: thread
    name: sharedConversation
    value: "Shared thread for agent handoffs"
```

### Message Variables
Used to influence input prompts or capture agent responses. Passed by value between agents.

```yaml
variables:
  - Type: userDefined
    name: planningOutput
    value: "Planning results to pass to execution agent"
```


This comprehensive specification enables developers to create sophisticated multi-agent applications using Microsoft Discovery. Standard agents handle individual tasks, while workflow agents orchestrate multiple agents to complete complex processes with clear definitions, examples, and best practices for both types of agents.

## Summary

By following these best practices and guidelines, you can create a high-quality multi-agent system using the YAML schema tailored for scientific research or any complex domain. Ensure each section of the YAML is clearly defined and validated to provide a seamless experience for users and reliable interactions between agents.

**Key Takeaways**:
- **Agent Types**: Microsoft Discovery supports standard agents for individual tasks and workflow agents for orchestrating complex multi-agent processes.
- **Modular Design**: Break down the problem into multiple agents each with a focused role (this mimics scientific teams where different experts handle different facets of a project).
- **Clear Specification**: Use the YAML fields to clearly specify what each agent does, which model it uses, and how it proceeds with its tasks (for workflow agents, this includes the orchestration logic).
- **Leverage Planning**: Planning constructs allow agents to figure out sub-tasks – use this to your advantage in complex problem-solving scenarios like research.
- **Tool Integration**: Extend agent capabilities with tools for data retrieval or computation. This ensures the language model is supported by factual and domain-specific operations, improving performance and accuracy.
- **Iterative Refinement**: Use workflow agent logic for agents to refine their outputs (similar to how scientists iteratively refine hypotheses and experiments).
- **Testing and Tuning**: Multi-agent systems can be complex; invest time in testing scenarios and tuning directives or model choices for optimal results.

For hands-on learning and practical implementation, explore our step-by-step tutorials:

## 📚 **Related Tutorials**

**Getting Started with Agents** (recommended order):
- **[Tutorial 1: Single Agent - Response Generation (Q&A)](c--tutorial-01-single-agent-qa.md)** - Learn to create basic Q&A agents
- **[Tutorial 2: Single Agent with Knowledge Base](d--tutorial-02-single-agent-kb.md)** - Integrate knowledge bases for enhanced responses  
- **[Tutorial 3: Single Agent with Tools](e--tutorial-03-single-agent-tools.md)** - Use computational tools for complex tasks
- **[Tutorial 4: Multi-Agent Workflow](f--tutorial-04-multi-agent-workflow.md)** - Orchestrate multiple agents for complex scientific workflows

These tutorials provide practical examples based on the specifications outlined in this document.
