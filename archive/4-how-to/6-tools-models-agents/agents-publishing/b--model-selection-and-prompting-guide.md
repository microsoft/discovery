# Model Selection and Prompting Guide

## Table of Contents

1. [Model Selection and Prompt Tuning Guidance](#model-selection-and-prompt-tuning-guidance)
2. [Prompting Guide for Different Models](#prompting-guide-for-different-models) 
   - [GPT-4.1 Model Prompting Guide](#gpt-41-model-prompting-guide)
   - [GPT-o3/o4-mini Model Prompting Guide](#gpt-o3o4-mini-model-prompting-guide)

## Model Selection and Prompt Tuning Guidance

Modern LLMs used in these agents (such as GPT-4.1 family models and their mini versions) have certain behaviors and require prompting techniques:
- **GPT-4.1 vs earlier GPT-4o**: GPT-4.1 is noted to follow instructions more literally and precisely. When using such models, ensure your instructions and descriptions are unambiguous. A single sentence clarification can steer the model significantly.

> **💡 Model Selection for Agent Use Cases:**
> - **GPT-4o** is recommended for agents that **run tools extensively**. It has been observed to perform tool execution more reliably and efficiently.
> - **GPT-4.1** is recommended for agents focused on **reasoning and content generation**. It can perform better than GPT-4o in tasks requiring deep analysis, writing, and complex reasoning.
> - **⚠️ GPT-4.1 Tool Execution Restrictions:** GPT-4.1 has limitations with tool execution reliability and is not recommended for tool-heavy workflows. Use GPT-4o for agents requiring frequent or complex tool invocations.
> 
> Consider your agent's primary function when selecting a model to optimize performance.

**Prompt Behavior in YAML**:
The YAML effectively sets up system prompts for the agent. For example, the `instructions` field is part of a system-level prompt about the agent's identity or role, and instruction fields become parts of user or system prompts during workflow execution. While you can't directly write the prompt, you influence it via these fields.

**Examples of Effective Prompt Tuning**:
- Use workflow instructions to induce chain-of-thought. For instance: *"List the steps and plan extensively before proceeding to actions."* This encourages the model to output a step-by-step plan.
- **Chain-of-Thought in Agent Instructions**: If you want an agent to explain its reasoning (which might be useful for traceability in research), you might include in the instructions: *"Explain the reasoning behind the conclusion in the report."* This nudges the model to not just give answers but also reasoning.
- **Avoiding Hallucinations**: For knowledge-critical tasks (like summarizing facts), it's often wise to use the tools (like retrieval functions) to provide the model with the raw info. Ensure the agent uses tools to fetch data and then the instructions say something like *"Based on the provided data, ..."* to anchor the model in reality. By doing so, you reduce the model's tendency to make up information.
- **End-of-Turn Reminders**: If an agent should not stray beyond a scope, you can remind it in `instruction` (which might act like a system instruction). For example, *"This agent only uses data from the provided tools and does not speculate beyond the given information."* Such a note can improve reliability.

**Testing Prompt Outcomes**:
After configuring, simulate a run:
- Provide sample inputs and walk through the workflow manually, predicting what the model will do at each agent interaction stage.
- If possible, run the agent in a staging environment with known tasks to see if it behaves as expected (e.g., does the `LiteratureReviewAgent` indeed list papers and summarize them? Does the `DataAnalysisAgent` correctly interpret the tool's output?).

## Prompting Guide for Different Models

### GPT-4.1 Model Prompting Guide

> **⚠️ Important - Tool Execution Limitations:** While GPT-4.1 excels at reasoning and content generation tasks, it has **limited tool execution reliability** and is **not recommended for tool-heavy workflows**. GPT-4o is strongly recommended for agents that run tools extensively. 
>
> **Best Use Cases for GPT-4.1:**
> - Planning agents that generate strategies and roadmaps
> - Summarization agents that consolidate results and findings
> - Literature review and research analysis agents
> - Report and documentation generation agents
> - Content creation and reasoning-focused tasks
>
> GPT-4.1 may show inconsistent behavior when executing tools frequently. For agents requiring frequent or complex tool invocations, prefer GPT-4o.

The GPT-4.1 family of models introduces notable improvements over GPT-4o, particularly in coding, instruction following, and handling long contexts. To help developers maximize these capabilities, consider the following prompting strategies based on extensive internal testing:

- **Be Explicit and Specific**: GPT-4.1 follows instructions more literally than previous models. Clearly state your requirements and avoid ambiguity.
- **Provide Context and Examples**: Supplying relevant context or sample inputs/outputs helps the model understand your intent and produce more accurate results.
- **Induce Planning**: Encourage step-by-step reasoning by prompting the model to plan or outline its approach before generating a final answer.
- **Prompt Migration**: Some prompts effective for GPT-4o may need adjustment. If model behavior is not as expected, add a direct, unequivocal instruction—often a single clarifying sentence is enough to correct the course.
- **Leverage Steerability**: The model is highly responsive to well-specified prompts. Use this to guide tone, output structure, or reasoning style as needed.

#### System Prompt

##### Recommended Prompt Reminders for Agentic GPT-4.1 Workflows

To fully leverage the agentic capabilities of GPT-4.1, include the following three types of reminders in all agent prompts. These are optimized for agentic coding workflows but can be adapted for general agentic scenarios:

1. **Persistence Reminder**  
   Ensures the model understands it is in a multi-message turn and prevents premature termination:
   > You are an agent--please keep going until the user's query is completely resolved before ending your turn and yielding back to the user. Only terminate your turn when you are sure that the problem is solved.

2. **Tool-Calling Reminder**  
   Encourages the model to use available tools and avoid hallucination:
   > If you are not sure about file content or codebase structure pertaining to the user's request, use your tools to read files and gather the relevant information; do NOT guess or make up an answer.

3. **Planning Reminder** *(optional)*  
   Prompts the model to plan and reflect before and after tool calls:
   > You MUST plan extensively before each function call, and reflect extensively on the outcomes of previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.

##### Prompting-Induced Planning & Chain-of-Thought 

Developers can optionally prompt agents built with GPT-4.1 to plan and reflect between tool calls, rather than executing tools in an unbroken sequence. While GPT-4.1 is not inherently a reasoning model—meaning it does not produce an internal chain of thought before answering—you can induce explicit, step-by-step planning by including a planning instruction in your prompt. This approach encourages the model to "think out loud," though it may result in higher cost and latency due to increased output tokens.

GPT-4.1 is trained to perform well at agentic reasoning and real-world problem solving, so extensive prompting is often unnecessary. However, to encourage chain-of-thought (CoT) reasoning, start with a basic instruction at the end of your prompt, such as:

> *First, think carefully step by step about what documents are needed to answer the query. Then, print out the TITLE and ID of each document. Then, format the IDs into a list.*

From there, refine your CoT prompt by auditing failures in your examples and evaluations. Address systematic planning and reasoning errors with more explicit instructions. In unconstrained CoT prompts, the model may try different strategies; if you observe a particularly effective approach, codify it in your prompt.

Common sources of error include misunderstanding user intent, insufficient context gathering or analysis, or inadequate step-by-step reasoning. Address these issues with more specific and opinionated instructions as needed.

Alternatively, you can switch to a reasoning model (e.g., o3-mini) and compare the differences in planning and reasoning performance.

##### Long Context

GPT-4.1 supports a highly performant 1M token input context window, making it well-suited for long-context tasks such as structured document parsing, re-ranking, extracting relevant information from large inputs, and multi-hop reasoning. This large context capacity allows you to provide more detailed descriptions and system prompts when configuring an agent that uses the GPT-4.1 model. However, if your agent's workflow involves multiple models, ensure that extended system prompts are only included in workflow steps where GPT-4.1 is active.

GPT-4.1 exhibits outstanding instruction-following performance, enabling developers to precisely shape and control outputs for their specific use cases. Developers frequently use detailed prompts to guide agentic reasoning steps, response tone and voice, tool usage, output formatting, and topics to avoid. However, because GPT-4.1 follows instructions more literally, it is important to explicitly specify both what the model should and should not do. Prompts optimized for other models may not work as intended with GPT-4.1, since implicit rules are less likely to be inferred and explicit instructions are required for optimal results.

##### General Advice

###### System prompt/instruction construction guide

- **Prompt Structure** 

For reference, here is a good starting point for structuring the instruction for your agent:

```
## Role and Objective
Define the role and objective of your agent, e.g. You are an AI agent specialized in retrosynthesis prediction using RetroChimera.

## Instructions
Describe the main function supposed to be performed by the agent. e.g. You can predict chemical reactions for synthesizing target molecules represented as SMILES.

## Sub-categories for more detailed instructions 
You can further specify agent behavior by adding clear instructions about what the agent should and should not do. For example, you may include important operational hints, such as: "Do not use RDKit to compute molecular properties if a dedicated model-based tool for property computation is available." These targeted instructions help guide the agent's decision-making and ensure it follows best practices for tool selection and workflow execution.
# Reasoning Steps 
You can provide more sophisiticated guidance on the reasoning step. e.g. 
You need to follow the steps below on reasoning
1. Review all previous agent messages to detect any operational failures.
2. Determine the cause of any identified failure using information from knowledgebase xxxx.
3. If possible, identify a solution to address the problem.
4. If a failure is found, inform the user of the reason and suggest a recommended next step.
# Data assets access
You can provide guidance on data asset access, as it's essential for tools to enable agents to work with large volumes of data.
e.g. Important* You should never assume the structure of the contents of a data asset. You should ALWAYS check your data context for relevant data assets and preview them to learn their structure before using them in your scripts. NEVER assume the structure of the data asset.
# Output Format 
You can specifiy what's the expected output data format. e.g. 
Provide the response in Markdown format
# Final instructions and prompt to think step by step 
If a non reasoning model is used, you can guide the agent to apply CoT with prompt
e.g. First, think carefully step by step about what documents are needed to answer the query, then find .....
You can attach the variable to share the context across multiple agents within a workflow. 
Below are two examples. 
Node pool context: 
{{nodePoolContext}}

Data handling context: 
{{dataHandlingContext}}
```

- **Delimiters**

Here are some general guidelines for selecting the best delimiters for your prompt:

1. **Markdown**:  
   - Recommended as a starting point.
   - Use markdown titles for major sections and subsections (including deeper hierarchy, up to H4+).
   - Use inline backticks or code blocks to wrap code precisely.
   - Use standard numbered or bulleted lists as needed.

2. **XML**:  
   - Performs well, with improved adherence in this model.
   - Useful for precisely wrapping sections, adding metadata to tags, and enabling nesting.
   - Example of nesting examples in an `<examples>` section:
     ```xml
     <examples>
      <example1 type="Abbreviate">
       <input>San Francisco</input>
       <output>- SF</output>
      </example1>
     </examples>
     ```

3. **JSON**:  
   - Highly structured and well understood by the model, especially in coding contexts.
   - Can be more verbose and may require character escaping, adding overhead.

The model is trained to robustly understand structure in a variety of formats. Use your judgment to choose a format that provides clear information and stands out to the model. For example, if you're retrieving documents that already contain lots of XML, an XML-based delimiter may be less effective.

### GPT-o3/o4-mini Model Prompting Guide

> **⚠️ Note:** GPT-o3/o4-mini models are optimized for reasoning tasks. For agents that **run tools extensively, GPT-4o is recommended** over reasoning models for better tool execution performance.

GPT-o3/o4-mini are reasoning-optimized model that excels at tasks requiring deep analysis and step-by-step thinking. When using this model for agents:

- **Leverage Native Reasoning**: GPT-o3-mini has built-in reasoning capabilities, so you don't need to explicitly prompt for chain-of-thought as much as with other models.
- **Allow Processing Time**: This model takes longer to respond as it performs internal reasoning, so design your workflows to accommodate longer response times.
- **Focus on Complex Tasks**: Use GPT-o3-mini for agents that need sophisticated understanding, complex problem-solving, or detailed analysis.
- **Clear Problem Definition**: Provide clear, well-defined problems as the model excels when given specific objectives to reason through.

**Best Use Cases for GPT-o3/o4-mini Agents**:
- Scientific literature analysis
- Complex data interpretation
- Multi-step problem solving
- Research planning and methodology design
