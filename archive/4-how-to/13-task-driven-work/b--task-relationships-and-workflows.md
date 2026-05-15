# Task Relationships and Basic Workflows

This guide explains how to use task relationships—particularly "parent of" and "depends on"—to create structured workflows that help cognition understand how your work is organized and what order things need to happen.

## Understanding Task Relationships

Tasks in Discovery can be related to each other in several ways. These relationships serve two key purposes:

1. **Organizational**: Help you (and cognition) understand how tasks fit together conceptually
2. **Functional**: Control the order of execution and ensure prerequisites are met

The two most important relationships for building workflows are:

- **Parent of** (or "has subtasks"): Hierarchical decomposition of work
- **Depends on**: Execution dependencies between tasks

## Parent-Child Relationships

### What It Means

When Task A is the **parent** of Task B, it means:
- Task B is a component of the work needed to complete Task A
- Task B is more specific/concrete than Task A
- Completing all children is (usually) necessary to complete the parent
- Task B inherits context from Task A

Think of it as decomposition: breaking down a large objective into smaller, manageable pieces.

### When to Use Parent-Child Relationships

Use parent-child relationships when:
- A task is too broad to tackle as a single unit
- You want to organize work into logical groups
- You need to track progress on multiple aspects of a larger goal
- You want to delegate different parts of a bigger effort

### Example: Research Project

```
🎯 Parent: Analyze competitive landscape for AI code assistants
  ├─ 📋 Child 1: Identify all major AI code assistants in market
  ├─ 📋 Child 2: Compare feature sets and capabilities
  ├─ 📋 Child 3: Analyze pricing models and market positioning
  └─ 📋 Child 4: Synthesize findings into competitive analysis report
```

**Why this structure works:**
- Each child is a distinct aspect of the larger analysis
- Children can potentially be worked on in parallel (though some may depend on others)
- Progress on the parent is visible through child completion
- Context flows down: all children understand they're about "AI code assistants"

### Creating Parent-Child Structures

**Start with the parent:**
```
Title: Optimize synthesis pathway for compound XYZ-789

Description: Our current synthesis has low yield (23%) and uses 
expensive reagents. Find alternative pathways that improve yield 
above 50% and reduce reagent costs by at least 30%.

Validation Requirements:
- At least 2 viable alternative pathways identified
- Each pathway has projected yield >50%
- Cost analysis showing ≥30% reduction
- Safety assessment for each pathway
```

**Let cognition create children, or add them yourself:**
```
Title: Literature review of XYZ-789 synthesis methods
Parent: Optimize synthesis pathway for compound XYZ-789

Description: Search chemical databases and literature for existing 
synthesis methods for XYZ-789 or structurally similar compounds.

Title: Screen alternative reagents for key reduction step
Parent: Optimize synthesis pathway for compound XYZ-789

Description: The current LAH reduction is expensive. Evaluate 
alternative reducing agents that maintain selectivity.
```

### Best Practices

✅ **Keep hierarchy shallow**: 2-3 levels is usually sufficient. Deeper hierarchies become hard to manage.

✅ **Make children actionable**: Each child should be concrete enough that you know what "done" looks like.

✅ **Don't over-decompose**: If a task is small and clear, don't force it to have children.

✅ **Use consistent granularity**: Children at the same level should be roughly similar in scope.

❌ **Don't mix concepts**: All children should contribute to the same parent objective.

## Depends-On Relationships

### What It Means

When Task A **depends on** Task B, it means:
- Task A cannot start (or complete) until Task B is done
- Task B's results or outputs are needed for Task A
- There's a logical or functional prerequisite relationship
- Cognition will not execute Task A until Task B is complete

This creates a **precedence constraint**: B must happen before A.

### When to Use Dependencies

Use depends-on relationships when:
- One task needs the results or outputs from another
- The approach for Task A depends on what you learn from Task B
- There's a logical sequence that must be followed
- Starting Task A before Task B would be wasteful or impossible

### Example: Sequential Analysis

```
📋 Task 1: Collect experimental data from instrument
    ↓
📋 Task 2: Clean and validate the dataset
    (depends on: Task 1)
    ↓
📋 Task 3: Perform statistical analysis
    (depends on: Task 2)
    ↓
📋 Task 4: Generate visualization and report
    (depends on: Task 3)
```

**Why dependencies matter here:**
- Task 2 literally needs the data from Task 1
- Task 3 needs clean data from Task 2
- Task 4 needs analysis results from Task 3
- Without dependencies, cognition might try to do these in parallel or wrong order

### Creating Dependencies

**Explicit dependencies:**
```
Title: Evaluate drug candidates against disease targets

Description: Screen the candidates from the previous task against 
our three protein targets using molecular docking.

Depends on: "Identify FDA-approved drugs with relevant mechanisms"

Validation Requirements:
- Docking scores for all candidates against all three targets
- Ranked list by binding affinity
- Top 10 candidates identified for detailed analysis
```

**Why this dependency exists:**
- Can't screen candidates until you know what the candidates are
- The list of candidates is the direct input to this task
- Results of one task are the input to another

### Types of Dependencies

**Data Dependency**: Task A needs data produced by Task B
```
Task B: Extract protein sequences from database
Task A: Perform multiple sequence alignment
(A depends on B because it needs the sequences)
```

**Knowledge Dependency**: Task A needs insights from Task B
```
Task B: Literature review of treatment approaches
Task A: Design novel treatment strategy
(A depends on B because insights inform the design)
```

**Validation Dependency**: Task A needs to confirm Task B succeeded
```
Task B: Deploy updated model to production
Task A: Run integration tests
(A depends on B because you must deploy before testing)
```

**Logical Dependency**: Task A only makes sense after Task B
```
Task B: Identify failure modes in current design
Task A: Propose design modifications to address failures
(A depends on B because you need to know what to fix)
```

## Combining Parent-Child and Dependencies

The real power comes from using both relationship types together to create structured workflows.

### Pattern 1: Sequential Phases

Organize work into phases where all tasks in one phase must complete before the next phase begins.

```
🎯 Parent: Drug repurposing study for Disease X

  📋 Phase 1: Understand disease mechanisms
  ├─ Task 1.1: Literature review
  ├─ Task 1.2: Protein target identification
  └─ Task 1.3: Pathway analysis

  📋 Phase 2: Identify candidate drugs
  ├─ Task 2.1: Query drug databases
  ├─ Task 2.2: Filter by mechanism of action
  └─ Task 2.3: Screen for contraindications
  (Depends on: Phase 1)

  📋 Phase 3: Evaluate candidates
  ├─ Task 3.1: Molecular docking analysis
  ├─ Task 3.2: Pharmacokinetic modeling
  └─ Task 3.3: Safety profile assessment
  (Depends on: Phase 2)
```

**How this works:**
- Parent-child groups related tasks within each phase
- Dependencies ensure phases happen in order
- Tasks within a phase can happen in parallel (unless they also have dependencies)
- Progress is visible at both phase and overall project level

### Pattern 2: Pipeline with Branches

Some work splits into parallel tracks that later reconverge.

```
🎯 Parent: Comprehensive materials analysis

  📋 Task 1: Prepare sample
  
  📋 Task 2: X-ray diffraction analysis
  (Depends on: Task 1)
  
  📋 Task 3: Electron microscopy
  (Depends on: Task 1)
  
  📋 Task 4: Spectroscopy analysis
  (Depends on: Task 1)
  
  📋 Task 5: Synthesize all analytical results
  (Depends on: Task 2, Task 3, Task 4)
```

**How this works:**
- Task 1 is a single prerequisite for multiple downstream tasks
- Tasks 2, 3, 4 can run in parallel (they share a dependency but not on each other)
- Task 5 waits for all analyses to complete
- Maximizes parallelism while ensuring prerequisites

### Pattern 3: Hierarchical Dependencies

Dependencies can exist at any level of the hierarchy.

```
🎯 Parent: Optimize machine learning model

  📋 Group 1: Data preparation
  ├─ Task 1.1: Collect raw data
  ├─ Task 1.2: Clean and validate
  │   (Depends on: Task 1.1)
  └─ Task 1.3: Feature engineering
      (Depends on: Task 1.2)

  📋 Group 2: Model training
  ├─ Task 2.1: Train baseline model
  ├─ Task 2.2: Hyperparameter tuning
  │   (Depends on: Task 2.1)
  └─ Task 2.3: Ensemble methods exploration
      (Depends on: Task 2.1)
  (Depends on: Group 1)

  📋 Group 3: Evaluation and deployment
  ├─ Task 3.1: Validation set evaluation
  ├─ Task 3.2: Model explainability analysis
  └─ Task 3.3: Production deployment
      (Depends on: Task 3.1)
  (Depends on: Group 2)
```

**How this works:**
- Dependencies within groups (1.2→1.1, 1.3→1.2)
- Dependencies between groups (Group 2→Group 1, Group 3→Group 2)
- Mix of sequential (1.1→1.2→1.3) and parallel (2.2 and 2.3 both from 2.1)
- Clear flow from data to training to deployment

## Building Your First Workflow

### Step 1: Identify the Main Objective

Start with the high-level goal:
```
Title: Develop predictive model for protein-ligand binding affinity

Description: Build a machine learning model that predicts binding 
affinity (Kd) between proteins and small molecules with R² > 0.8 
on held-out test set.
```

### Step 2: Identify Major Phases or Components

Break down into 3-5 major pieces:
```
- Data collection and preparation
- Feature engineering and selection
- Model development and training
- Validation and optimization
- Documentation and deployment
```

### Step 3: Create Child Tasks for Each Phase

```
📋 Data collection and preparation
├─ Gather binding affinity datasets from public databases
├─ Combine and deduplicate entries
└─ Split into train/validation/test sets

📋 Feature engineering and selection
├─ Generate molecular descriptors for ligands
├─ Generate protein descriptors
└─ Feature selection and dimensionality reduction
```

### Step 4: Add Dependencies

Identify what must happen in sequence:
```
📋 Data collection and preparation
  
📋 Feature engineering and selection
(Depends on: Data collection and preparation)

📋 Model development and training
(Depends on: Feature engineering and selection)

📋 Validation and optimization
(Depends on: Model development and training)
```

### Step 5: Refine with Sub-Dependencies

Within groups, identify internal ordering:
```
📋 Data collection and preparation
├─ Gather binding affinity datasets
├─ Combine and deduplicate entries
│   (Depends on: Gather datasets)
└─ Split into train/validation/test sets
    (Depends on: Combine and deduplicate entries)
```

### Step 6: Add Validation Requirements

For each task, specify success criteria:
```
Title: Generate molecular descriptors for ligands

Description: Calculate a comprehensive set of molecular descriptors 
(topological, physicochemical, fingerprints) for all ligands in 
the dataset.

Depends on: "Split into train/validation/test sets"

Validation Requirements:
- Descriptors calculated for 100% of ligands
- At least 50 different descriptor types
- No missing values
- Descriptors saved in standardized format (CSV/HDF5)
- Documentation of descriptor definitions
```

## Common Patterns to Avoid

### Anti-Pattern 1: Circular Dependencies

❌ **Don't do this:**
```
Task A depends on Task B
Task B depends on Task C
Task C depends on Task A  ← Circular!
```

This creates a deadlock where nothing can start. If you find yourself creating circular dependencies, you likely need to rethink your task decomposition.

### Anti-Pattern 2: Everything Depends on Everything

❌ **Don't do this:**
```
Task A depends on: B, C, D, E, F, G
Task B depends on: A, C, D, E, F, G
Task C depends on: A, B, D, E, F, G
...
```

Over-constraining dependencies eliminates parallelism. Only create dependencies where there's a real prerequisite relationship.

### Anti-Pattern 3: Deep Hierarchies with No Parallelism

❌ **Don't do this:**
```
🎯 Parent
  └─ Child 1
      └─ Grandchild 1
          └─ Great-grandchild 1
              └─ Great-great-grandchild 1
```

This is both hard to manage and provides no opportunity for parallel work. Keep hierarchies shallow and look for opportunities to parallelize.

### Anti-Pattern 4: Orphaned Dependencies

❌ **Don't do this:**
```
Task A depends on Task X
(but Task X doesn't exist or is in a different project)
```

Dependencies should reference tasks that actually exist and are part of the same workflow. Broken dependencies confuse cognition.

## How Cognition Uses Relationships

Understanding how cognition interprets relationships helps you design better workflows.

### Execution Order

Cognition uses dependencies to determine what can be worked on:
- Tasks with no dependencies (or all dependencies complete) are eligible to start
- Tasks with incomplete dependencies wait
- When a task completes, cognition checks if any waiting tasks are now eligible

### Parallelization

Cognition automatically parallelizes independent work:
- Tasks without dependencies between them can run simultaneously
- Child tasks of the same parent can run in parallel unless they depend on each other
- This happens automatically—you don't need to specify parallelism

### Context Propagation

Cognition uses relationships to understand context:
- Child tasks inherit context from parents
- Tasks with dependencies see the results of prerequisite tasks
- Related tasks (even without dependencies) are considered as shared context

### Progress Tracking

Relationships affect how progress is calculated:
- A parent task's progress is based on child task completion
- Dependencies help estimate when waiting tasks will become available
- Overall project progress considers the critical path through dependencies

## Practical Examples

### Example 1: Literature Review and Synthesis

**Scenario**: You need to understand current research on a topic and synthesize findings.

```
🎯 Parent: Comprehensive review of quantum error correction

  📋 Task 1: Identify relevant papers and sources
  
  📋 Task 2: Analyze surface code approaches
  (Depends on: Task 1)
  
  📋 Task 3: Analyze topological code approaches
  (Depends on: Task 1)
  
  📋 Task 4: Analyze concatenated code approaches
  (Depends on: Task 1)
  
  📋 Task 5: Compare approaches and identify trade-offs
  (Depends on: Task 2, Task 3, Task 4)
  
  📋 Task 6: Write comprehensive review document
  (Depends on: Task 5)
```

**Why this works:**
- Task 1 identifies what to read (prerequisite for all analysis)
- Tasks 2, 3, 4 analyze different approaches in parallel
- Task 5 synthesizes after all approaches are understood
- Task 6 documents findings after synthesis

### Example 2: Experimental Workflow

**Scenario**: Run experiments, analyze results, iterate.

```
🎯 Parent: Optimize catalyst performance

  📋 Phase 1: Baseline measurement
  ├─ Task 1.1: Prepare baseline catalyst
  ├─ Task 1.2: Run baseline experiments
  │   (Depends on: Task 1.1)
  └─ Task 1.3: Analyze baseline performance
      (Depends on: Task 1.2)

  📋 Phase 2: Test variations
  ├─ Task 2.1: Design experimental variations
  ├─ Task 2.2: Prepare variant catalysts
  │   (Depends on: Task 2.1)
  ├─ Task 2.3: Run variant experiments
  │   (Depends on: Task 2.2)
  └─ Task 2.4: Analyze variant performance
      (Depends on: Task 2.3)
  (Depends on: Phase 1)

  📋 Phase 3: Optimization
  ├─ Task 3.1: Identify best-performing variations
  ├─ Task 3.2: Design refined experiments
  │   (Depends on: Task 3.1)
  └─ Task 3.3: Run optimization experiments
      (Depends on: Task 3.2)
  (Depends on: Phase 2)
```

**Why this works:**
- Clear phases: baseline → variations → optimization
- Dependencies within phases ensure proper sequencing
- Phase dependencies prevent jumping ahead
- Results from earlier phases inform later work

### Example 3: Multi-Track Development

**Scenario**: Develop multiple components that come together at the end.

```
🎯 Parent: Build data analysis pipeline

  📋 Task 1: Define data schema and requirements
  
  📋 Track A: Data ingestion module
  ├─ Task A1: Design ingestion architecture
  ├─ Task A2: Implement data connectors
  │   (Depends on: Task A1)
  └─ Task A3: Add validation logic
      (Depends on: Task A2)
  (Depends on: Task 1)
  
  📋 Track B: Processing engine
  ├─ Task B1: Design processing pipeline
  ├─ Task B2: Implement core transformations
  │   (Depends on: Task B1)
  └─ Task B3: Add error handling
      (Depends on: Task B2)
  (Depends on: Task 1)
  
  📋 Track C: Output module
  ├─ Task C1: Design output formats
  ├─ Task C2: Implement exporters
  │   (Depends on: Task C1)
  └─ Task C3: Add formatting options
      (Depends on: Task C2)
  (Depends on: Task 1)
  
  📋 Task 2: Integration and testing
  (Depends on: Track A, Track B, Track C)
  
  📋 Task 3: Documentation and deployment
  (Depends on: Task 2)
```

**Why this works:**
- All tracks depend on shared requirements (Task 1)
- Tracks A, B, C develop in parallel
- Integration waits for all tracks to complete
- Clear separation of concerns with final integration

## Tips for Effective Workflows

### Start Simple
Begin with a basic structure and add complexity only as needed. It's easier to add dependencies later than to untangle over-constrained workflows.

### Make Dependencies Explicit
If one task needs another's results, create the dependency. Don't rely on implicit ordering or hope cognition figures it out.

### Use Meaningful Names
Task titles should make the workflow self-documenting. "Task 1, Task 2, Task 3" doesn't convey meaning. "Collect data, Clean data, Analyze data" does.

### Test Your Logic
Walk through the workflow mentally: What can start immediately? What's waiting? What runs in parallel? If the logic doesn't make sense to you, it won't make sense to cognition.

### Document Rationale
Use task descriptions to explain why dependencies exist, especially if they're not obvious. This helps both you and cognition understand the workflow logic.

### Keep It Flexible
Don't over-specify. Leave room for cognition to choose approaches and tools. Your workflow should constrain order, not dictate implementation.

## Next Steps

- Learn [advanced workflow patterns](./c--advanced-workflow-patterns.md) for complex scenarios
- See [Tasks concept](../../3-concepts/tasks.md) for complete field reference
- See [Working with Tasks and Engine](./a--working-with-tasks-and-engine.md) for general task-driven work patterns
- See [Cognition concept](../../3-concepts/cognition.md) to understand how autonomous execution works

## Summary

Task relationships—particularly parent-child and depends-on—are the foundation of structured workflows in Discovery:

- **Parent-child relationships** organize work hierarchically, breaking large objectives into manageable pieces
- **Depends-on relationships** control execution order, ensuring prerequisites are met
- **Combining both** creates powerful workflows with clear structure and intelligent parallelization
- **Cognition uses relationships** to determine execution order, maximize parallelism, and track progress

Well-designed workflows help cognition work more effectively on your behalf while giving you clear visibility into how complex work is organized and progressing.
