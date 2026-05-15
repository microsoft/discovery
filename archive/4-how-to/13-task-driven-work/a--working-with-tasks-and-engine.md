# Working with Tasks and the Discovery Engine

This guide explains how to approach complex problems using task-driven work with the Discovery Engine, shifting from traditional call-response AI interactions to a collaborative, long-running workflow.

## Understanding the Paradigm Shift

If you're familiar with working with AI agents through conversational interfaces, you're accustomed to:
- Asking a question and getting an immediate response
- Breaking down work yourself into sequential prompts
- Staying engaged throughout the entire process
- Managing context manually across multiple interactions

The Discovery Engine introduces a different model:
- **Delegation over conversation**: You define what needs to be done, not how to do it step-by-step
- **Asynchronous progress**: Work continues in the background while you focus on other priorities
- **Ambient assistance**: The engine maintains context and makes decisions autonomously
- **Feedback loops**: You review, refine, and redirect rather than micromanage each step

Think of it as the difference between pair programming (constant back-and-forth) and collaborating with a colleague (delegating tasks, checking in periodically, providing feedback on completed work).

## When to Use Task-Driven Work

### Ideal Scenarios

Task-driven work with the Discovery Engine excels when:

- **Multi-faceted problems**: The solution requires multiple approaches, tools, or domains of knowledge
- **Open-ended exploration**: You don't know the exact path to the solution upfront
- **Long-duration efforts**: Work that takes hours or days rather than minutes
- **Iterative refinement**: Solutions that need multiple rounds of analysis and feedback
- **Complex dependencies**: Work where some steps depend on the results of others

**Example**: "Analyze the competitive landscape for protein folding prediction tools, evaluate their methodologies, and propose three novel approaches that address current limitations."

### When to Use Traditional Approaches

Stick with direct chat or specific agent calls for:

- **Quick queries**: Simple questions with straightforward answers
- **Immediate results**: When you need an answer right now to continue your work
- **Well-defined single steps**: Tasks that are already atomic and clear
- **Interactive exploration**: When you want to guide every decision in real-time

**Example**: "What is the molecular weight of caffeine?"

## Getting Started with Task-Driven Work

### Step 1: Enable Discovery Mode

Before creating tasks, enable Discovery Mode to activate the cognition system. This starts the background reasoning process that will work on your behalf.

⚠️ **Warning!** Discovery Mode may incur substantial additional costs due to background autonomous processing. Monitor your usage accordingly and disable when not needed.

**Note**: The cognition service can process a maximum of 10 active Cogloop instances at a time. Tasks within each refinement are queued, and quota is allocated per Cogloop instance. If you experience delays in task processing, this limit may be a factor.

### Step 2: Define Your High-Level Objective as a Task

In the Discovery UI, navigate to the "Tasks" panel and create a new task that captures your overall goal.

Start with your end goal, not the individual steps. A good objective:
- Describes **what** you want to achieve, not **how**
- Includes context about **why** it matters
- Specifies how you'll **measure success**

**Example of a well-formed objective:**

```
Title: Identify drug repurposing candidates for rare disease X

Description: We need to find existing FDA-approved drugs that could 
potentially treat rare disease X. Focus on drugs with mechanisms of 
action that interact with the three known protein targets (A, B, C) 
associated with this disease.

Validation Requirements: 
- At least 10 candidate drugs identified
- Each candidate must have documented mechanism of action
- Include analysis of potential side effects and contraindications
- Provide confidence scores based on protein binding affinity data
```

### Step 3: Let the Engine Decompose the Work

Once you create your high-level task, the Discovery Engine (through cognition) will:
- Analyze the objective
- Break it down into sub-tasks
- Identify dependencies
- Begin executing tasks autonomously

You'll see sub-tasks appear automatically as the engine plans the work. This might include tasks like:
- Literature search for disease mechanisms
- Query protein databases for target information
- Screen drug databases against targets
- Analyze interaction patterns
- Synthesize findings

### Step 4: Review and Refine as Work Progresses

As work progresses, you can:

**Review execution history**: Check what the engine has tried and what results it found

**Provide feedback on results**: Add comments to guide future efforts
```
"The binding affinity threshold seems too loose. Focus on compounds 
with KD values below 100nM."
```

**Adjust task priorities**: Reorder tasks if certain areas are more critical

**Add new tasks**: If you identify gaps or new opportunities
```
"Also check for natural compounds that might serve as scaffolds for 
novel drug development"
```

**Modify validation requirements**: Clarify success criteria if the initial results don't match expectations

### Step 5: Iterate and Collaborate

The engine works best when you treat it as a collaborative partner:

- **Check in periodically** (every few hours for long efforts)
- **Don't micromanage** - let the engine explore approaches
- **Provide direction, not instructions** - guide the "what" and "why," not the "how"
- **Build on partial results** - review intermediate findings and adjust course
- **Add context as needed** - if the engine seems stuck, provide additional context through comments

## Structuring Effective Tasks

### Task Hierarchy

Organize tasks in a hierarchy that reflects the natural decomposition of work:

```
🎯 Main Objective: Drug repurposing for disease X
  ├─ 📋 Task 1: Identify disease mechanisms
  │   ├─ 📋 Subtask 1.1: Literature review
  │   ├─ 📋 Subtask 1.2: Pathway analysis
  │   └─ 📋 Subtask 1.3: Target validation
  ├─ 📋 Task 2: Screen drug databases
  │   ├─ 📋 Subtask 2.1: Query FDA-approved drugs
  │   └─ 📋 Subtask 2.2: Filter by mechanism
  └─ 📋 Task 3: Analyze candidates
      ├─ 📋 Subtask 3.1: Binding affinity analysis
      └─ 📋 Subtask 3.2: Safety profile review
```

### Essential Task Components

For each task, focus on these elements:

**Title**: Clear, action-oriented (5-10 words)
- ✅ "Analyze protein-drug interactions for top 10 candidates"
- ❌ "Proteins and drugs"

**Description**: Context and objectives (2-4 sentences)
- What needs to be done
- Why it matters to the overall goal
- Any constraints or specific requirements

**Validation Requirements**: Concrete success criteria
- Measurable outcomes
- Quality thresholds
- Deliverable format

**Dependencies**: Link related tasks
- `Depends on`: Tasks that must complete first
- `Related to`: Tasks with shared context or resources

## Working Cooperatively with Cognition

### What Cognition Handles

The cognition system autonomously:
- Selects appropriate agents, models, and tools
- Sequences work based on dependencies
- Parallelizes independent tasks
- Retries failed attempts with different approaches
- Synthesizes results across multiple sub-tasks
- Identifies when additional information is needed

### Your Role as the Human

You provide:
- **Strategic direction**: What problems matter and why
- **Domain expertise**: Context the AI doesn't have
- **Quality judgment**: Whether results meet your standards
- **Course corrections**: When to pivot or dig deeper
- **Constraint setting**: Resource limits, ethical boundaries, priorities

### Communication Patterns

**Instead of instructing step-by-step:**
```
❌ "First, search PubMed for papers on disease X. Then extract the 
protein targets mentioned. Then query DrugBank for each target..."
```

**Define outcomes and let cognition plan:**
```
✅ "Find existing drugs that interact with the protein targets 
associated with disease X. Prioritize FDA-approved drugs with 
strong clinical evidence."
```

**Instead of asking yes/no questions:**
```
❌ "Should we also look at drugs in clinical trials?"
```

**Add tasks or modify validation requirements:**
```
✅ [Create new task] "Expand search to include drugs in Phase 2/3 
clinical trials that target the same pathways"
```

## Example Workflows

### Example 1: Research Synthesis

**Scenario**: You need to understand the current state of quantum error correction techniques.

**Traditional approach**: Multiple sequential queries
```
"What are the main quantum error correction codes?"
"How does the surface code work?"
"What are the error rates for surface codes?"
"Compare surface codes to other approaches..."
```

**Task-driven approach**:
```
Title: Comprehensive analysis of quantum error correction landscape

Description: Provide a detailed analysis of current quantum error 
correction techniques, including their theoretical foundations, 
practical implementations, performance metrics, and trade-offs. 
This will inform our hardware architecture decisions.

Validation Requirements:
- Cover at least 5 major error correction schemes
- Include performance data from experimental implementations
- Compare trade-offs in terms of qubit overhead, error rates, and 
  computational complexity
- Identify 2-3 most promising approaches for near-term applications
```

Then step away and check back in a few hours.

### Example 2: Iterative Exploration

**Scenario**: You're exploring different synthesis pathways for a novel compound.

**Initial task**:
```
Title: Design synthesis pathway for compound ABC-123

Description: Identify feasible synthesis routes for compound 
ABC-123 starting from commercially available precursors. Optimize 
for yield, cost, and safety.

Validation Requirements:
- At least 3 distinct synthesis routes
- Each route should have >50% theoretical yield
- Include cost estimates and hazard assessments
```

**After reviewing results, add feedback**:
```
Comment on Route 2: "This route looks promising but the lithium 
aluminum hydride step is concerning for scale-up. Can we find an 
alternative reducing agent?"
```

**Add a new related task**:
```
Title: Evaluate alternative reducing agents for Route 2, Step 4

Description: The LAH reduction in Route 2 isn't practical for 
scale-up. Find alternative reducing agents that are safer and 
more cost-effective while maintaining selectivity.
```

The engine continues work, incorporating your feedback without needing you to specify every approach to try.

## Best Practices

### Do's

✅ **Start broad, refine iteratively**: Begin with high-level objectives and add detail as work progresses

✅ **Trust the engine to explore**: Let cognition try different approaches without micromanaging

✅ **Provide rich context**: Include why something matters, not just what to do

✅ **Review asynchronously**: Check in at natural breakpoints rather than watching constantly

✅ **Use validation requirements**: Specify concrete success criteria to guide autonomous work

✅ **Link related tasks**: Use dependencies and relationships to provide context

✅ **Add comments generously**: Feedback helps the engine learn your preferences

### Don'ts

❌ **Don't specify implementation details**: Let the engine choose tools and methods

❌ **Don't stay in chat**: Tasks are the primary interface for long-running work

❌ **Don't create overly atomic tasks**: Some decomposition is good, but let the engine handle fine-grained steps

❌ **Don't expect instant results**: This model works over hours and days, not seconds

❌ **Don't abandon context**: Even though work is asynchronous, periodic review keeps things on track

❌ **Don't treat it like a chatbot**: You're delegating to a colleague, not prompting a tool

## Troubleshooting Common Issues

### "The engine isn't making progress"

- Check if Discovery Mode is enabled
- Review validation requirements - are they specific enough?
- Look at execution history - is it stuck on a particular step?
- Add a comment with additional context or guidance

### "Results don't match what I wanted"

- Refine validation requirements to be more specific
- Add a comment explaining what's wrong and what you're looking for
- Create a new related task that explores the specific direction you want

### "Too many sub-tasks are being created"

- Simplify your validation requirements
- Consolidate related tasks
- Adjust task descriptions to be less ambiguous

### "The work is going in the wrong direction"

- Add comments to course-correct
- Adjust task priorities
- Cancel or mark irrelevant tasks as blocked
- Create new tasks that better capture your intent

## Next Steps

- See [Tasks concept](../../3-concepts/tasks.md) for detailed task structure reference
- See [Cognition concept](../../3-concepts/cognition.md) to understand how autonomous reasoning works
- See [Engine concept](../../3-concepts/engine.md) for the overall architecture
- See [Creating an Investigation](../8-investigations/a--creating-investigation.md) to organize multiple related efforts

## Summary

Task-driven work with the Discovery Engine represents a shift from interactive prompting to collaborative delegation. By structuring your work as tasks with clear objectives and validation criteria, you enable the cognition system to work autonomously on your behalf while you focus on strategic direction and quality oversight. This approach is ideal for complex, multi-faceted problems that benefit from ambient assistance over extended periods.

The key is to think like you're working with a capable colleague: communicate the goal and why it matters, provide feedback on results, and trust them to figure out the details. The engine handles the tactical execution while you maintain strategic control.
