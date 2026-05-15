# Microsoft Discovery Agents

This documentation provides an overview of the AI agents concept available in Microsoft Discovery, including their types and usage with different user scenarios.

## Agents Overview

### What are Agents in Microsoft Discovery?

A Microsoft Discovery Agent is a runtime AI assistant that executes tasks on behalf of a user, often as part of a user-defined workflow. Agents handle data operations and coordinate tool or model execution across compute environments.

Agents are implemented using reasoning engines, grounding skills, and action skills. The agents' behavior is programmed using instructions (prompts) provided in natural language, enabling sophisticated scientific reasoning and engineering,  and decision-making.

## Agent Types

The agents in Microsoft Discovery could be used for varying purposes:

- **Specialized Research Agents:** These agents are designed for operation of specific scientific tools or models in Microsoft Discovery. An example of a specialized research agent is a molecular dynamics analysis agent that uses GROMACS tools for protein folding studies.  Another example of a specialized agent is one for engineering simulation, such as a circuit analysis agent that uses SPICE tools to verify integrated circuit designs.

- **Workflow Agents:** Workflow agent can be thought of as a top-level agent that orchestrates the overall flow. It's a multi-agent program that orchestrates the execution of multiple agents to complete complex research tasks. Workflows enable researchers and engineers to create sophisticated, multi-step research processes that can adapt and respond to different scenarios, making the Microsoft Discovery platform particularly powerful for complex R&D operations. Generally a workflow agent is defined using:
  - **Variables**: To model data flow between agents throughout the research process
  - **Transitions**: To model control flow between agents based on research outcomes
  - **States**: To bind the agents and configure their behaviors for specific scientific operations

- **Other functional Agents:**  They handle the overall planning, resource allocation, and decision-making processes that determine which agents should be activated and in what sequence. Some functional agents are valuable for managing multi-step research processes that require coordination between different scientific and engineering domains. An example could be a research planning agent that coordinates literature review, experimental design, and result analysis across multiple scientific domains.

For any of the agent types mentioned above, developers need to provide agent definitions that specify the AI model to use, behavioral instructions, tool integrations, and workflow configurations. This ensures that agents can operate effectively within the Microsoft Discovery platform's secure and high-performance environment.

