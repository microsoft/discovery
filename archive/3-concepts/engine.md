# Microsoft Discovery Engine

Microsoft Discovery Engine is a feature within Discovery that acts and behaves like a colleague you can converse with, delegate to, cooperatively plan with, and hand off tasks to when working on ambitious long-duration work. The Discovery Engine is organized and driven by the purpose of the work you want to accomplish, using the rest of Discovery as resources to accomplish it.

The engine represents a fundamental shift from traditional AI interaction patterns. Rather than engaging in rapid question-and-answer exchanges, you work with the engine through delegation and collaboration over extended periods—hours and days rather than seconds and minutes. This approach is specifically designed for complex problems that benefit from sustained autonomous effort, exploration of multiple approaches, and integration of diverse tools and knowledge sources.

## Engine Components

The two main components of the Engine are Cognition and Tasks. These two components work in tandem with cognition maintaining awareness and continually managing the work to be done while Tasks organizes and captures our intent and work progress.

### [Cognition](./cognition.md)

The cognition system is an AI system that runs continuously while enabled. This system has been guided to behave with scientific and engineering rigor and maintain focus on both the long-term project objectives and the current working details. The cognition system picks which data, agents, and knowledge to use to make progress on the overall effort and manages their execution through tasking and direct interactions. Cognition is capable of performing both narrow topical reasoning and longer-term project tracking, allowing for work to persist over several days of effort if there are many steps, complex tool interactions, or feedback from physical experimentation.

Cognition operates autonomously in the background, continuously:
- Decomposing high-level objectives into actionable sub-tasks
- Selecting appropriate agents, models, and tools for each task
- Executing work and adapting based on results
- Synthesizing findings across multiple activities
- Responding to your feedback and adjusting plans accordingly

Cognition can currently be enabled and disabled manually using "Discovery Mode".

### [Tasks](./tasks.md)

The task system captures the key information to organize your work and make your intent accessible to the Discovery Engine for AI-driven assistance. Additionally the tasks system provides an asynchronous interaction to work with these AI systems by focusing on why the work is important, how it should be done, and allowing feedback at all levels of the project work.

Tasks are structured to capture:
- **What** needs to be accomplished (title and description)
- **Why** it matters (context within larger objectives)
- **How** success is measured (validation requirements)
- **Relationships** to other work (dependencies, parent tasks, related tasks)
- **Progress** over time (status, execution history, results)

Tasks provide an alternative primary interaction to chat, allowing you to focus on the intent and major outcomes independently from the ongoing execution of a specific activity.

## How the Engine Works

### The Collaboration Cycle

Working with the Discovery Engine follows a collaborative cycle:

1. **Define Objectives**: Create high-level tasks describing what you want to achieve
2. **Enable Discovery Mode**: Activate cognition to begin autonomous work
3. **Autonomous Execution**: Cognition decomposes tasks, selects resources, and executes work
4. **Periodic Review**: Check progress, review completed work, and provide feedback
5. **Refinement**: Adjust priorities, add context, modify tasks based on results
6. **Iteration**: The cycle continues until objectives are met

This cycle operates over hours and days, with you checking in periodically rather than staying constantly engaged.

### Resource Orchestration

The engine leverages the full Discovery platform:

- **[Agents](./agents.md)**: Specialized AI systems for specific types of reasoning or tasks
- **[Models](./models.md)**: Language models and other AI models for generation and analysis
- **[Tools](./tools.md)**: Computational capabilities for data access, calculations, simulations
- **[Bookshelf](./bookshelf.md)**: Knowledge bases and document collections for context
- **[Supercomputer](./supercomputer.md)**: Computing infrastructure for intensive workloads
- **Data Assets**: Datasets, results, and intermediate outputs from completed work

Cognition automatically selects and orchestrates these resources based on task requirements.

### Collaboration Patterns

The engine supports different modes of collaboration:

**Full Delegation**: You define the objective and let cognition handle all execution
- Best for exploratory work where the path isn't clear
- You review results periodically and provide strategic feedback

**Parallel Work**: You work on some tasks while cognition handles others
- Useful when you have specific expertise for certain parts
- Cognition sees your work and builds on it

**Iterative Refinement**: Cognition does initial exploration, you refine, it continues
- Good for problems where early results inform later direction
- Feedback loop between your judgment and autonomous execution

**Guided Exploration**: You set constraints and priorities, cognition explores within them
- When you have strong opinions about approach but want help with execution
- Use validation requirements and comments to guide autonomous work

## When to Use the Discovery Engine

### Ideal Use Cases

Problems that are multi-faceted, have open-ended solutions, and will take a long time to solve are all ideal uses of the Discovery Engine. The engine is designed to work alongside you, providing leverage to the ideas and investigations you wish to pursue and reacting to your feedback at all levels of detail.

**Characteristics of problems well-suited for the engine:**

- **Multi-faceted**: Require multiple approaches, tools, or domains of knowledge
- **Open-ended**: The path to the solution isn't predetermined and requires exploration
- **Long-duration**: Take hours or days rather than minutes to complete
- **Iterative**: Benefit from multiple rounds of analysis, synthesis, and refinement
- **Complex dependencies**: Some steps depend on results from others, requiring intelligent sequencing

When you enable the Discovery Engine there is a background cognition process that starts interpreting tasks and acting autonomously on your behalf. Much like a colleague, this process will find and follow paths of opportunity, and is best interacted with over a period of hours and days rather than interactively.

### Example: Ideal for the Engine

A big-picture goal like this would make a good basis for using the Discovery Engine:

> "Identify the existing drugs that treat [disease name] and their activation pathways. From this, use each active compound as the basis for an evolutionary study of different variants that have higher protein binding affinity and projected lower immune response. For the candidates that appear most promising, plan the retrosynthesis pathway for formulation in the lab."

**Why this works well:**
- Requires multiple domains of knowledge (pharmacology, biochemistry, synthesis)
- Has an open-ended exploration phase (finding variants)
- Will take substantial time to complete (days of work)
- Involves complex tool orchestration (databases, modeling, pathway planning)
- Benefits from autonomous exploration while you focus on strategic decisions

### Example: Not Ideal for the Engine

Conversely, relatively simple queries where a rapid response is desired are less ideal. For example, this request would not be a good candidate for the full engine:

> "What is the reduction potential of [chemical]?"

**Why direct interaction is better:**
- Single, well-defined question
- Quick lookup or calculation
- Immediate answer needed
- No complex dependencies or exploration required

### Decision Guide

**Use the Discovery Engine when:**
- You can describe the goal but not the exact steps
- The work will span multiple sessions over hours or days
- You want to delegate exploration and come back to review results
- Multiple approaches might work and you want autonomous exploration
- The problem requires coordinating many tools, agents, and knowledge sources

**Use direct chat or specific agents when:**
- You have a specific, well-defined question
- You need an immediate response
- You want to guide every step interactively
- The task is simple enough to complete in one interaction
- You already know exactly what tools or approach to use

## Getting Started with the Engine

### Quick Start

1. **Enable Discovery Mode**: Turn on cognition in the interface
2. **Create a high-level task** or **Ask for help with an objective**: Describe what you want to achieve
3. **Let it run**: Step away and let cognition work for a few hours
4. **Review progress**: Check what's been completed and what's in progress
5. **Provide feedback**: Add comments, adjust priorities, refine tasks
6. **Continue**: Let cognition incorporate your feedback and keep working

### Effective Task Definition

For the engine to work well, define tasks that:
- Focus on **outcomes**, not procedures
- Include **context** about why it matters
- Specify **validation requirements** for measuring success
- Are scoped appropriately (not too broad, not too narrow)

### Monitoring and Feedback

Track progress through:
- **Task status**: See what's in progress, completed, or blocked
- **Execution history**: Review what approaches were tried
- **Data assets**: Examine outputs and intermediate results
- **System activity**: Observe agent and tool invocations

Provide feedback by:
- **Adding comments**: Explain what's good or needs adjustment
- **Modifying tasks**: Update descriptions or validation requirements
- **Adjusting priorities**: Reorder what matters most
- **Adding new tasks**: Introduce new directions to explore

## Best Practices

### Do's

✅ **Start with clear objectives**: Define what you want to achieve and why
✅ **Trust autonomous exploration**: Let cognition try different approaches
✅ **Check in periodically**: Review progress every few hours
✅ **Provide strategic feedback**: Guide direction, not tactical choices
✅ **Use validation requirements**: Specify concrete success criteria
✅ **Think in days, not minutes**: Complex work takes time to explore properly

### Don'ts

❌ **Don't micromanage**: Avoid specifying every step or tool to use
❌ **Don't watch constantly**: This isn't designed for real-time interaction
❌ **Don't start with tiny tasks**: Let cognition decompose high-level objectives
❌ **Don't abandon it**: Periodic review and feedback keep work on track
❌ **Don't expect instant results**: This model trades speed for thoroughness

## Troubleshooting

**Engine isn't making progress:**
- Verify Discovery Mode is enabled
- Check if tasks have clear validation requirements
- Review execution history to see if cognition is stuck
- Add comments with additional context or guidance

**Results don't match expectations:**
- Refine validation requirements to be more specific
- Add comments explaining what you're looking for
- Create new related tasks for specific directions to explore

**Too much or too little decomposition:**
- Adjust task descriptions to clarify scope
- Mark irrelevant sub-tasks as cancelled
- Add parent tasks to group related work

## See Also

- **[Working with Tasks and the Discovery Engine](../4-how-to/13-task-driven-work/a--working-with-tasks-and-engine.md)** - Comprehensive how-to guide
- **[Cognition](./cognition.md)** - Deep dive into autonomous reasoning
- **[Tasks](./tasks.md)** - Task structure and best practices
- **[Creating an Investigation](../4-how-to/8-investigations/a--creating-investigation.md)** - Organizing related efforts



